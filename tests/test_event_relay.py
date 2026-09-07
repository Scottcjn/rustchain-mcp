"""Offline tests for the read-only RustChain event relay."""

from __future__ import annotations

import json
import socket
import threading
import time

import httpx
import pytest

from rustchain_mcp import server as mcp_server
from rustchain_mcp import events as event_module
from rustchain_mcp.events import (
    EventRelay,
    EventRelayConfig,
    EventRelayHTTPServer,
    RelayInputError,
    SSEConfig,
    canonical_json,
)


class FakeNode:
    """Mutable MockTransport handler for fixed RustChain read endpoints."""

    def __init__(self):
        self.payloads = {
            "/health": {"version": "1.0", "ok": True},
            "/epoch": {"slot": 10, "epoch": 7},
            "/api/miners": {
                "total": 47,
                "miners": [
                    {"miner_id": "zeta", "multiplier": 1.0},
                    {"multiplier": 2.5, "miner_id": "alpha"},
                ],
            },
        }
        self.failures: dict[str, str] = {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.method == "GET"
        failure = self.failures.get(request.url.path)
        if failure == "timeout":
            raise httpx.ReadTimeout("fake timeout", request=request)
        if failure == "503":
            return httpx.Response(503, json={"error": "offline"})
        return httpx.Response(200, json=self.payloads[request.url.path])


def make_relay(fake_node: FakeNode, **overrides) -> tuple[EventRelay, httpx.Client]:
    generation = overrides.pop("generation", "testgen")
    values = {
        "node_url": "https://fake-node.invalid",
        "poll_interval": 0.05,
        "request_timeout": 0.2,
        "backoff_initial": 0.05,
        "backoff_max": 0.2,
        "buffer_size": 16,
        "max_batch_size": 8,
        "max_wait_seconds": 1.0,
        "max_response_bytes": 4096,
    }
    values.update(overrides)
    client = httpx.Client(transport=httpx.MockTransport(fake_node))
    relay = EventRelay(
        EventRelayConfig(**values),
        client=client,
        wall_clock=lambda: 1_700_000_000.0,
        generation=generation,
    )
    return relay, client


def test_poll_normalizes_changes_and_uses_only_fixed_get_paths():
    fake = FakeNode()
    relay, client = make_relay(fake)
    try:
        assert relay.poll_once() is True
        first = relay.get_batch(limit=8)

        assert [event["cursor"] for event in first["events"]] == [
            "testgen:1",
            "testgen:2",
            "testgen:3",
        ]
        assert [event["type"] for event in first["events"]] == [
            "rustchain.health.snapshot",
            "rustchain.epoch.snapshot",
            "rustchain.miners.snapshot",
        ]
        assert [
            miner["miner_id"] for miner in first["events"][2]["data"]["miners"]
        ] == [
            "alpha",
            "zeta",
        ]
        assert first["events"][0]["observed_at"] == "2023-11-14T22:13:20.000Z"
        miners_data = first["events"][2]["data"]
        assert miners_data["page_count"] == 2
        assert miners_data["page_limit"] == 100
        assert miners_data["total_miners"] == 47
        assert miners_data["total_known"] is True
        miners_requests = [
            request for request in fake.requests if request.url.path == "/api/miners"
        ]
        assert dict(miners_requests[0].url.params) == {"limit": "100", "offset": "0"}

        # Reordering a semantically unordered miner list is not a change.
        fake.payloads["/api/miners"]["miners"].reverse()
        assert relay.poll_once() is True
        assert relay.get_batch(after_cursor="testgen:3", limit=8)["events"] == []

        fake.payloads["/epoch"]["slot"] = 11
        assert relay.poll_once() is True
        changed = relay.get_batch(after_cursor="testgen:3", limit=8)
        assert [event["type"] for event in changed["events"]] == [
            "rustchain.epoch.changed"
        ]
        assert {request.url.path for request in fake.requests} == {
            "/health",
            "/epoch",
            "/api/miners",
        }
    finally:
        relay.stop()
        client.close()


def test_health_volatility_does_not_emit_but_meaningful_change_does():
    fake = FakeNode()
    fake.payloads["/health"].update(
        {"backup_age_hours": 1.0, "db_rw": True, "uptime_s": 100}
    )
    relay, client = make_relay(fake)
    try:
        relay.poll_once()
        fake.payloads["/health"]["uptime_s"] = 105
        fake.payloads["/health"]["backup_age_hours"] = 1.1
        relay.poll_once()
        assert relay.get_batch(after_cursor="testgen:3", limit=8)["events"] == []

        fake.payloads["/health"]["db_rw"] = False
        relay.poll_once()
        events = relay.get_batch(after_cursor="testgen:3", limit=8)["events"]
        assert [event["type"] for event in events] == ["rustchain.health.changed"]
        assert "uptime_s" not in events[0]["data"]
        assert "backup_age_hours" not in events[0]["data"]
        assert events[0]["data"]["db_rw"] is False
    finally:
        relay.stop()
        client.close()


def test_miners_without_node_total_do_not_report_page_length_as_global_total():
    fake = FakeNode()
    del fake.payloads["/api/miners"]["total"]
    relay, client = make_relay(fake, miners_limit=2)
    try:
        relay.poll_once()
        miners = relay.get_batch(limit=8)["events"][2]["data"]
        assert miners["page_count"] == 2
        assert miners["page_limit"] == 2
        assert miners["total_known"] is False
        assert "total_miners" not in miners
        request = next(
            request for request in fake.requests if request.url.path == "/api/miners"
        )
        assert dict(request.url.params) == {"limit": "2", "offset": "0"}
    finally:
        relay.stop()
        client.close()


def test_cursor_generation_change_resets_and_replays_retained_snapshots():
    fake_a = FakeNode()
    relay_a, client_a = make_relay(fake_a, generation="boot-a")
    fake_b = FakeNode()
    relay_b, client_b = make_relay(fake_b, generation="boot-b")
    try:
        relay_a.poll_once()
        persisted_cursor = relay_a.get_batch(limit=8)["next_cursor"]
        assert persisted_cursor == "boot-a:3"

        relay_b.poll_once()
        restarted = relay_b.get_batch(after_cursor=persisted_cursor, limit=8)
        assert restarted["cursor_reset"] is True
        assert restarted["reset_reason"] == "generation_changed"
        assert restarted["cursor_expired"] is False
        assert [event["cursor"] for event in restarted["events"]] == [
            "boot-b:1",
            "boot-b:2",
            "boot-b:3",
        ]

        legacy = relay_b.get_batch(after_cursor="3", limit=8)
        assert legacy["cursor_reset"] is True
        assert legacy["reset_reason"] == "legacy_cursor"
        assert legacy["events"][0]["cursor"] == "boot-b:1"
    finally:
        relay_a.stop()
        relay_b.stop()
        client_a.close()
        client_b.close()


def test_bounded_buffer_reports_cursor_expiry_and_paginates():
    fake = FakeNode()
    relay, client = make_relay(fake, buffer_size=3, max_batch_size=2)
    try:
        relay.poll_once()
        fake.payloads["/health"]["version"] = "1.1"
        fake.payloads["/epoch"]["epoch"] = 8
        fake.payloads["/api/miners"]["miners"].append({"miner_id": "beta"})
        relay.poll_once()

        batch = relay.get_batch(after_cursor="testgen:0", limit=2)
        assert batch["cursor_expired"] is True
        assert batch["cursor_reset"] is False
        assert batch["oldest_cursor"] == "testgen:4"
        assert [event["cursor"] for event in batch["events"]] == [
            "testgen:4",
            "testgen:5",
        ]
        assert batch["next_cursor"] == "testgen:5"
        assert batch["has_more"] is True

        restarted = relay.get_batch(after_cursor="older-generation:99", limit=2)
        assert restarted["cursor_reset"] is True
        assert restarted["cursor_expired"] is True
        assert restarted["reset_reason"] == "generation_changed"
        assert restarted["events"][0]["cursor"] == "testgen:4"

        final = relay.get_batch(after_cursor="testgen:5", limit=2)
        assert [event["cursor"] for event in final["events"]] == ["testgen:6"]
        assert final["has_more"] is False
        with pytest.raises(RelayInputError, match="ahead of latest"):
            relay.get_batch(after_cursor="testgen:99", limit=1)
    finally:
        relay.stop()
        client.close()


def test_long_poll_wakes_for_a_new_event():
    fake = FakeNode()
    relay, client = make_relay(fake)
    relay.poll_once()
    result: dict = {}

    def wait_for_event() -> None:
        result.update(
            relay.get_batch(after_cursor="testgen:3", limit=2, wait_seconds=0.8)
        )

    waiter = threading.Thread(target=wait_for_event)
    waiter.start()
    time.sleep(0.05)
    fake.payloads["/epoch"]["slot"] = 12
    relay.poll_once()
    waiter.join(1)
    try:
        assert not waiter.is_alive()
        assert result["timed_out"] is False
        assert [event["cursor"] for event in result["events"]] == ["testgen:4"]
    finally:
        relay.stop()
        client.close()


def test_failure_is_deduplicated_and_recovery_is_emitted():
    fake = FakeNode()
    fake.failures["/health"] = "timeout"
    relay, client = make_relay(fake)
    try:
        assert relay.poll_once() is False
        first = relay.get_batch(limit=8)
        unavailable = first["events"][0]
        assert unavailable["type"] == "rustchain.health.unavailable"
        assert unavailable["data"]["error"]["code"] == "UPSTREAM_TIMEOUT"

        assert relay.poll_once() is False
        assert relay.get_batch(after_cursor="testgen:3", limit=8)["events"] == []

        del fake.failures["/health"]
        assert relay.poll_once() is True
        recovered = relay.get_batch(after_cursor="testgen:3", limit=8)["events"]
        assert [event["type"] for event in recovered] == ["rustchain.health.recovered"]
        assert relay.backoff_delay(1) == 0.05
        assert relay.backoff_delay(2) == 0.1
        assert relay.backoff_delay(99) == 0.2
    finally:
        relay.stop()
        client.close()


def test_oversized_fake_node_response_becomes_bounded_error_event():
    fake = FakeNode()
    fake.payloads["/health"] = {"padding": "x" * 5000}
    relay, client = make_relay(fake, max_response_bytes=1024)
    try:
        assert relay.poll_once() is False
        event = relay.get_batch(limit=8)["events"][0]
        assert event["type"] == "rustchain.health.unavailable"
        assert event["data"]["error"]["code"] == "RESPONSE_TOO_LARGE"
    finally:
        relay.stop()
        client.close()


def test_background_poller_and_long_poll_shutdown_gracefully():
    fake = FakeNode()
    relay, client = make_relay(fake)
    relay.start()
    deadline = time.monotonic() + 1
    while (
        relay.status()["latest_cursor"] == "testgen:0" and time.monotonic() < deadline
    ):
        time.sleep(0.01)
    latest = relay.status()["latest_cursor"]
    assert latest == "testgen:3"
    assert relay.stop(timeout=1) is True
    stopped_batch = relay.get_batch(after_cursor=latest, limit=1, wait_seconds=0.5)
    assert stopped_batch["stopped"] is True
    assert stopped_batch["events"] == []
    client.close()


def test_stop_reports_stuck_worker_and_closes_owned_client(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    class BlockingStream:
        def __enter__(self):
            entered.set()
            release.wait(2)
            raise httpx.ReadTimeout(
                "cancelled", request=httpx.Request("GET", "https://fake")
            )

        def __exit__(self, exc_type, exc, traceback):
            return False

    class StubbornClient:
        def __init__(self):
            self.closed = False
            self.stream_calls = 0

        def stream(self, *args, **kwargs):
            self.stream_calls += 1
            return BlockingStream()

        def close(self):
            self.closed = True

    owned_client = StubbornClient()
    monkeypatch.setattr(event_module.httpx, "Client", lambda **kwargs: owned_client)
    relay = EventRelay(
        EventRelayConfig(
            node_url="https://fake-node.invalid",
            poll_interval=0.05,
            request_timeout=0.05,
            backoff_initial=0.05,
            backoff_max=0.1,
        ),
        generation="shutdown-test",
    )
    relay.start()
    assert entered.wait(1)

    assert relay.stop(timeout=0.01) is False
    assert owned_client.closed is True
    assert owned_client.stream_calls == 1

    release.set()
    assert relay.stop(timeout=1) is True


def test_mcp_tool_is_explicit_bounded_batch_not_native_stream(monkeypatch):
    fake = FakeNode()
    relay, client = make_relay(fake)
    relay.poll_once()
    monkeypatch.setattr(mcp_server, "get_event_relay", lambda: relay)
    try:
        result = mcp_server.rustchain_events(after_cursor="testgen:0", limit=2)
        assert result["ok"] is True
        assert result["delivery"] == "bounded_batch_or_long_poll"
        assert result["native_mcp_streaming"] is False
        assert result["next_cursor"] == "testgen:2"
        assert result["has_more"] is True
    finally:
        relay.stop()
        client.close()


def test_mcp_default_limit_clamps_to_configured_maximum(monkeypatch):
    fake = FakeNode()
    relay, client = make_relay(fake, max_batch_size=2)
    relay.poll_once()
    monkeypatch.setattr(mcp_server, "get_event_relay", lambda: relay)
    try:
        result = mcp_server.rustchain_events(after_cursor="testgen:0")
        assert result["ok"] is True
        assert result["limit"] == 2
        assert result["limit_clamped"] is True
        assert len(result["events"]) == 2
        assert result["has_more"] is True
    finally:
        relay.stop()
        client.close()


def test_sse_endpoint_uses_deterministic_json_and_bearer_auth():
    fake = FakeNode()
    relay, client = make_relay(fake)
    relay.poll_once()
    token = "0123456789abcdef"
    config = SSEConfig(
        host="127.0.0.1",
        port=0,
        max_clients=2,
        heartbeat_seconds=0.1,
        write_timeout=0.5,
        bearer_token=token,
    )
    http_server = EventRelayHTTPServer((config.host, config.port), relay, config)
    server_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    server_thread.start()
    base_url = f"http://127.0.0.1:{http_server.server_address[1]}"

    try:
        unauthorized = httpx.get(f"{base_url}/healthz", timeout=1)
        assert unauthorized.status_code == 401

        headers = {"Authorization": f"Bearer {token}"}
        rejected_write = httpx.post(f"{base_url}/events", headers=headers, timeout=1)
        assert rejected_write.status_code == 405
        malformed = httpx.get(
            f"{base_url}/events?a=1&b=2&c=3&d=4&e=5",
            headers=headers,
            timeout=1,
        )
        assert malformed.status_code == 400
        with httpx.stream(
            "GET", f"{base_url}/events?cursor=0&limit=1", headers=headers, timeout=1
        ) as response:
            assert response.status_code == 200
            lines = response.iter_lines()
            assert next(lines) == "id: testgen:1"
            assert next(lines) == "event: rustchain.health.snapshot"
            data_line = next(lines)
            payload = data_line.removeprefix("data: ")
            assert payload == canonical_json(json.loads(payload))
            assert json.loads(payload)["cursor"] == "testgen:1"
    finally:
        relay.stop()
        http_server.shutdown()
        http_server.server_close()
        server_thread.join(1)
        client.close()


def test_sse_last_event_id_from_old_generation_emits_reset_before_snapshots():
    fake = FakeNode()
    relay, client = make_relay(fake, generation="boot-new")
    relay.poll_once()
    config = SSEConfig(
        host="127.0.0.1",
        port=0,
        max_clients=2,
        heartbeat_seconds=0.1,
        write_timeout=0.5,
    )
    http_server = EventRelayHTTPServer((config.host, config.port), relay, config)
    server_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    server_thread.start()
    url = f"http://127.0.0.1:{http_server.server_address[1]}/events"

    try:
        with httpx.stream(
            "GET",
            url,
            headers={"Last-Event-ID": "boot-old:2"},
            timeout=1,
        ) as response:
            assert response.status_code == 200
            lines = response.iter_lines()
            assert next(lines) == "event: rustchain.cursor.reset"
            reset = json.loads(next(lines).removeprefix("data: "))
            assert reset["reason"] == "generation_changed"
            assert reset["generation"] == "boot-new"
            assert next(lines) == ""
            assert next(lines) == "id: boot-new:1"
            assert next(lines) == "event: rustchain.health.snapshot"
    finally:
        relay.stop()
        http_server.shutdown()
        http_server.server_close()
        server_thread.join(1)
        client.close()


def test_connection_limit_applies_before_slow_request_creates_more_workers():
    fake = FakeNode()
    relay, client = make_relay(fake)
    config = SSEConfig(
        host="127.0.0.1",
        port=0,
        max_clients=1,
        heartbeat_seconds=0.1,
        write_timeout=0.5,
    )
    http_server = EventRelayHTTPServer((config.host, config.port), relay, config)
    server_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    server_thread.start()
    address = ("127.0.0.1", http_server.server_address[1])
    slow_socket = socket.create_connection(address, timeout=1)
    slow_socket.sendall(b"GET /healthz HTTP/1.1\r\nHost: localhost\r\n")

    def connection_slot_is_taken() -> bool:
        acquired = http_server.connection_slots.acquire(blocking=False)
        if acquired:
            http_server.connection_slots.release()
            return False
        return True

    deadline = time.monotonic() + 1
    while not connection_slot_is_taken() and time.monotonic() < deadline:
        time.sleep(0.01)

    try:
        assert connection_slot_is_taken()
        rejected = httpx.get(f"http://{address[0]}:{address[1]}/healthz", timeout=1)
        assert rejected.status_code == 503
        assert rejected.json()["error"] == "too_many_connections"
    finally:
        slow_socket.close()
        relay.stop()
        http_server.shutdown()
        http_server.server_close()
        server_thread.join(1)
        client.close()


def test_remote_listener_requires_opt_in_and_token():
    with pytest.raises(RelayInputError, match="allow-remote"):
        SSEConfig(host="0.0.0.0").validated()
    with pytest.raises(RelayInputError, match="TOKEN"):
        SSEConfig(host="0.0.0.0", allow_remote=True).validated()
