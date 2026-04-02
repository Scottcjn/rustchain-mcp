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


def test_discover_agents_from_a2a_successful_responses(monkeypatch):
    """Test A2A discovery with successful responses."""
    # Mock successful responses for both URLs
    dummy = _DummyClient(
        get_payloads=[
            (200, {"name": "RustChain Agent", "version": "1.0"}),
            (200, {"name": "BoTTube Agent", "version": "2.0"}),
        ]
    )
    monkeypatch.setattr(evangelist_agent, "client", dummy)
    
    # Currently always returns empty list
    result = evangelist_agent.discover_agents_from_a2a()
    assert result == []  # Current behavior
    assert len(dummy._get_payloads) == 0  # Both requests were made


def test_discover_agents_from_a2a_failed_responses(monkeypatch):
    """Test A2A discovery with failed responses."""
    # Mock failed responses (404 and exception)
    dummy = _DummyClient(
        get_payloads=[
            (404, {"error": "Not found"}),
            (500, {"error": "Server error"}),
        ]
    )
    monkeypatch.setattr(evangelist_agent, "client", dummy)
    
    result = evangelist_agent.discover_agents_from_a2a()
    assert result == []  # Should still return empty list
    assert len(dummy._get_payloads) == 0  # Both requests were made


def test_generate_onboarding_post_success(monkeypatch):
    """Test onboarding post generation with successful API calls."""
    dummy = _DummyClient(
        get_payloads=[
            (200, {"version": "2.2.1-rip200", "ok": True}),
            (200, {"agents": 130, "videos": 850, "total_views": 57000}),
        ]
    )
    monkeypatch.setattr(evangelist_agent, "client", dummy)
    
    post = evangelist_agent.generate_onboarding_post()
    
    # Verify post structure
    assert isinstance(post, dict)
    assert "title" in post
    assert "content" in post
    assert "submolt" in post
    assert len(dummy._get_payloads) == 0  # Both requests were made



def test_post_to_moltbook_no_api_key(monkeypatch):
    """Test Moltbook post when API key is not set."""
    # Ensure MOLTBOOK_KEY is not set
    monkeypatch.delenv("MOLTBOOK_KEY", raising=False)
    monkeypatch.setattr(evangelist_agent, "MOLTBOOK_KEY", "")
    
    result = evangelist_agent.post_to_moltbook("Test", "Content", "rustchain", dry_run=False)
    assert result is False


def test_post_to_moltbook_dry_run(monkeypatch):
    """Test Moltbook post in dry-run mode."""
    monkeypatch.setenv("MOLTBOOK_API_KEY", "test-key")
    monkeypatch.setattr(evangelist_agent, "MOLTBOOK_KEY", "test-key")
    
    dummy = _DummyClient()
    monkeypatch.setattr(evangelist_agent, "client", dummy)
    
    result = evangelist_agent.post_to_moltbook("Test", "Content", "rustchain", dry_run=True)
    assert result is True
    assert dummy.posts == []  # No actual post in dry-run


def test_post_to_moltbook_success(monkeypatch):
    """Test successful Moltbook post."""
    monkeypatch.setenv("MOLTBOOK_API_KEY", "test-key")
    monkeypatch.setattr(evangelist_agent, "MOLTBOOK_KEY", "test-key")
    
    dummy = _DummyClient()
    monkeypatch.setattr(evangelist_agent, "client", dummy)
    
    # Mock successful response
    def mock_post(*args, **kwargs):
        class MockResponse:
            status_code = 201
            text = '{"id": "post-123"}'
        return MockResponse()
    
    monkeypatch.setattr(dummy, "post", mock_post)
    
    result = evangelist_agent.post_to_moltbook("Test Title", "Test Content", "rustchain", dry_run=False)
    assert result is True


