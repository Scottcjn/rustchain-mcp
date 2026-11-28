# SPDX-License-Identifier: MIT
"""Security and SSRF hardening regression tests for rustchain_mcp.bottube_media."""

from __future__ import annotations

import ipaddress

import httpx
import pytest

from rustchain_mcp import bottube_media
from rustchain_mcp import server as srv

API_KEY = "bt_super_secret_key_99999"


class _OkUpload:
    def __init__(self, status: int = 200, body: dict | None = None, text: str | None = None):
        self.status = status
        self.body = body
        self.text = text
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        if self.text is not None:
            return httpx.Response(self.status, text=self.text)
        return httpx.Response(
            self.status,
            json=self.body
            if self.body is not None
            else {"ok": True, "video_id": "v1", "watch_url": "/watch/v1"},
        )


def _setup_download(monkeypatch, handler, addresses=("93.184.216.34",)):
    monkeypatch.setattr(
        srv,
        "_bottube_download_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    monkeypatch.setattr(bottube_media, "_default_resolver", lambda _host: list(addresses))


@pytest.mark.parametrize(
    "addr",
    [
        # NAT64 well-known prefix (RFC 6052) and local prefix (RFC 8215)
        "64:ff9b::127.0.0.1",
        "64:ff9b::169.254.169.254",
        "64:ff9b::10.0.0.1",
        "64:ff9b:1::10.0.0.1",
        # IPv4 and IPv6 multicast (Python ip.is_global is True!)
        "224.0.0.1",
        "239.255.255.250",
        "ff02::1",
        "ff0e::1",
        # Unspecified, reserved, IPv4-mapped private, 6to4 private, Teredo private
        str(ipaddress.IPv4Address(0)),
        "::",
        "240.0.0.1",
        "255.255.255.255",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "2002:7f00:0001::1",
        "2002:a9fe:a9fe::1",
        "2001:0000:4136:e378:8000:63bf:3fff:fdd2",
        # Interface-scoped IPv6 zone IDs (even on global-looking prefix)
        "fe80::1%eth0",
        "2606:2800:220:1:248:1893:25c8:1946%eth0",
    ],
)
def test_check_public_url_blocks_nat64_multicast_zoned_and_transition_ssrf(addr):
    with pytest.raises(bottube_media.UploadError, match="non-public address"):
        bottube_media._check_public_url("https://cdn.example.com/v.mp4", lambda _host: [addr])


@pytest.mark.parametrize(
    "addr",
    [
        "93.184.216.34",
        "2606:2800:220:1:248:1893:25c8:1946",
        "::ffff:93.184.216.34",
    ],
)
def test_check_public_url_allows_legitimate_public_unicast_addresses(addr):
    bottube_media._check_public_url("https://cdn.example.com/v.mp4", lambda _host: [addr])


def test_check_public_url_rejects_credentials_control_chars_and_invalid_port():
    def _resolver(_host: str) -> list[str]:
        return ["93.184.216.34"]

    with pytest.raises(bottube_media.UploadError, match="credentials"):
        bottube_media._check_public_url("https://user:secret@cdn.example.com/v.mp4", _resolver)
    with pytest.raises(bottube_media.UploadError, match="control characters"):
        bottube_media._check_public_url("https://cdn.example.com/v.mp4\r\nX-Test: 1", _resolver)
    with pytest.raises(bottube_media.UploadError, match="invalid port"):
        bottube_media._check_public_url("https://cdn.example.com:99999/v.mp4", _resolver)
    with pytest.raises(bottube_media.UploadError, match="invalid address"):
        bottube_media._check_public_url("https://cdn.example.com/v.mp4", lambda _host: ["not-an-ip"])


def test_download_to_temp_sanitizes_tricky_filenames_and_whitespace_content_length():
    def _ok_handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"1234", headers={"content-type": "video/mp4"})

    client = httpx.Client(transport=httpx.MockTransport(_ok_handler), follow_redirects=False)
    try:
        tmp1, name1 = bottube_media.download_to_temp(
            'https://cdn.example.com/bad"file;x=1.mp4',
            1024,
            client,
            resolver=lambda _h: ["93.184.216.34"],
        )
        tmp1.unlink(missing_ok=True)
        assert '"' not in name1
        assert ";" not in name1
        assert name1.endswith(".mp4")

        tmp2, name2 = bottube_media.download_to_temp(
            "https://cdn.example.com/.mp4",
            1024,
            client,
            resolver=lambda _h: ["93.184.216.34"],
        )
        tmp2.unlink(missing_ok=True)
        assert name2 == "video.mp4"
    finally:
        client.close()

    # Whitespace-padded Content-Length header must still enforce pre-check cap
    def _padded_cl(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"x" * 10,
            headers={"content-type": "video/mp4", "content-length": " 5000 "},
        )

    client2 = httpx.Client(transport=httpx.MockTransport(_padded_cl), follow_redirects=False)
    try:
        with pytest.raises(bottube_media.UploadError, match="upload limit"):
            bottube_media.download_to_temp(
                "https://cdn.example.com/v.mp4",
                100,
                client2,
                resolver=lambda _h: ["93.184.216.34"],
            )
    finally:
        client2.close()


