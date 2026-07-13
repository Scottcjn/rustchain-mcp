"""Read-only RustChain event relay with bounded batch and SSE delivery."""

from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import logging
import math
import os
import signal
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx


LOGGER = logging.getLogger("rustchain_mcp.events")
_SOURCE_PATHS = (
    ("health", "/health"),
    ("epoch", "/epoch"),
    ("miners", "/api/miners"),
)


class RelayInputError(ValueError):
    """Raised for invalid cursor, limit, wait, or listener configuration."""


class _PollFailure(Exception):
    def __init__(self, data: dict[str, Any]):
        super().__init__(data["error"]["code"])
        self.data = data


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise RelayInputError(f"{name} must be an integer") from exc


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise RelayInputError(f"{name} must be a number") from exc


def _tls_verify_from_env() -> bool | str:
    value = os.environ.get(
        "RUSTCHAIN_CA_BUNDLE",
        os.environ.get("RUSTCHAIN_TLS_VERIFY", "true"),
    )
    lowered = value.lower()
    if lowered in ("false", "0", "no"):
        return False
    if lowered in ("true", "1", "yes"):
        return True
    return value


def _validate_node_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RelayInputError("RUSTCHAIN_NODE must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise RelayInputError("RUSTCHAIN_NODE must not contain credentials")
    if parsed.query or parsed.fragment:
        raise RelayInputError("RUSTCHAIN_NODE must not contain a query or fragment")
    return value.rstrip("/")


@dataclass(frozen=True)
class EventRelayConfig:
    """Validated polling and retention limits for an event relay."""

    node_url: str = "https://50.28.86.131"
    poll_interval: float = 5.0
    request_timeout: float = 5.0
    backoff_initial: float = 1.0
    backoff_max: float = 60.0
    buffer_size: int = 256
    max_batch_size: int = 100
    max_wait_seconds: float = 30.0
    max_response_bytes: int = 131_072

    @classmethod
    def from_env(cls) -> "EventRelayConfig":
        config = cls(
            node_url=os.environ.get("RUSTCHAIN_NODE", cls.node_url),
            poll_interval=_env_float(
                "RUSTCHAIN_EVENT_POLL_INTERVAL", cls.poll_interval
            ),
            request_timeout=_env_float(
                "RUSTCHAIN_EVENT_REQUEST_TIMEOUT", cls.request_timeout
            ),
            backoff_initial=_env_float(
                "RUSTCHAIN_EVENT_BACKOFF_INITIAL", cls.backoff_initial
            ),
            backoff_max=_env_float("RUSTCHAIN_EVENT_BACKOFF_MAX", cls.backoff_max),
            buffer_size=_env_int("RUSTCHAIN_EVENT_BUFFER_SIZE", cls.buffer_size),
            max_batch_size=_env_int("RUSTCHAIN_EVENT_BATCH_LIMIT", cls.max_batch_size),
            max_wait_seconds=_env_float(
                "RUSTCHAIN_EVENT_LONG_POLL_MAX", cls.max_wait_seconds
            ),
            max_response_bytes=_env_int(
                "RUSTCHAIN_EVENT_RESPONSE_BYTES", cls.max_response_bytes
            ),
        )
        return config.validated()

    def validated(self) -> "EventRelayConfig":
        node_url = _validate_node_url(self.node_url)
        if not 0.05 <= self.poll_interval <= 3600:
            raise RelayInputError("poll_interval must be between 0.05 and 3600 seconds")
        if not 0.05 <= self.request_timeout <= 120:
            raise RelayInputError(
                "request_timeout must be between 0.05 and 120 seconds"
            )
        if not 0.05 <= self.backoff_initial <= 3600:
            raise RelayInputError(
                "backoff_initial must be between 0.05 and 3600 seconds"
            )
        if not self.backoff_initial <= self.backoff_max <= 3600:
            raise RelayInputError(
                "backoff_max must be at least backoff_initial and at most 3600"
            )
        if not 1 <= self.buffer_size <= 100_000:
            raise RelayInputError("buffer_size must be between 1 and 100000")
        if not 1 <= self.max_batch_size <= 1000:
            raise RelayInputError("max_batch_size must be between 1 and 1000")
        if not 0 <= self.max_wait_seconds <= 120:
            raise RelayInputError("max_wait_seconds must be between 0 and 120")
        if not 1024 <= self.max_response_bytes <= 10_485_760:
            raise RelayInputError(
                "max_response_bytes must be between 1024 and 10485760"
            )
        return replace(self, node_url=node_url)


@dataclass(frozen=True)
class SSEConfig:
    """Listener limits for the standalone SSE endpoint."""

    host: str = "127.0.0.1"
    port: int = 8766
    max_clients: int = 16
    heartbeat_seconds: float = 15.0
    write_timeout: float = 30.0
    bearer_token: str = ""
    allow_remote: bool = False

    @classmethod
    def from_env(cls) -> "SSEConfig":
        return cls(
            host=os.environ.get("RUSTCHAIN_EVENT_SSE_HOST", cls.host),
            port=_env_int("RUSTCHAIN_EVENT_SSE_PORT", cls.port),
            max_clients=_env_int("RUSTCHAIN_EVENT_SSE_MAX_CLIENTS", cls.max_clients),
            heartbeat_seconds=_env_float(
                "RUSTCHAIN_EVENT_SSE_HEARTBEAT", cls.heartbeat_seconds
            ),
            write_timeout=_env_float(
                "RUSTCHAIN_EVENT_SSE_WRITE_TIMEOUT", cls.write_timeout
            ),
            bearer_token=os.environ.get("RUSTCHAIN_EVENT_TOKEN", ""),
            allow_remote=os.environ.get("RUSTCHAIN_EVENT_ALLOW_REMOTE", "false").lower()
            in ("true", "1", "yes"),
        ).validated()

    def validated(self) -> "SSEConfig":
        if not 0 <= self.port <= 65535:
            raise RelayInputError("port must be between 0 and 65535")
        if not 1 <= self.max_clients <= 1000:
            raise RelayInputError("max_clients must be between 1 and 1000")
        if not 0.1 <= self.heartbeat_seconds <= 120:
            raise RelayInputError(
                "heartbeat_seconds must be between 0.1 and 120 seconds"
            )
        if not 0.1 <= self.write_timeout <= 300:
            raise RelayInputError("write_timeout must be between 0.1 and 300 seconds")

        is_loopback = self.host == "localhost"
        try:
            is_loopback = is_loopback or ipaddress.ip_address(self.host).is_loopback
        except ValueError:
            pass
        if not is_loopback and not self.allow_remote:
            raise RelayInputError("non-loopback SSE binds require --allow-remote")
        if not is_loopback and not self.bearer_token:
            raise RelayInputError(
                "non-loopback SSE binds require RUSTCHAIN_EVENT_TOKEN"
            )
        if self.bearer_token and len(self.bearer_token) < 16:
            raise RelayInputError(
                "RUSTCHAIN_EVENT_TOKEN must contain at least 16 characters"
            )
        return self


def canonical_json(value: Any) -> str:
    """Serialize JSON identically across batches and SSE delivery."""
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _normalize_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalize_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalize_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise _PollFailure(_error_data("INVALID_JSON", retryable=False))
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise _PollFailure(_error_data("INVALID_JSON", retryable=False))


def _error_data(
    code: str, *, retryable: bool, status_code: int | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "retryable": retryable}
    if status_code is not None:
        error["status_code"] = status_code
    return {"ok": False, "error": error}


def _normalize_source(source: str, payload: Any) -> Any:
    if source in ("health", "epoch"):
        if not isinstance(payload, Mapping):
            raise _PollFailure(_error_data("MISSING_EXPECTED_OBJECT", retryable=False))
        return _normalize_json(payload)

    if isinstance(payload, list):
        miners = payload
        normalized: dict[str, Any] = {}
    elif isinstance(payload, Mapping):
        if not isinstance(payload.get("miners"), list):
            raise _PollFailure(_error_data("MISSING_MINERS", retryable=False))
        miners = payload["miners"]
        normalized = _normalize_json(payload)
    else:
        raise _PollFailure(_error_data("MISSING_MINERS", retryable=False))

    normalized_miners = [_normalize_json(miner) for miner in miners]
    normalized_miners.sort(key=canonical_json)
    normalized["miners"] = normalized_miners
    normalized["total_miners"] = len(normalized_miners)
    return _normalize_json(normalized)


@dataclass(frozen=True)
class RelayEvent:
    cursor: int
    event_type: str
    source: str
    serialized: str

    def as_dict(self) -> dict[str, Any]:
        return json.loads(self.serialized)


@dataclass(frozen=True)
class _SourceState:
    available: bool
    canonical_data: str


class EventRelay:
    """Poll fixed read-only node paths and retain normalized state changes."""

    def __init__(
        self,
        config: EventRelayConfig,
        *,
        client: httpx.Client | None = None,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ):
        self.config = config.validated()
        self._client = client or httpx.Client(
            timeout=self.config.request_timeout,
            verify=_tls_verify_from_env(),
            follow_redirects=False,
        )
        self._owns_client = client is None
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._events: deque[RelayEvent] = deque(maxlen=self.config.buffer_size)
        self._condition = threading.Condition()
        self._source_states: dict[str, _SourceState] = {}
        self._next_cursor = 1
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._client_closed = False

    def start(self) -> None:
        """Start polling. Calling start more than once is harmless."""
        with self._condition:
            if self._stop_event.is_set():
                raise RuntimeError("a stopped event relay cannot be restarted")
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._poll_loop,
                name="rustchain-event-poller",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float | None = None) -> bool:
        """Request shutdown, wake long polls, and close the owned HTTP client."""
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(
                timeout if timeout is not None else self.config.request_timeout + 1
            )
        stopped = not thread or not thread.is_alive()
        if stopped and self._owns_client and not self._client_closed:
            self._client.close()
            self._client_closed = True
        return stopped

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    def poll_once(self) -> bool:
        """Poll all fixed endpoints once; return true only if all succeeded."""
        all_succeeded = True
        for source, path in _SOURCE_PATHS:
            try:
                payload = self._fetch_source(path)
                normalized = _normalize_source(source, payload)
                self._record_success(source, normalized)
            except _PollFailure as exc:
                all_succeeded = False
                self._record_failure(source, exc.data)
            except (httpx.TimeoutException, TimeoutError):
                all_succeeded = False
                self._record_failure(
                    source, _error_data("UPSTREAM_TIMEOUT", retryable=True)
                )
            except httpx.RequestError:
                all_succeeded = False
                self._record_failure(
                    source, _error_data("TRANSPORT_RETRYABLE", retryable=True)
                )
            except Exception:
                all_succeeded = False
                self._record_failure(
                    source, _error_data("UPSTREAM_INVALID_RESPONSE", retryable=False)
                )
        return all_succeeded

    def backoff_delay(self, consecutive_failures: int) -> float:
        """Return deterministic capped exponential backoff for a failure count."""
        if consecutive_failures <= 0:
            return self.config.poll_interval
        exponent = min(consecutive_failures - 1, 30)
        return min(self.config.backoff_initial * (2**exponent), self.config.backoff_max)

    def get_batch(
        self,
        after_cursor: int = 0,
        limit: int = 50,
        wait_seconds: float = 0.0,
    ) -> dict[str, Any]:
        """Return a bounded batch, waiting cooperatively for a newer event."""
        self._validate_batch_input(after_cursor, limit, wait_seconds)
        deadline = self._monotonic_clock() + wait_seconds

        with self._condition:
            while True:
                oldest_cursor = self._events[0].cursor if self._events else 0
                latest_cursor = self._events[-1].cursor if self._events else 0
                if after_cursor > latest_cursor:
                    raise RelayInputError(
                        f"after_cursor {after_cursor} is ahead of latest cursor {latest_cursor}"
                    )

                cursor_expired = bool(self._events and after_cursor < oldest_cursor - 1)
                effective_cursor = oldest_cursor - 1 if cursor_expired else after_cursor
                available = [
                    event for event in self._events if event.cursor > effective_cursor
                ]
                if available or wait_seconds == 0 or self._stop_event.is_set():
                    break
                remaining = deadline - self._monotonic_clock()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)

            selected = available[:limit]
            next_cursor = selected[-1].cursor if selected else after_cursor
            has_more = any(event.cursor > next_cursor for event in self._events)
            timed_out = bool(
                wait_seconds > 0
                and not selected
                and not self._stop_event.is_set()
                and self._monotonic_clock() >= deadline
            )
            return {
                "cursor_expired": cursor_expired,
                "events": [event.as_dict() for event in selected],
                "has_more": has_more,
                "latest_cursor": latest_cursor,
                "next_cursor": next_cursor,
                "oldest_cursor": oldest_cursor,
                "stopped": self._stop_event.is_set(),
                "timed_out": timed_out,
            }

    def status(self) -> dict[str, Any]:
        with self._condition:
            return {
                "buffer_capacity": self.config.buffer_size,
                "buffered_events": len(self._events),
                "latest_cursor": self._events[-1].cursor if self._events else 0,
                "oldest_cursor": self._events[0].cursor if self._events else 0,
                "running": bool(self._thread and self._thread.is_alive()),
                "stopped": self._stop_event.is_set(),
            }

    def _validate_batch_input(
        self, after_cursor: int, limit: int, wait_seconds: float
    ) -> None:
        if (
            isinstance(after_cursor, bool)
            or not isinstance(after_cursor, int)
            or after_cursor < 0
        ):
            raise RelayInputError("after_cursor must be a non-negative integer")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= self.config.max_batch_size
        ):
            raise RelayInputError(
                f"limit must be between 1 and {self.config.max_batch_size}"
            )
        if isinstance(wait_seconds, bool) or not isinstance(wait_seconds, (int, float)):
            raise RelayInputError("wait_seconds must be a number")
        if not 0 <= wait_seconds <= self.config.max_wait_seconds:
            raise RelayInputError(
                f"wait_seconds must be between 0 and {self.config.max_wait_seconds}"
            )

    def _fetch_source(self, path: str) -> Any:
        try:
            with self._client.stream(
                "GET",
                f"{self.config.node_url}{path}",
                headers={"Accept": "application/json"},
                timeout=self.config.request_timeout,
            ) as response:
                if response.status_code >= 400:
                    code = (
                        "RATE_LIMITED"
                        if response.status_code == 429
                        else "UPSTREAM_REJECTED"
                    )
                    retryable = (
                        response.status_code == 429 or response.status_code >= 500
                    )
                    if response.status_code >= 500:
                        code = "NODE_UNAVAILABLE"
                    raise _PollFailure(
                        _error_data(
                            code, retryable=retryable, status_code=response.status_code
                        )
                    )
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self.config.max_response_bytes:
                        raise _PollFailure(
                            _error_data("RESPONSE_TOO_LARGE", retryable=False)
                        )
        except _PollFailure:
            raise

        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _PollFailure(
                _error_data("NON_JSON_RESPONSE", retryable=False)
            ) from exc

    def _record_success(self, source: str, data: Any) -> None:
        canonical_data = canonical_json(data)
        previous = self._source_states.get(source)
        if (
            previous
            and previous.available
            and previous.canonical_data == canonical_data
        ):
            return
        if previous is None:
            suffix = "snapshot"
        elif not previous.available:
            suffix = "recovered"
        else:
            suffix = "changed"
        self._source_states[source] = _SourceState(True, canonical_data)
        self._append_event(f"rustchain.{source}.{suffix}", source, data)

    def _record_failure(self, source: str, data: dict[str, Any]) -> None:
        canonical_data = canonical_json(data)
        previous = self._source_states.get(source)
        if (
            previous
            and not previous.available
            and previous.canonical_data == canonical_data
        ):
            return
        self._source_states[source] = _SourceState(False, canonical_data)
        self._append_event(f"rustchain.{source}.unavailable", source, data)

    def _append_event(self, event_type: str, source: str, data: Any) -> None:
        with self._condition:
            cursor = self._next_cursor
            self._next_cursor += 1
            observed_at = (
                datetime.fromtimestamp(self._wall_clock(), tz=timezone.utc)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )
            serialized = canonical_json(
                {
                    "cursor": cursor,
                    "data": data,
                    "observed_at": observed_at,
                    "source": source,
                    "type": event_type,
                }
            )
            self._events.append(RelayEvent(cursor, event_type, source, serialized))
            self._condition.notify_all()

    def _poll_loop(self) -> None:
        consecutive_failures = 0
        while not self._stop_event.is_set():
            succeeded = self.poll_once()
            consecutive_failures = 0 if succeeded else consecutive_failures + 1
            delay = self.backoff_delay(consecutive_failures)
            if self._stop_event.wait(delay):
                break


