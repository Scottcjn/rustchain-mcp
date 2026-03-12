from __future__ import annotations

from typing import Any

import evangelist_agent


class _DummyResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> Any:
        return self._payload


class _DummyClient:
    def __init__(self, get_payloads: list[tuple[int, Any]] | None = None):
        self._get_payloads = list(get_payloads or [])
        self.posts: list[tuple[str, Any]] = []

    def get(self, url: str, params: dict[str, Any] | None = None, timeout: int | None = None, follow_redirects: bool | None = None):  # noqa: ARG002,E501
        if self._get_payloads:
            code, payload = self._get_payloads.pop(0)
            return _DummyResponse(code, payload)
        return _DummyResponse(500, {"error": "no payloads"})

    def post(self, url: str, json: Any = None, headers: dict[str, str] | None = None, timeout: int | None = None):  # noqa: ARG002,E501
        self.posts.append((url, json))
        return _DummyResponse(500, {"error": "post not configured"})


def test_discover_agents_from_beacon_handles_non_object_json(monkeypatch):
    # Edge case: server returns a JSON array instead of {"agents": [...]}
    dummy = _DummyClient(get_payloads=[(200, ["not", "an", "object"])])
    monkeypatch.setattr(evangelist_agent, "client", dummy)

    assert evangelist_agent.discover_agents_from_beacon() == []


def test_discover_agents_from_bottube_filters_bad_entries(monkeypatch):
    dummy = _DummyClient(
        get_payloads=[
            (200, {"top_agents": [{"agent_name": "a"}, {"agent_name": 123}, "oops", {}]}),
        ]
    )
    monkeypatch.setattr(evangelist_agent, "client", dummy)

    assert evangelist_agent.discover_agents_from_bottube() == ["a"]


def test_beacon_ping_agent_dry_run_does_not_post(monkeypatch):
    dummy = _DummyClient()
    monkeypatch.setattr(evangelist_agent, "client", dummy)

    ok = evangelist_agent.beacon_ping_agent("agent-1", "hello", dry_run=True)
    assert ok is True
    assert dummy.posts == []

