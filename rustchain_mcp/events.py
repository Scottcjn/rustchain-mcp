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
import uuid
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
_VOLATILE_HEALTH_FIELDS = frozenset(("backup_age_hours", "uptime_s"))


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
    miners_limit: int = 100

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
            miners_limit=_env_int("RUSTCHAIN_EVENT_MINERS_LIMIT", cls.miners_limit),
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
        if not 1 <= self.miners_limit <= 1000:
            raise RelayInputError("miners_limit must be between 1 and 1000")
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


def pagination_total(payload: Mapping[str, Any]) -> int | None:
    candidates = (
        payload.get("total_miners"),
        payload.get("total"),
        payload.get("total_count"),
    )
    pagination = payload.get("pagination")
    if isinstance(pagination, Mapping):
        candidates += (
            pagination.get("total_miners"),
            pagination.get("total"),
            pagination.get("total_count"),
        )
    for candidate in candidates:
        if (
            isinstance(candidate, int)
            and not isinstance(candidate, bool)
            and candidate >= 0
        ):
            return candidate
    return None


def _normalize_source(
    source: str,
    payload: Any,
    *,
    miners_limit: int | None = None,
) -> Any:
    if source in ("health", "epoch"):
        if not isinstance(payload, Mapping):
            raise _PollFailure(_error_data("MISSING_EXPECTED_OBJECT", retryable=False))
        normalized_source = _normalize_json(payload)
        if source == "health":
            for field in _VOLATILE_HEALTH_FIELDS:
                normalized_source.pop(field, None)
        return normalized_source

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
    total_miners = pagination_total(payload) if isinstance(payload, Mapping) else None
    normalized["page_count"] = len(normalized_miners)
    normalized["page_limit"] = miners_limit
    normalized["page_offset"] = 0
    normalized["total_known"] = total_miners is not None
    if total_miners is not None:
        normalized["total_miners"] = total_miners
    else:
        normalized.pop("total_miners", None)
    return _normalize_json(normalized)


@dataclass(frozen=True)
class RelayEvent:
    sequence: int
    cursor: str
    event_type: str
    source: str
    serialized: str

    def as_dict(self) -> dict[str, Any]:
        return json.loads(self.serialized)


@dataclass(frozen=True)
class _SourceState:
    available: bool
    canonical_data: str


@dataclass(frozen=True)
class _CursorPosition:
    sequence: int
    reset: bool = False
    reset_reason: str | None = None