def test_download_to_temp_rejects_unexpected_non_2xx_and_nonpositive_limit():
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _r: httpx.Response(304)),
        follow_redirects=False,
    )
    try:
        with pytest.raises(bottube_media.UploadError, match="unexpected HTTP 304"):
            bottube_media.download_to_temp(
                "https://cdn.example.com/v.mp4",
                1024,
                client,
                resolver=lambda _h: ["93.184.216.34"],
            )
        with pytest.raises(bottube_media.UploadError, match="positive"):
            bottube_media.download_to_temp(
                "https://cdn.example.com/v.mp4",
                0,
                client,
                resolver=lambda _h: ["93.184.216.34"],
            )
    finally:
        client.close()


def test_resolve_local_file_and_validate_metadata_reject_nul_bytes():
    with pytest.raises(bottube_media.UploadError, match="invalid"):
        bottube_media.resolve_local_file("clip\x00.mp4", 1024)
    with pytest.raises(bottube_media.UploadError, match="positive"):
        bottube_media.resolve_local_file("clip.mp4", 0)
    with pytest.raises(bottube_media.UploadError, match="NUL"):
        bottube_media.validate_metadata("Demo\x00", "", "", "")


def test_post_multipart_redacts_api_key_from_upstream_and_transport_errors(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x01" * 32)

    # 1. Upstream JSON error echoing API key
    echo_json = _OkUpload(status=401, body={"error": f"bad key {API_KEY}"})
    c1 = httpx.Client(transport=httpx.MockTransport(echo_json))
    try:
        res1 = bottube_media.post_multipart(
            c1, "https://bottube.test/api/upload", API_KEY, {"title": "Demo"}, video, "clip.mp4", 10.0
        )
        assert res1["ok"] is False
        assert API_KEY not in repr(res1)
        assert "[REDACTED]" in res1["error"]
    finally:
        c1.close()

    # 2. Upstream plain-text error echoing API key
    echo_text = _OkUpload(status=502, text=f"proxy failed with {API_KEY}")
    c2 = httpx.Client(transport=httpx.MockTransport(echo_text))
    try:
        res2 = bottube_media.post_multipart(
            c2, "https://bottube.test/api/upload", API_KEY, {"title": "Demo"}, video, "clip.mp4", 10.0
        )
        assert res2["ok"] is False
        assert API_KEY not in repr(res2)
        assert "[REDACTED]" in res2["error"]
    finally:
        c2.close()

    # 3. httpx transport error echoing API key
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed with {API_KEY}", request=request)

    c3 = httpx.Client(transport=httpx.MockTransport(_boom))
    try:
        res3 = bottube_media.post_multipart(
            c3, "https://bottube.test/api/upload", API_KEY, {"title": "Demo"}, video, "clip.mp4", 10.0
        )
        assert res3["ok"] is False
        assert API_KEY not in repr(res3)
        assert "[REDACTED]" in res3["error"]
    finally:
        c3.close()


def test_bottube_upload_end_to_end_rejects_nat64_metadata_ssrf(monkeypatch):
    endpoint = _OkUpload()
    client = httpx.Client(transport=httpx.MockTransport(endpoint))
    monkeypatch.setattr(srv, "get_client", lambda: client)
    monkeypatch.setattr(srv, "BOTTUBE_URL", "https://bottube.test")
    calls: list[httpx.Request] = []
    _setup_download(
        monkeypatch,
        lambda req: calls.append(req) or httpx.Response(200, content=b"secret"),
        addresses=("64:ff9b::169.254.169.254",),
    )

    result = srv.bottube_upload(
        "Demo",
        video_url="https://nat64-imds.example/video.mp4",
        api_key=API_KEY,
    )
    assert result["ok"] is False
    assert "non-public address" in result["error"]
    assert calls == []
    assert endpoint.requests == []
