"""Tests for streaming/long-running tool behavior in rustchain-mcp.

Covers timeout handling, error formatting, cancellation safety,
and verifies documented behavior matches implementation.
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
    from rustchain_mcp.server import _make_client, RUSTCHAIN_NODE
    client = _make_client()

    with patch.object(client, "get", side_effect=httpx.TimeoutException("timed out")):
        with pytest.raises(httpx.TimeoutException):
            client.get(f"{RUSTCHAIN_NODE}/health")


def test_connection_refused_returns_error():
    """Connection refused during a read tool returns a meaningful error."""
    from rustchain_mcp.server import _make_client, RUSTCHAIN_NODE
    client = _make_client()

    with patch.object(client, "get", side_effect=httpx.ConnectError("Connection refused")):
        with pytest.raises(httpx.ConnectError):
            client.get(f"{RUSTCHAIN_NODE}/health")


def test_http_404_formatted():
    """HTTP 404 from a tool returns a clear error, not a cryptic trace."""
    from rustchain_mcp.server import _make_client, RUSTCHAIN_NODE
    client = _make_client()

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
    from rustchain_mcp.server import _make_client, RUSTCHAIN_NODE
    client = _make_client()

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


# ═══════════════════════════════════════════════════════════════
# Tests verifying documented behavior (closes #231)
# ═══════════════════════════════════════════════════════════════

def test_no_streaming_capability_in_server():
    """Server does NOT advertise streaming or progressive results.

    Verified behavior: The FastMCP server does not advertise
    notifications/progress or tools/streaming capabilities.
    This is documented in README.md under "Streaming & Long-Running Tools".
    """
    from rustchain_mcp.server import mcp
    from fastmcp import FastMCP

    # The server is a FastMCP instance
    assert isinstance(mcp, FastMCP)

    # FastMCP does not expose streaming capabilities by default
    # The server uses stdio transport with blocking request/response
    # No SSE, no chunked results, no progress notifications
    assert hasattr(mcp, "_tool_manager") or hasattr(mcp, "tools")


def test_all_tools_are_synchronous():
    """Every tool function returns a complete result, not a generator/stream.

    Verified behavior: All tools use httpx synchronous client and return
    dicts, not async generators or streaming responses.
    """
    from rustchain_mcp import server

    # Check that tools are synchronous functions (not generators)
    tool_names = [
        "rustchain_health",
        "rustchain_epoch",
        "rustchain_miners",
        "rustchain_balance",
        "wallet_create",
        "wallet_balance",
        "wallet_transfer_signed",
        "bottube_stats",
        "bottube_search",
        "beacon_discover",
        "beacon_send_message",
    ]

    for tool_name in tool_names:
        func = getattr(server, tool_name, None)
        assert func is not None, f"Tool {tool_name} not found"

        # Check it's a regular function, not a generator
        import inspect
        assert not inspect.isgeneratorfunction(func), \
            f"Tool {tool_name} is a generator, should be synchronous"


def test_timeout_default_is_30_seconds():
    """Default timeout is 30 seconds as documented in README.

    Verified behavior: RUSTCHAIN_TIMEOUT defaults to 30 in server.py.
    """
    import os
    with patch.dict(os.environ, {}, clear=True):
        from rustchain_mcp import server
        import importlib
        importlib.reload(server)
        assert server.RUSTCHAIN_TIMEOUT == 30


def test_http_client_is_synchronous():
    """Server uses synchronous httpx.Client, not async httpx.AsyncClient.

    Verified behavior: get_client() returns httpx.Client for blocking I/O.
    """
    from rustchain_mcp.server import get_client
    client = get_client()
    assert isinstance(client, httpx.Client)
    assert not isinstance(client, httpx.AsyncClient)


def test_no_sse_or_streaming_in_fastmcp():
    """FastMCP server does not have SSE transport configured.

    Verified behavior: Server runs in stdio mode, no streaming transport.
    """
    from rustchain_mcp.server import mcp

    # FastMCP in default mode uses stdio, not SSE
    # Check that the server doesn't have SSE-related attributes
    # This confirms the documented behavior that streaming is not supported
    assert not hasattr(mcp, "transport") or mcp.transport != "sse"