class EventRelay:
    """Poll fixed read-only node paths and retain normalized state changes."""

    def __init__(
        self,
        config: EventRelayConfig,
        *,
        client: httpx.Client | None = None,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
        generation: str | None = None,
    ):
        self.config = config.validated()
        self.generation = self._validate_generation(generation or uuid.uuid4().hex)
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
        self._client_close_lock = threading.Lock()

    @staticmethod
    def _validate_generation(generation: str) -> str:
        if not generation or len(generation) > 64:
            raise RelayInputError("generation must contain between 1 and 64 characters")
        if not all(
            character.isalnum() or character in ("-", "_") for character in generation
        ):
            raise RelayInputError(
                "generation may contain only letters, numbers, '-' and '_'"
            )
        return generation

    def _format_cursor(self, sequence: int) -> str:
        return f"{self.generation}:{sequence}"

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
        client_closed = self._close_owned_client()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            shutdown_timeout = (
                timeout
                if timeout is not None
                else len(_SOURCE_PATHS) * self.config.request_timeout + 1
            )
            thread.join(shutdown_timeout)
        stopped = not thread or not thread.is_alive()
        return stopped and client_closed

    def _close_owned_client(self) -> bool:
        if not self._owns_client:
            return True
        with self._client_close_lock:
            if self._client_closed:
                return True
            try:
                self._client.close()
            except Exception:
                LOGGER.exception("Failed to close RustChain event relay HTTP client")
                return False
            self._client_closed = True
            return True

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    def poll_once(self) -> bool:
        """Poll all fixed endpoints once; return true only if all succeeded."""
        all_succeeded = True
        for source, path in _SOURCE_PATHS:
            if self._stop_event.is_set():
                return False
            params = (
                {"limit": self.config.miners_limit, "offset": 0}
                if source == "miners"
                else None
            )
            try:
                payload = self._fetch_source(path, params=params)
                normalized = _normalize_source(
                    source,
                    payload,
                    miners_limit=self.config.miners_limit,
                )
                if self._stop_event.is_set():
                    return False
                self._record_success(source, normalized)
            except _PollFailure as exc:
                if self._stop_event.is_set():
                    return False
                all_succeeded = False
                self._record_failure(source, exc.data)
            except (httpx.TimeoutException, TimeoutError):
                if self._stop_event.is_set():
                    return False
                all_succeeded = False
                self._record_failure(
                    source, _error_data("UPSTREAM_TIMEOUT", retryable=True)
                )
            except httpx.RequestError:
                if self._stop_event.is_set():
                    return False
                all_succeeded = False
                self._record_failure(
                    source, _error_data("TRANSPORT_RETRYABLE", retryable=True)
                )
            except Exception:
                if self._stop_event.is_set():
                    return False
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
        after_cursor: str | int = "0",
        limit: int = 50,
        wait_seconds: float = 0.0,
    ) -> dict[str, Any]:
        """Return a bounded batch, waiting cooperatively for a newer event."""
        self._validate_batch_input(after_cursor, limit, wait_seconds)
        deadline = self._monotonic_clock() + wait_seconds

        with self._condition:
            while True:
                oldest_sequence = self._events[0].sequence if self._events else 0
                latest_sequence = self._events[-1].sequence if self._events else 0
                position = self._parse_cursor(after_cursor)
                if not position.reset and position.sequence > latest_sequence:
                    raise RelayInputError(
                        f"after_cursor {after_cursor!r} is ahead of latest cursor "
                        f"{self._format_cursor(latest_sequence)!r}"
                    )

                cursor_expired = bool(
                    self._events
                    and (
                        (position.reset and oldest_sequence > 1)
                        or (
                            not position.reset
                            and position.sequence < oldest_sequence - 1
                        )
                    )
                )
                effective_sequence = (
                    oldest_sequence - 1
                    if cursor_expired or position.reset
                    else position.sequence
                )
                available = [
                    event
                    for event in self._events
                    if event.sequence > effective_sequence
                ]
                if available or wait_seconds == 0 or self._stop_event.is_set():
                    break
                remaining = deadline - self._monotonic_clock()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)

            selected = available[:limit]
            next_sequence = (
                selected[-1].sequence
                if selected
                else (0 if position.reset else position.sequence)
            )
            next_cursor = self._format_cursor(next_sequence)
            has_more = any(event.sequence > next_sequence for event in self._events)
            timed_out = bool(
                wait_seconds > 0
                and not selected
                and not self._stop_event.is_set()
                and self._monotonic_clock() >= deadline
            )
            return {
                "cursor_expired": cursor_expired,
                "cursor_reset": position.reset,
                "events": [event.as_dict() for event in selected],
                "generation": self.generation,
                "has_more": has_more,
                "latest_cursor": self._format_cursor(latest_sequence),
                "next_cursor": next_cursor,
                "oldest_cursor": self._format_cursor(oldest_sequence),
                "reset_reason": position.reset_reason,
                "stopped": self._stop_event.is_set(),
                "timed_out": timed_out,
            }

    def status(self) -> dict[str, Any]:
        with self._condition:
            return {
                "buffer_capacity": self.config.buffer_size,
                "buffered_events": len(self._events),
                "generation": self.generation,
                "latest_cursor": self._format_cursor(
                    self._events[-1].sequence if self._events else 0
                ),
                "oldest_cursor": self._format_cursor(
                    self._events[0].sequence if self._events else 0
                ),
                "running": bool(self._thread and self._thread.is_alive()),
                "stopped": self._stop_event.is_set(),
            }

    def _validate_batch_input(
        self, after_cursor: str | int, limit: int, wait_seconds: float
    ) -> None:
        self._parse_cursor(after_cursor)
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

    def _parse_cursor(self, cursor: str | int) -> _CursorPosition:
        if isinstance(cursor, bool):
            raise RelayInputError("after_cursor must be a generation-qualified cursor")
        if isinstance(cursor, int):
            if cursor < 0:
                raise RelayInputError("after_cursor sequence must be non-negative")
            if cursor == 0:
                return _CursorPosition(0)
            return _CursorPosition(0, reset=True, reset_reason="legacy_cursor")
        if not isinstance(cursor, str):
            raise RelayInputError("after_cursor must be a string cursor")

        cursor = cursor.strip()
        if cursor in ("", "0"):
            return _CursorPosition(0)
        if ":" not in cursor:
            if cursor.isdigit():
                return _CursorPosition(0, reset=True, reset_reason="legacy_cursor")
            raise RelayInputError("after_cursor must use '<generation>:<sequence>'")

        generation, sequence_text = cursor.rsplit(":", 1)
        try:
            sequence = int(sequence_text)
        except ValueError as exc:
            raise RelayInputError("after_cursor sequence must be an integer") from exc
        if sequence < 0:
            raise RelayInputError("after_cursor sequence must be non-negative")
        if generation != self.generation:
            return _CursorPosition(0, reset=True, reset_reason="generation_changed")
        return _CursorPosition(sequence)

    def _fetch_source(
        self,
        path: str,
        *,
        params: dict[str, int] | None = None,
    ) -> Any:
        try:
            with self._client.stream(
                "GET",
                f"{self.config.node_url}{path}",
                headers={"Accept": "application/json"},
                params=params,
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
            sequence = self._next_cursor
            self._next_cursor += 1
            cursor = self._format_cursor(sequence)
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
            self._events.append(
                RelayEvent(sequence, cursor, event_type, source, serialized)
            )
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
        self.connection_slots = threading.BoundedSemaphore(self.sse_config.max_clients)
        super().__init__(address, EventRelayRequestHandler)

    def get_request(self) -> tuple[Any, Any]:
        request, client_address = super().get_request()
        request.settimeout(self.sse_config.write_timeout)
        return request, client_address

    def process_request(self, request: Any, client_address: Any) -> None:
        """Admit a connection before ThreadingMixIn creates its worker."""
        if not self.connection_slots.acquire(blocking=False):
            request.settimeout(min(self.sse_config.write_timeout, 0.25))
            body = canonical_json(
                {"error": "too_many_connections", "ok": False}
            ).encode("utf-8")
            response = (
                b"HTTP/1.1 503 Service Unavailable\r\n"
                b"Content-Type: application/json; charset=utf-8\r\n"
                b"Cache-Control: no-store\r\n"
                b"Connection: close\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
                + body
            )
            try:
                request.sendall(response)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.connection_slots.release()
            self.shutdown_request(request)
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connection_slots.release()


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
        try:
            after_cursor, limit = self._parse_event_query(query)
            initial = self.server.relay.get_batch(after_cursor, limit, 0)
        except RelayInputError as exc:
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
            cursor = batch["next_cursor"]
            if batch["cursor_reset"]:
                self._write_sse(
                    "rustchain.cursor.reset",
                    canonical_json(
                        {
                            "generation": batch["generation"],
                            "next_cursor": batch["next_cursor"],
                            "reason": batch["reset_reason"],
                            "requested_cursor": after_cursor,
                        }
                    ),
                )
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

    def _parse_event_query(self, query: str) -> tuple[str, int]:
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
            limit = int(limit_value)
        except ValueError as exc:
            raise RelayInputError("limit must be an integer") from exc
        return cursor_value, limit

    def _write_sse(self, event_type: str, data: str, cursor: str | None = None) -> None:
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
    try:
        server = EventRelayHTTPServer(
            (sse_config.host, sse_config.port), relay, sse_config
        )
    except Exception:
        if not relay.stop():
            LOGGER.error(
                "RustChain event relay client did not close after bind failure"
            )
        raise
    stopping = threading.Event()
    exit_code = 0

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
        if not relay.stop():
            LOGGER.error("RustChain event poller did not stop before timeout")
            exit_code = 1
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
