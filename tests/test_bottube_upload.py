"""bottube_upload must send a real multipart file upload.

BoTTube's ``POST /api/upload`` reads the video from ``request.files["video"]``
and metadata from form fields, authenticated by ``X-API-Key``; a JSON body is
rejected with ``400 No video file in request``. These tests drive the tool
through ``httpx.MockTransport`` so the actual encoded request is inspected.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from rustchain_mcp import bottube_media
from rustchain_mcp import server as srv

API_KEY = "bt_secret_key_do_not_leak"
OK_BODY = {
    "ok": True,
    "video_id": "abc123XYZ",
    "watch_url": "/watch/abc123XYZ",
    "stream_url": "/api/videos/abc123XYZ/stream",
    "title": "Demo",
}


class _Upload:
    """Mock BoTTube endpoint that parses the multipart body like Flask would."""

    def __init__(self, status=200, body=None):
        self.status = status
        self.body = OK_BODY if body is None else body
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        return httpx.Response(self.status, json=self.body)


def _parse_multipart(request: httpx.Request) -> tuple[dict, dict]:
    """Return (form_fields, files) where files maps name -> (filename, ctype, bytes)."""
    ctype = request.headers["content-type"]
    assert ctype.startswith("multipart/form-data; boundary=")
    boundary = ctype.split("boundary=", 1)[1].encode()
    fields, files = {}, {}
    for part in request.content.split(b"--" + boundary):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        head, _, data = part.partition(b"\r\n\r\n")
        headers = head.decode()
        name = headers.split('name="', 1)[1].split('"', 1)[0]
        if 'filename="' in headers:
            filename = headers.split('filename="', 1)[1].split('"', 1)[0]
            part_ctype = headers.split("Content-Type: ", 1)[1].split("\r\n", 1)[0]
            files[name] = (filename, part_ctype, data)
        else:
            fields[name] = data.decode()
    return fields, files


@pytest.fixture
def upload(monkeypatch):
    endpoint = _Upload()
    client = httpx.Client(transport=httpx.MockTransport(endpoint))
    monkeypatch.setattr(srv, "get_client", lambda: client)
    monkeypatch.setattr(srv, "BOTTUBE_URL", "https://bottube.test")
    monkeypatch.delenv("BOTTUBE_API_KEY", raising=False)
    return endpoint


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x01" * 64)
    return path


def _download(monkeypatch, handler, addresses=("93.184.216.34",)):
    """Route video_url downloads through a mock transport with a fake resolver."""
    monkeypatch.setattr(
        srv,
        "_bottube_download_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    monkeypatch.setattr(bottube_media, "_default_resolver", lambda host: list(addresses))


# ── local file uploads ─────────────────────────────────────────


def test_local_file_is_sent_as_multipart_video_field(upload, video):
    result = srv.bottube_upload(
        "Demo", video_path=str(video), description="desc",
        tags="ai, rustchain ,,", category="Retro", api_key=API_KEY,
    )

    assert result["ok"] is True
    assert result["video_id"] == "abc123XYZ"
    assert result["watch_url"] == "https://bottube.test/watch/abc123XYZ"

    (req,) = upload.requests
    assert req.method == "POST"
    assert str(req.url) == "https://bottube.test/api/upload"
    assert req.headers["X-API-Key"] == API_KEY
    assert "authorization" not in req.headers
    fields, files = _parse_multipart(req)
    assert fields == {"title": "Demo", "description": "desc", "tags": "ai,rustchain", "category": "retro"}
    assert set(files) == {"video"}
    filename, ctype, data = files["video"]
    assert filename == "clip.mp4"
    assert ctype == "video/mp4"
    assert data == video.read_bytes()


def test_no_json_body_is_sent(upload, video):
    srv.bottube_upload("Demo", video_path=str(video), api_key=API_KEY)
    (req,) = upload.requests
    assert not req.headers["content-type"].startswith("application/json")
    assert b"video_url" not in req.content


def test_api_key_falls_back_to_env(upload, video, monkeypatch):
    monkeypatch.setenv("BOTTUBE_API_KEY", API_KEY)
    result = srv.bottube_upload("Demo", video_path=str(video))
    assert result["ok"] is True
    assert upload.requests[0].headers["X-API-Key"] == API_KEY


# ── input validation (no request is made) ──────────────────────


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"api_key": ""}, "API key required"),
        ({"video_path": ""}, "exactly one of video_path"),
        ({"video_url": "https://cdn.test/v.mp4"}, "exactly one of video_path"),
        ({"title": "   "}, "title is required"),
        ({"title": "x" * 201}, "at most 200"),
        ({"description": "d" * 2001}, "at most 2000"),
        ({"tags": ",".join(f"t{i}" for i in range(16))}, "at most 15"),
        ({"tags": "ok," + "y" * 41}, "longer than 40"),
    ],
)
def test_invalid_inputs_fail_before_any_request(upload, video, kwargs, message):
    args = {"title": "Demo", "video_path": str(video), "api_key": API_KEY}
    args.update(kwargs)
    result = srv.bottube_upload(**args)
    assert result["ok"] is False
    assert message in result["error"]
    assert upload.requests == []


def test_missing_file(upload, tmp_path):
    result = srv.bottube_upload("Demo", video_path=str(tmp_path / "nope.mp4"), api_key=API_KEY)
    assert result["ok"] is False and "does not exist" in result["error"]
    assert upload.requests == []


def test_directory_is_rejected(upload, tmp_path):
    folder = tmp_path / "dir.mp4"
    folder.mkdir()
    result = srv.bottube_upload("Demo", video_path=str(folder), api_key=API_KEY)
    assert result["ok"] is False and "not a regular file" in result["error"]


def test_bad_extension(upload, tmp_path):
    path = tmp_path / "clip.gif"
    path.write_bytes(b"GIF89a")
    result = srv.bottube_upload("Demo", video_path=str(path), api_key=API_KEY)
    assert result["ok"] is False and "unsupported video extension" in result["error"]
    assert upload.requests == []


def test_empty_file(upload, tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"")
    result = srv.bottube_upload("Demo", video_path=str(path), api_key=API_KEY)
    assert result["ok"] is False and "empty" in result["error"]


def test_oversized_file(upload, video, monkeypatch):
    monkeypatch.setattr(bottube_media, "max_upload_bytes", lambda: 10)
    result = srv.bottube_upload("Demo", video_path=str(video), api_key=API_KEY)
    assert result["ok"] is False and "upload limit" in result["error"]
    assert upload.requests == []


def test_upload_limit_never_exceeds_server_cap(monkeypatch):
    monkeypatch.setenv("BOTTUBE_MAX_UPLOAD_MB", "999999")
    assert bottube_media.max_upload_bytes() == bottube_media.SERVER_MAX_VIDEO_BYTES
    monkeypatch.setenv("BOTTUBE_MAX_UPLOAD_MB", "50")
    assert bottube_media.max_upload_bytes() == 50 * 1024 * 1024
    monkeypatch.setenv("BOTTUBE_MAX_UPLOAD_MB", "garbage")
    assert bottube_media.max_upload_bytes() == bottube_media.SERVER_MAX_VIDEO_BYTES


# ── upstream errors ────────────────────────────────────────────


@pytest.mark.parametrize(
    "status, body, expect",
    [
        (400, {"error": "No video file in request"}, "No video file in request"),
        (401, {"error": "Invalid API key"}, "Invalid API key"),
        (429, {"error": "Upload rate limit exceeded (max 5/hour)."}, "rate limit"),
        (422, {"error": "Upload held for coaching review.", "code": "CONTENT_POLICY_VIOLATION",
               "coach_note": "rewrite it"}, "coaching review"),
    ],
)
def test_bottube_errors_are_structured(upload, video, status, body, expect):
    upload.status, upload.body = status, body
    result = srv.bottube_upload("Demo", video_path=str(video), api_key=API_KEY)
    assert result["ok"] is False
    assert result["status_code"] == status
    assert expect in result["error"]
    if "code" in body:
        assert result["code"] == body["code"] and result["coach_note"] == "rewrite it"
    assert API_KEY not in repr(result)


def test_upload_timeout_is_reported(video, monkeypatch):
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    client = httpx.Client(transport=httpx.MockTransport(boom))
    monkeypatch.setattr(srv, "get_client", lambda: client)
    result = srv.bottube_upload("Demo", video_path=str(video), api_key=API_KEY)
    assert result["ok"] is False and "timed out" in result["error"]
    assert API_KEY not in repr(result)


def test_api_key_never_logged(upload, video, caplog):
    caplog.set_level(logging.DEBUG)
    upload.status, upload.body = 401, {"error": "Invalid API key"}
    srv.bottube_upload("Demo", video_path=str(video), api_key=API_KEY)
    srv.bottube_upload("Demo", video_path="/nonexistent.mp4", api_key=API_KEY)
    assert API_KEY not in caplog.text


# ── video_url: download then upload ────────────────────────────


def test_url_is_downloaded_then_uploaded(upload, monkeypatch):
    payload = b"\x00\x00\x00\x18ftypmp42" + b"\x02" * 300
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=payload, headers={"content-type": "video/mp4"})

    _download(monkeypatch, handler)
    created = []
    real_mkstemp = bottube_media.tempfile.mkstemp

    def tracking_mkstemp(*a, **kw):
        fd, name = real_mkstemp(*a, **kw)
        created.append(name)
        return fd, name

    monkeypatch.setattr(bottube_media.tempfile, "mkstemp", tracking_mkstemp)

    result = srv.bottube_upload("Demo", video_url="https://cdn.example.com/media/talk.mp4", api_key=API_KEY)

    assert result["ok"] is True
    assert str(seen[0].url) == "https://cdn.example.com/media/talk.mp4"
    assert "x-api-key" not in seen[0].headers  # the key never goes to the third-party host
    _, files = _parse_multipart(upload.requests[0])
    assert files["video"][0] == "talk.mp4"
    assert files["video"][2] == payload
    import os

    assert created and not any(os.path.exists(p) for p in created), "temp file must be removed"


def test_url_extension_from_content_type(upload, monkeypatch):
    _download(monkeypatch, lambda r: httpx.Response(200, content=b"1234", headers={"content-type": "video/webm"}))
    result = srv.bottube_upload("Demo", video_url="https://cdn.example.com/stream?id=9", api_key=API_KEY)
    assert result["ok"] is True
    _, files = _parse_multipart(upload.requests[0])
    assert files["video"][0] == "video.webm" and files["video"][1] == "video/webm"


def test_url_unknown_type_rejected(upload, monkeypatch):
    _download(monkeypatch, lambda r: httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}))
    result = srv.bottube_upload("Demo", video_url="https://example.com/page", api_key=API_KEY)
    assert result["ok"] is False and "supported video type" in result["error"]
    assert upload.requests == []


def test_url_declared_size_over_limit(upload, monkeypatch):
    monkeypatch.setattr(bottube_media, "max_upload_bytes", lambda: 100)
    _download(monkeypatch, lambda r: httpx.Response(
        200, content=b"x" * 10, headers={"content-type": "video/mp4", "content-length": "5000"}))
    result = srv.bottube_upload("Demo", video_url="https://cdn.example.com/v.mp4", api_key=API_KEY)
    assert result["ok"] is False and "upload limit" in result["error"]
    assert upload.requests == []


def test_url_streamed_size_over_limit(upload, monkeypatch):
    monkeypatch.setattr(bottube_media, "max_upload_bytes", lambda: 100)

    def handler(request):
        # No Content-Length: the cap must be enforced while streaming.
        return httpx.Response(200, content=iter([b"x" * 64] * 4), headers={"content-type": "video/mp4"})

    _download(monkeypatch, handler)
    result = srv.bottube_upload("Demo", video_url="https://cdn.example.com/v.mp4", api_key=API_KEY)
    assert result["ok"] is False and "exceeded the upload limit" in result["error"]
    assert upload.requests == []


def test_url_http_error(upload, monkeypatch):
    _download(monkeypatch, lambda r: httpx.Response(404))
    result = srv.bottube_upload("Demo", video_url="https://cdn.example.com/v.mp4", api_key=API_KEY)
    assert result["ok"] is False and "HTTP 404" in result["error"] and result["status_code"] == 404


def test_url_download_timeout(upload, monkeypatch):
    def handler(request):
        raise httpx.ConnectTimeout("slow", request=request)

    _download(monkeypatch, handler)
    result = srv.bottube_upload("Demo", video_url="https://cdn.example.com/v.mp4", api_key=API_KEY)
    assert result["ok"] is False and "timed out downloading" in result["error"]


@pytest.mark.parametrize("url", ["ftp://example.com/v.mp4", "file:///etc/passwd", "v.mp4"])
def test_url_scheme_must_be_http(upload, monkeypatch, url):
    _download(monkeypatch, lambda r: httpx.Response(200, content=b"x"))
    result = srv.bottube_upload("Demo", video_url=url, api_key=API_KEY)
    assert result["ok"] is False and "http:// or https://" in result["error"]


@pytest.mark.parametrize("addr", ["127.0.0.1", "10.0.0.5", "192.168.0.160", "169.254.169.254", "::1", "100.75.100.89"])
def test_url_to_private_address_rejected(upload, monkeypatch, addr):
    calls = []
    _download(monkeypatch, lambda r: calls.append(r) or httpx.Response(200, content=b"x"), addresses=(addr,))
    result = srv.bottube_upload("Demo", video_url="https://sneaky.example/v.mp4", api_key=API_KEY)
    assert result["ok"] is False and "non-public address" in result["error"]
    assert calls == [] and upload.requests == []


def test_redirect_to_private_address_rejected(upload, monkeypatch):
    def handler(request):
        if request.url.host == "cdn.example.com":
            return httpx.Response(302, headers={"location": "http://internal.example/v.mp4"})
        raise AssertionError("must not fetch the internal host")

    monkeypatch.setattr(
        srv, "_bottube_download_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    monkeypatch.setattr(
        bottube_media, "_default_resolver",
        lambda host: ["93.184.216.34"] if host == "cdn.example.com" else ["10.1.2.3"],
    )
    result = srv.bottube_upload("Demo", video_url="https://cdn.example.com/v.mp4", api_key=API_KEY)
    assert result["ok"] is False and "non-public address" in result["error"]
    assert upload.requests == []


def test_redirect_to_public_host_followed(upload, monkeypatch):
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(301, headers={"location": "/real/clip.mov"})
        return httpx.Response(200, content=b"mov-bytes", headers={"content-type": "application/octet-stream"})

    _download(monkeypatch, handler)
    result = srv.bottube_upload("Demo", video_url="https://cdn.example.com/start", api_key=API_KEY)
    assert result["ok"] is True
    _, files = _parse_multipart(upload.requests[0])
    assert files["video"][:2] == ("clip.mov", "video/quicktime")


def test_redirect_loop_capped(upload, monkeypatch):
    _download(monkeypatch, lambda r: httpx.Response(302, headers={"location": "/again"}))
    result = srv.bottube_upload("Demo", video_url="https://cdn.example.com/start", api_key=API_KEY)
    assert result["ok"] is False and "redirected more than" in result["error"]
