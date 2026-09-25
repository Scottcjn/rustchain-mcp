"""Multipart video upload support for the ``bottube_upload`` MCP tool.

BoTTube's ``POST /api/upload`` (``bottube_server.upload_video``) only accepts a
``multipart/form-data`` request with the video bytes in the ``video`` file
field, authenticated by the ``X-API-Key`` header. Metadata travels as form
fields (``title``, ``description``, ``tags``, ``category``). There is no
server-side "fetch this URL" mode: a JSON body with a ``video_url`` is
rejected with ``400 No video file in request``.

This module validates inputs locally (so obvious mistakes fail fast with a
clear message instead of a 400 after a long transfer), optionally downloads
a remote video to a bounded temporary file, and streams the file to BoTTube.

Every failure is returned as ``{"ok": False, "error": ..., ...}``. The API
key is only ever placed in the request header; it is never logged, echoed,
or included in an error message.
"""

from __future__ import annotations

import ipaddress
import os
import pathlib
import socket
import tempfile
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

# Mirrors bottube_server.py (ALLOWED_VIDEO_EXT, MAX_VIDEO_SIZE,
# MAX_TITLE_LENGTH, MAX_DESCRIPTION_LENGTH, MAX_TAGS, MAX_TAG_LENGTH).
ALLOWED_VIDEO_EXT = (".mp4", ".webm", ".avi", ".mkv", ".mov")
SERVER_MAX_VIDEO_BYTES = 500 * 1024 * 1024
MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2000
MAX_TAGS = 15
MAX_TAG_LENGTH = 40

MAX_REDIRECTS = 5
_CHUNK = 64 * 1024

_CONTENT_TYPE_EXT = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/x-msvideo": ".avi",
    "video/avi": ".avi",
    "video/x-matroska": ".mkv",
    "video/quicktime": ".mov",
}
_EXT_CONTENT_TYPE = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
}