def test_post_to_moltbook_failure(monkeypatch):
    """Test failed Moltbook post."""
    monkeypatch.setenv("MOLTBOOK_API_KEY", "test-key")
    monkeypatch.setattr(evangelist_agent, "MOLTBOOK_KEY", "test-key")
    
    dummy = _DummyClient()
    monkeypatch.setattr(evangelist_agent, "client", dummy)
    
    # Mock failed response
    def mock_post(*args, **kwargs):
        class MockResponse:
            status_code = 403
            text = '{"error": "Forbidden"}'
        return MockResponse()
    
    monkeypatch.setattr(dummy, "post", mock_post)
    
    result = evangelist_agent.post_to_moltbook("Test", "Content", "rustchain", dry_run=False)
    assert result is False


def test_run_once_dry_run(monkeypatch):
    """Test main run_once function in dry-run mode."""
    # Mock all discovery functions
    def mock_discover_agents_from_a2a():
        return []
    
    def mock_discover_agents_from_beacon():
        return [{"id": "agent-1"}, {"id": "agent-2"}]
    
    def mock_discover_agents_from_bottube():
        return ["agent-2", "agent-3"]
    
    # Track calls to beacon_ping_agent
    ping_calls = []
    def mock_beacon_ping_agent(agent_id, message, dry_run=False):
        ping_calls.append((agent_id, message, dry_run))
        return True
    
    # Mock post functions
    def mock_generate_onboarding_post():
        return {"title": "Test", "content": "Content", "submolt": "rustchain"}
    
    post_calls = []
    def mock_post_to_moltbook(title, content, submolt, dry_run=False):
        post_calls.append((title, content, submolt, dry_run))
        return True
    
    # Apply all mocks
    monkeypatch.setattr(evangelist_agent, "discover_agents_from_a2a", mock_discover_agents_from_a2a)
    monkeypatch.setattr(evangelist_agent, "discover_agents_from_beacon", mock_discover_agents_from_beacon)
    monkeypatch.setattr(evangelist_agent, "discover_agents_from_bottube", mock_discover_agents_from_bottube)
    monkeypatch.setattr(evangelist_agent, "beacon_ping_agent", mock_beacon_ping_agent)
    monkeypatch.setattr(evangelist_agent, "generate_onboarding_post", mock_generate_onboarding_post)
    monkeypatch.setattr(evangelist_agent, "post_to_moltbook", mock_post_to_moltbook)
    
    # Mock AGENT_WALLET to avoid self-ping
    monkeypatch.setattr(evangelist_agent, "AGENT_WALLET", "different-wallet")
    
    # Run in dry-run mode
    pinged = evangelist_agent.run_once(dry_run=True)
    
    # Verify results
    # 3 unique agents discovered: agent-1, agent-2, agent-3 (agent-2 deduplicated)
    # MAX_PINGS_PER_RUN = 5, so should ping all 3 unique agents
    assert pinged == 3  # agent-1, agent-2, agent-3 (after deduplication)
    assert len(ping_calls) == 3
    assert len(post_calls) == 1
    assert post_calls[0][3] is True  # dry_run=True


def test_run_once_no_agents(monkeypatch):
    """Test run_once when no agents are discovered."""
    # Mock empty discoveries
    monkeypatch.setattr(evangelist_agent, "discover_agents_from_a2a", lambda: [])
    monkeypatch.setattr(evangelist_agent, "discover_agents_from_beacon", lambda: [])
    monkeypatch.setattr(evangelist_agent, "discover_agents_from_bottube", lambda: [])
    
    # Track calls
    ping_calls = []
    monkeypatch.setattr(evangelist_agent, "beacon_ping_agent", 
                       lambda *args, **kwargs: ping_calls.append(args) or True)
    
    post_calls = []
    monkeypatch.setattr(evangelist_agent, "post_to_moltbook",
                       lambda *args, **kwargs: post_calls.append(args) or True)
    
    # Mock onboarding post
    monkeypatch.setattr(evangelist_agent, "generate_onboarding_post",
                       lambda: {"title": "T", "content": "C", "submolt": "R"})
    
    pinged = evangelist_agent.run_once(dry_run=False)
    
    assert pinged == 0
    assert len(ping_calls) == 0
    assert len(post_calls) == 1
