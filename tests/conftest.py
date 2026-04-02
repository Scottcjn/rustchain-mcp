"""
Pytest configuration and shared fixtures for rustchain-mcp tests.
"""
import pytest
from unittest.mock import Mock
import httpx
import evangelist_agent


@pytest.fixture
def mock_client(monkeypatch):
    """Mock httpx client for API calls."""
    mock = Mock(spec=httpx.Client)
    
    # Configure default responses
    mock.get.return_value = Mock(
        status_code=200,
        json=lambda: {"agents": [], "top_agents": []}
    )
    mock.post.return_value = Mock(
        status_code=200,
        json=lambda: {"success": True}
    )
    
    monkeypatch.setattr(evangelist_agent, "client", mock)
    return mock


@pytest.fixture
def beacon_response():
    """Sample Beacon Atlas response."""
    return {
        "agents": [
            {"id": "agent-1", "name": "Test Agent 1", "wallet": "wallet-1"},
            {"id": "agent-2", "name": "Test Agent 2", "wallet": "wallet-2"},
        ]
    }


@pytest.fixture
def bottube_response():
    """Sample BoTTube stats response."""
    return {
        "top_agents": [
            {"agent_name": "bottube-agent-1", "videos": 10},
            {"agent_name": "bottube-agent-2", "videos": 5},
        ]
    }


@pytest.fixture
def moltbook_response():
    """Sample Moltbook API response."""
    return {
        "id": "post-123",
        "title": "Test Post",
        "content": "Test content",
        "submolt": "rustchain",
        "created_at": "2026-04-02T14:00:00Z"
    }


@pytest.fixture
def env_vars(monkeypatch):
    """Set environment variables for testing."""
    monkeypatch.setenv("TLS_VERIFY", "0")
    monkeypatch.setenv("RUSTCHAIN_NODE", "https://test-node.example.com")
    monkeypatch.setenv("BOTTUBE_URL", "https://test-bottube.example.com")
    monkeypatch.setenv("BEACON_URL", "https://test-beacon.example.com")
    monkeypatch.setenv("MOLTBOOK_URL", "https://test-moltbook.example.com")
    monkeypatch.setenv("EVANGELIST_WALLET", "test-wallet")
    monkeypatch.setenv("MOLTBOOK_API_KEY", "test-moltbook-key")
    monkeypatch.setenv("BOTTUBE_API_KEY", "test-bottube-key")
    
    # Restore after test
    yield
    
    # Cleanup
    for var in ["TLS_VERIFY", "RUSTCHAIN_NODE", "BOTTUBE_URL", "BEACON_URL", 
                "MOLTBOOK_URL", "EVANGELIST_WALLET", "MOLTBOOK_API_KEY", "BOTTUBE_API_KEY"]:
        monkeypatch.delenv(var, raising=False)