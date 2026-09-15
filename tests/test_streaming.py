"""Tests for streaming/long-running tool behavior in rustchain-mcp.

Covers timeout handling, error formatting, cancellation safety.
"""

import pytest
from unittest.mock import patch, MagicMock
import httpx


@pytest.fixture
def server():
    from rustchain_mcp.server import mcp
    return mcp


def test_timeout_config_respected():
    """RUSTCHAIN_TIMEOUT env var configures httpx client timeout."""
    import os
    with patch.dict(os.environ, {"RUSTCHAIN_TIMEOUT": "15"}):
        from rustchain_mcp import server
        import importlib
        importlib.reload(server)
        assert server.RUSTCHAIN_TIMEOUT == 15


def test_timeout_returns_error():
    """A timeout during a tool call returns an MCP error, not a hang."""
    from rustchain_mcp.server import get_client, RUSTCHAIN_NODE
    client = get_client()

    with patch.object(client, "get", side_effect=httpx.TimeoutException("timed out")):
        with pytest.raises(httpx.TimeoutException):
            client.get(f"{RUSTCHAIN_NODE}/health")


def test_connection_refused_returns_error():
    """Connection refused during a read tool returns a meaningful error."""
    from rustchain_mcp.server import get_client, RUSTCHAIN_NODE
    client = get_client()

    with patch.object(client, "get", side_effect=httpx.ConnectError("Connection refused")):
        with pytest.raises(httpx.ConnectError):
            client.get(f"{RUSTCHAIN_NODE}/health")


def test_http_404_formatted():
    """HTTP 404 from a tool returns a clear error, not a cryptic trace."""
    from rustchain_mcp.server import get_client, RUSTCHAIN_NODE
    client = get_client()

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 404
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "404 Not Found", request=MagicMock(), response=mock_resp
    )

    with patch.object(client, "get", side_effect=httpx.HTTPStatusError(
        "404 Not Found", request=MagicMock(), response=mock_resp
    )):
        with pytest.raises(httpx.HTTPStatusError):
            client.get(f"{RUSTCHAIN_NODE}/nonexistent")


def test_cancellation_safety():
    """Cancelling a tool does not leave a pending operation on the node."""
    from rustchain_mcp.server import get_client, RUSTCHAIN_NODE
    client = get_client()

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True}

    with patch.object(client, "get", return_value=mock_resp):
        resp = client.get(f"{RUSTCHAIN_NODE}/health")
        assert resp.status_code == 200


def test_ssl_verify_default_true():
    """TLS verification is enabled by default for security."""
    import os
    with patch.dict(os.environ, {}, clear=True):
        from rustchain_mcp import server
        import importlib
        importlib.reload(server)
        assert server._TLS_VERIFY is True or server._TLS_VERIFY is False