class EventRelayHTTPServer(ThreadingHTTPServer):
    """Threaded SSE server with an explicit connection ceiling."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], relay: EventRelay, config: SSEConfig):
        self.relay = relay
        self.sse_config = config.validated()
        self.client_slots = threading.BoundedSemaphore(self.sse_config.max_clients)
        super().__init__(address, EventRelayRequestHandler)

    def get_request(self) -> tuple[Any, Any]:
        request, client_address = super().get_request()
        request.settimeout(self.sse_config.write_timeout)
        return request, client_address


class EventRelayRequestHandler(BaseHTTPRequestHandler):
    """Serve health JSON and cursor-resumable server-sent events."""

    protocol_version = "HTTP/1.1"
    server: EventRelayHTTPServer

    def log_message(self, format_string: str, *args: Any) -> None:
        LOGGER.info("SSE client %s: " + format_string, self.client_address[0], *args)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlsplit(self.path)
        if parsed.path not in ("/events", "/healthz"):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found", "ok": False})
            return
        if not self._authorized():
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("Content-Length", "0")
            self.send_header("WWW-Authenticate", "Bearer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            return
        if parsed.path == "/healthz":
            self._send_json(
                HTTPStatus.OK, {"ok": True, "relay": self.server.relay.status()}
            )
            return
        self._serve_events(parsed.query)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED, {"error": "read_only", "ok": False}
        )

    def _authorized(self) -> bool:
        expected = self.server.sse_config.bearer_token
        if not expected:
            return True
        supplied = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not supplied.startswith(prefix):
            return False
        return hmac.compare_digest(supplied[len(prefix) :], expected)

    def _serve_events(self, query: str) -> None:
        if not self.server.client_slots.acquire(blocking=False):
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "too_many_sse_clients", "ok": False},
            )
            return
        try:
            after_cursor, limit = self._parse_event_query(query)
            initial = self.server.relay.get_batch(after_cursor, limit, 0)
        except RelayInputError as exc:
            self.server.client_slots.release()
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_request", "message": str(exc), "ok": False},
            )
            return

        try:
            self.connection.settimeout(self.server.sse_config.write_timeout)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()

            batch = initial
            cursor = after_cursor
            if batch["cursor_expired"]:
                self._write_sse(
                    "rustchain.cursor.expired",
                    canonical_json(
                        {
                            "oldest_cursor": batch["oldest_cursor"],
                            "requested_cursor": after_cursor,
                        }
                    ),
                )
            while not self.server.relay.stopped:
                for event in batch["events"]:
                    self._write_sse(
                        event["type"], canonical_json(event), event["cursor"]
                    )
                    cursor = event["cursor"]
                if batch["has_more"]:
                    batch = self.server.relay.get_batch(cursor, limit, 0)
                    continue
                batch = self.server.relay.get_batch(
                    cursor,
                    limit,
                    self.server.sse_config.heartbeat_seconds,
                )
                if not batch["events"] and not batch["stopped"]:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            return
        finally:
            self.server.client_slots.release()

    def _parse_event_query(self, query: str) -> tuple[int, int]:
        try:
            params = parse_qs(query, keep_blank_values=True, max_num_fields=4)
        except ValueError as exc:
            raise RelayInputError("too many query parameters") from exc
        if any(len(values) != 1 for values in params.values()):
            raise RelayInputError("query parameters must not be repeated")
        unknown = set(params) - {"cursor", "limit"}
        if unknown:
            raise RelayInputError(
                "only cursor and limit query parameters are supported"
            )

        cursor_value = params.get("cursor", [self.headers.get("Last-Event-ID", "0")])[0]
        limit_value = params.get(
            "limit", [str(self.server.relay.config.max_batch_size)]
        )[0]
        try:
            return int(cursor_value), int(limit_value)
        except ValueError as exc:
            raise RelayInputError("cursor and limit must be integers") from exc

    def _write_sse(self, event_type: str, data: str, cursor: int | None = None) -> None:
        lines = []
        if cursor is not None:
            lines.append(f"id: {cursor}")
        lines.extend((f"event: {event_type}", f"data: {data}", "", ""))
        self.wfile.write("\n".join(lines).encode("utf-8"))
        self.wfile.flush()

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = canonical_json(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def build_parser() -> argparse.ArgumentParser:
    defaults = EventRelayConfig.from_env()
    sse_defaults = SSEConfig.from_env()
    parser = argparse.ArgumentParser(
        prog="rustchain-event-relay",
        description="Poll read-only RustChain state and expose cursor-resumable SSE.",
    )
    parser.add_argument("--node-url", default=defaults.node_url)
    parser.add_argument("--host", default=sse_defaults.host)
    parser.add_argument("--port", type=int, default=sse_defaults.port)
    parser.add_argument("--poll-interval", type=float, default=defaults.poll_interval)
    parser.add_argument(
        "--request-timeout", type=float, default=defaults.request_timeout
    )
    parser.add_argument("--buffer-size", type=int, default=defaults.buffer_size)
    parser.add_argument("--max-clients", type=int, default=sse_defaults.max_clients)
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        default=sse_defaults.allow_remote,
        help="allow a non-loopback bind (also requires RUSTCHAIN_EVENT_TOKEN)",
    )
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the standalone SSE relay until SIGINT or SIGTERM."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level), format="%(levelname)s %(message)s"
    )

    relay_config = replace(
        EventRelayConfig.from_env(),
        node_url=args.node_url,
        poll_interval=args.poll_interval,
        request_timeout=args.request_timeout,
        buffer_size=args.buffer_size,
    ).validated()
    sse_config = replace(
        SSEConfig.from_env(),
        host=args.host,
        port=args.port,
        max_clients=args.max_clients,
        allow_remote=args.allow_remote,
    ).validated()

    relay = EventRelay(relay_config)
    server = EventRelayHTTPServer((sse_config.host, sse_config.port), relay, sse_config)
    stopping = threading.Event()

    def request_stop(signum: int, frame: Any) -> None:
        del signum, frame
        stopping.set()

    previous_handlers: dict[int, Any] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[signum] = signal.signal(signum, request_stop)

    relay.start()
    server.timeout = 0.5
    host, port = server.server_address[:2]
    LOGGER.info("RustChain event relay listening on http://%s:%s/events", host, port)
    try:
        while not stopping.is_set():
            server.handle_request()
    finally:
        server.server_close()
        relay.stop()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