class UploadError(Exception):
    """An input or transfer problem that should be reported to the caller."""

    def __init__(self, message: str, **extra: Any):
        super().__init__(message)
        self.extra = extra


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def max_upload_bytes() -> int:
    """Byte cap for local files and URL downloads (``BOTTUBE_MAX_UPLOAD_MB``)."""
    mb = _env_int("BOTTUBE_MAX_UPLOAD_MB", SERVER_MAX_VIDEO_BYTES // (1024 * 1024))
    return min(mb * 1024 * 1024, SERVER_MAX_VIDEO_BYTES)


def upload_timeout() -> float:
    """Seconds for the upload request (``BOTTUBE_UPLOAD_TIMEOUT``, default 300).

    BoTTube transcodes synchronously before responding, so this is much
    longer than the 30 s default used for ordinary API reads.
    """
    return float(_env_int("BOTTUBE_UPLOAD_TIMEOUT", 300))


def download_timeout() -> float:
    """Seconds for the URL download (``BOTTUBE_DOWNLOAD_TIMEOUT``, default 120)."""
    return float(_env_int("BOTTUBE_DOWNLOAD_TIMEOUT", 120))


def _fmt_mb(n: int) -> str:
    return f"{n / (1024 * 1024):.0f} MB"


def validate_metadata(title: str, description: str, tags: str, category: str) -> dict[str, str]:
    """Return the form fields to send, or raise ``UploadError``."""
    title = (title or "").strip()
    if not title:
        raise UploadError("title is required")
    if len(title) > MAX_TITLE_LENGTH:
        raise UploadError(f"title is {len(title)} characters; BoTTube allows at most {MAX_TITLE_LENGTH}")
    description = (description or "").strip()
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise UploadError(
            f"description is {len(description)} characters; BoTTube allows at most {MAX_DESCRIPTION_LENGTH}"
        )
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    if len(tag_list) > MAX_TAGS:
        raise UploadError(f"{len(tag_list)} tags given; BoTTube allows at most {MAX_TAGS}")
    long_tags = [t for t in tag_list if len(t) > MAX_TAG_LENGTH]
    if long_tags:
        raise UploadError(f"tags longer than {MAX_TAG_LENGTH} characters: {long_tags}")
    fields = {"title": title, "description": description, "tags": ",".join(tag_list)}
    category = (category or "").strip().lower()
    if category:
        fields["category"] = category
    return fields


def resolve_local_file(video_path: str, limit: int) -> pathlib.Path:
    """Validate a local video path and return it resolved."""
    path = pathlib.Path(video_path).expanduser()
    if not path.exists():
        raise UploadError(f"video_path does not exist: {video_path}")
    if not path.is_file():
        raise UploadError(f"video_path is not a regular file: {video_path}")
    ext = path.suffix.lower()
    if ext not in ALLOWED_VIDEO_EXT:
        raise UploadError(
            f"unsupported video extension {ext or '(none)'!r}; allowed: {', '.join(ALLOWED_VIDEO_EXT)}"
        )
    size = path.stat().st_size
    if size == 0:
        raise UploadError(f"video_path is empty: {video_path}")
    if size > limit:
        raise UploadError(f"video is {_fmt_mb(size)}; the upload limit is {_fmt_mb(limit)}")
    return path.resolve()


def _default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


def _check_public_url(url: str, resolver: Callable[[str], list[str]]) -> None:
    """Allow only http(s) URLs whose host resolves exclusively to public IPs.

    This stops the tool from being used to pull files off loopback, the LAN,
    or cloud metadata endpoints. Use ``video_path`` for local files.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UploadError("video_url must be an http:// or https:// URL")
    host = parts.hostname
    if not host:
        raise UploadError("video_url has no host")
    try:
        addresses = resolver(host)
    except (OSError, UnicodeError) as exc:
        raise UploadError(f"could not resolve video_url host {host!r}: {exc}") from exc
    if not addresses:
        raise UploadError(f"could not resolve video_url host {host!r}")
    for addr in addresses:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
        if not ip.is_global:
            raise UploadError(
                f"video_url host {host!r} resolves to non-public address {ip}; "
                "download a local copy and pass video_path instead"
            )


def _extension_for(url: str, content_type: str) -> str:
    ext = pathlib.PurePosixPath(urlsplit(url).path).suffix.lower()
    if ext in ALLOWED_VIDEO_EXT:
        return ext
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime in _CONTENT_TYPE_EXT:
        return _CONTENT_TYPE_EXT[mime]
    raise UploadError(
        "could not determine a supported video type from the URL path or "
        f"Content-Type {mime or '(none)'!r}; allowed: {', '.join(ALLOWED_VIDEO_EXT)}"
    )


def download_to_temp(
    url: str,
    limit: int,
    client: httpx.Client,
    resolver: Callable[[str], list[str]] | None = None,
) -> tuple[pathlib.Path, str]:
    """Download ``url`` to a temporary file, enforcing ``limit`` bytes.

    Redirects are followed manually so every hop is re-checked against the
    public-address rule. Returns ``(temp_path, upload_filename)``; the
    caller must delete ``temp_path``.
    """
    resolver = resolver or _default_resolver
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        _check_public_url(current, resolver)
        with client.stream("GET", current) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    raise UploadError(f"video_url redirect ({resp.status_code}) without a Location header")
                current = urljoin(current, location)
                continue
            if resp.status_code >= 400:
                raise UploadError(
                    f"downloading video_url failed with HTTP {resp.status_code}",
                    status_code=resp.status_code,
                )
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > limit:
                raise UploadError(
                    f"video_url is {_fmt_mb(int(declared))}; the upload limit is {_fmt_mb(limit)}"
                )
            ext = _extension_for(current, resp.headers.get("content-type", ""))
            fd, tmp_name = tempfile.mkstemp(prefix="bottube-upload-", suffix=ext)
            tmp_path = pathlib.Path(tmp_name)
            total = 0
            try:
                with os.fdopen(fd, "wb") as out:
                    for chunk in resp.iter_bytes(_CHUNK):
                        total += len(chunk)
                        if total > limit:
                            raise UploadError(
                                f"video_url exceeded the upload limit of {_fmt_mb(limit)} while downloading"
                            )
                        out.write(chunk)
                if total == 0:
                    raise UploadError("video_url returned an empty body")
            except BaseException:
                tmp_path.unlink(missing_ok=True)
                raise
            name = pathlib.PurePosixPath(urlsplit(current).path).name
            if not name.lower().endswith(ext):
                name = f"video{ext}"
            return tmp_path, name
    raise UploadError(f"video_url redirected more than {MAX_REDIRECTS} times")


def _error_from_response(resp: httpx.Response) -> dict[str, Any]:
    detail: Any = None
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        detail = body.get("error") or body.get("message")
        result: dict[str, Any] = {"ok": False, "status_code": resp.status_code}
        result["error"] = f"BoTTube rejected the upload (HTTP {resp.status_code}): {detail or 'no error message'}"
        for key in ("code", "coach_note", "max_duration", "max_file_kb", "category"):
            if key in body:
                result[key] = body[key]
        return result
    text = (resp.text or "")[:200]
    return {
        "ok": False,
        "status_code": resp.status_code,
        "error": f"BoTTube rejected the upload (HTTP {resp.status_code}): {text or 'empty response'}",
    }


def post_multipart(
    client: httpx.Client,
    upload_url: str,
    api_key: str,
    fields: dict[str, str],
    file_path: pathlib.Path,
    filename: str,
    timeout: float,
) -> dict[str, Any]:
    """Send the multipart request and normalise the response."""
    mime = _EXT_CONTENT_TYPE.get(pathlib.PurePosixPath(filename).suffix.lower(), "application/octet-stream")
    try:
        with open(file_path, "rb") as fh:
            resp = client.post(
                upload_url,
                headers={"X-API-Key": api_key},
                data=fields,
                files={"video": (filename, fh, mime)},
                timeout=timeout,
            )
    except httpx.TimeoutException:
        return {
            "ok": False,
            "error": (
                f"BoTTube upload timed out after {timeout:.0f}s; the video may still be "
                "processing. Raise BOTTUBE_UPLOAD_TIMEOUT for large files."
            ),
        }
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"BoTTube upload failed: {type(exc).__name__}: {exc}"}

    if resp.status_code >= 400:
        return _error_from_response(resp)
    try:
        body = resp.json()
    except ValueError:
        return {"ok": False, "status_code": resp.status_code, "error": "BoTTube returned a non-JSON response"}
    if not isinstance(body, dict):
        return {"ok": False, "status_code": resp.status_code, "error": "BoTTube returned an unexpected response"}
    return body
