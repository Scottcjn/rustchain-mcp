"""Offline tests for the read-only RustChain event relay."""

from __future__ import annotations

import json
import threading
import time

import httpx
import pytest

from rustchain_mcp import server as mcp_server
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
                "miners": [
                    {"miner_id": "zeta", "multiplier": 1.0},
                    {"multiplier": 2.5, "miner_id": "alpha"},
                ]
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
    )
    return relay, client


def test_poll_normalizes_changes_and_uses_only_fixed_get_paths():
    fake = FakeNode()
    relay, client = make_relay(fake)
    try:
        assert relay.poll_once() is True
        first = relay.get_batch(limit=8)

        assert [event["cursor"] for event in first["events"]] == [1, 2, 3]
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

        # Reordering a semantically unordered miner list is not a change.
        fake.payloads["/api/miners"]["miners"].reverse()
        assert relay.poll_once() is True
        assert relay.get_batch(after_cursor=3, limit=8)["events"] == []

        fake.payloads["/epoch"]["slot"] = 11
        assert relay.poll_once() is True
        changed = relay.get_batch(after_cursor=3, limit=8)
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


def test_bounded_buffer_reports_cursor_expiry_and_paginates():
    fake = FakeNode()
    relay, client = make_relay(fake, buffer_size=3, max_batch_size=2)
    try:
        relay.poll_once()
        fake.payloads["/health"]["version"] = "1.1"
        fake.payloads["/epoch"]["epoch"] = 8
        fake.payloads["/api/miners"]["miners"].append({"miner_id": "beta"})
        relay.poll_once()

        batch = relay.get_batch(after_cursor=0, limit=2)
        assert batch["cursor_expired"] is True
        assert batch["oldest_cursor"] == 4
        assert [event["cursor"] for event in batch["events"]] == [4, 5]
        assert batch["next_cursor"] == 5
        assert batch["has_more"] is True

        final = relay.get_batch(after_cursor=5, limit=2)
        assert [event["cursor"] for event in final["events"]] == [6]
        assert final["has_more"] is False
        with pytest.raises(RelayInputError, match="ahead of latest"):
            relay.get_batch(after_cursor=99, limit=1)
    finally:
        relay.stop()
        client.close()


def test_long_poll_wakes_for_a_new_event():
    fake = FakeNode()
    relay, client = make_relay(fake)
    relay.poll_once()
    result: dict = {}

    def wait_for_event() -> None:
        result.update(relay.get_batch(after_cursor=3, limit=2, wait_seconds=0.8))

    waiter = threading.Thread(target=wait_for_event)
    waiter.start()
    time.sleep(0.05)
    fake.payloads["/epoch"]["slot"] = 12
    relay.poll_once()
    waiter.join(1)
    try:
        assert not waiter.is_alive()
        assert result["timed_out"] is False
        assert [event["cursor"] for event in result["events"]] == [4]
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
        assert relay.get_batch(after_cursor=3, limit=8)["events"] == []

        del fake.failures["/health"]
        assert relay.poll_once() is True
        recovered = relay.get_batch(after_cursor=3, limit=8)["events"]
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
    while relay.status()["latest_cursor"] == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    latest = relay.status()["latest_cursor"]
    assert latest == 3
    assert relay.stop(timeout=1) is True
    stopped_batch = relay.get_batch(after_cursor=latest, limit=1, wait_seconds=0.5)
    assert stopped_batch["stopped"] is True
    assert stopped_batch["events"] == []
    client.close()


def test_mcp_tool_is_explicit_bounded_batch_not_native_stream(monkeypatch):
    fake = FakeNode()
    relay, client = make_relay(fake)
    relay.poll_once()
    monkeypatch.setattr(mcp_server, "get_event_relay", lambda: relay)
    try:
        result = mcp_server.rustchain_events(after_cursor=0, limit=2)
        assert result["ok"] is True
        assert result["delivery"] == "bounded_batch_or_long_poll"
        assert result["native_mcp_streaming"] is False
        assert result["next_cursor"] == 2
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
            assert next(lines) == "id: 1"
            assert next(lines) == "event: rustchain.health.snapshot"
            data_line = next(lines)
            payload = data_line.removeprefix("data: ")
            assert payload == canonical_json(json.loads(payload))
            assert json.loads(payload)["cursor"] == 1
    finally:
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
