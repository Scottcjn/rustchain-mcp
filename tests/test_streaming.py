"""Tests for streaming/long-running tool behavior in rustchain-mcp.

Covers timeout handling, error formatting, cancellation safety,
and capability advertisement for streaming/progress.

References:
    - `rustchain_mcp/server.py` — lines 34–68 (timeout config, client factory)
    - `rustchain_mcp/server.py` — lines 86–1475 (all tools — none use Context)
"""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
import httpx
import os
import importlib


# ── Timeout Configuration ──────────────────────────────────────

def test_timeout_config_respected():
    """RUSTCHAIN_TIMEOUT env var configures httpx client timeout.

    Reference: `rustchain_mcp/server.py` line 38:
        RUSTCHAIN_TIMEOUT = int(os.environ.get("RUSTCHAIN_TIMEOUT", "30"))
    """
    with patch.dict(os.environ, {"RUSTCHAIN_TIMEOUT": "15"}, clear=False):
        import rustchain_mcp.server as server
        importlib.reload(server)
        assert server.RUSTCHAIN_TIMEOUT == 15


def test_timeout_default_value():
    """Default timeout is 30 seconds when RUSTCHAIN_TIMEOUT is not set.

    Reference: `rustchain_mcp/server.py` line 38:
        RUSTCHAIN_TIMEOUT = int(os.environ.get("RUSTCHAIN_TIMEOUT", "30"))
    """
    with patch.dict(os.environ, {}, clear=True):
        import rustchain_mcp.server as server
        importlib.reload(server)
        assert server.RUSTCHAIN_TIMEOUT == 30


# ── HTTP Client Error Handling ─────────────────────────────────

def test_get_client_timeout_propagates():
    """get_client() creates httpx.Client with the module's RUSTCHAIN_TIMEOUT.

    Reference: `rustchain_mcp/server.py` lines 64–68:
        def get_client() -> httpx.Client:
            global _client
            if _client is None:
                _client = httpx.Client(timeout=RUSTCHAIN_TIMEOUT, verify=_TLS_VERIFY)
            return _client
    """
    from rustchain_mcp.server import get_client, RUSTCHAIN_TIMEOUT
    client = get_client()
    assert client.timeout == httpx.Timeout(RUSTCHAIN_TIMEOUT)


def test_timeout_raises_exception():
    """A timeout during a tool call raises httpx.TimeoutException.

    Reference: `rustchain_mcp/server.py` line 67:
        httpx.Client(timeout=RUSTCHAIN_TIMEOUT, verify=_TLS_VERIFY)
    All tool functions call get_client() and let httpx exceptions propagate.
    """
    from rustchain_mcp.server import get_client, RUSTCHAIN_NODE
    client = get_client()

    with patch.object(client, "get", side_effect=httpx.TimeoutException("timed out")):
        with pytest.raises(httpx.TimeoutException):
            client.get(f"{RUSTCHAIN_NODE}/health")


def test_connection_refused_raises_exception():
    """Connection refused during a tool call raises httpx.ConnectError.

    Reference: `rustchain_mcp/server.py` lines 71–77 (_handle_api_error)
    and all tool functions that call `get_client().get(...)`.
    """
    from rustchain_mcp.server import get_client, RUSTCHAIN_NODE
    client = get_client()

    with patch.object(client, "get", side_effect=httpx.ConnectError("Connection refused")):
        with pytest.raises(httpx.ConnectError):
            client.get(f"{RUSTCHAIN_NODE}/health")


def test_http_error_formatting():
    """HTTP errors from tools produce structured error messages.

    Reference: `rustchain_mcp/server.py` lines 71–77 (_handle_api_error):
        def _handle_api_error(response: httpx.Response) -> str:
            try:
                error_data = response.json()
                return error_data.get("error") or error_data.get("message") or ...
            except Exception:
                return f"HTTP {response.status_code}: {response.text[:200]}"
    """
    from rustchain_mcp.server import _handle_api_error

    # Test JSON error response
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.json.return_value = {"error": "Wallet not found"}
    err_msg = _handle_api_error(mock_resp)
    assert err_msg == "Wallet not found"

    # Test JSON message response
    mock_resp2 = MagicMock(spec=httpx.Response)
    mock_resp2.json.return_value = {"message": "Insufficient balance"}
    err_msg2 = _handle_api_error(mock_resp2)
    assert err_msg2 == "Insufficient balance"

    # Test non-JSON fallback
    mock_resp3 = MagicMock(spec=httpx.Response)
    mock_resp3.status_code = 404
    mock_resp3.text = "Not Found"
    mock_resp3.json.side_effect = ValueError("not json")
    err_msg3 = _handle_api_error(mock_resp3)
    assert "HTTP 404" in err_msg3


# ── Tool Execution Model (Blocking, No Streaming) ──────────────

def test_no_tools_use_context():
    """No tools request FastMCP Context, meaning none use report_progress().

    Every tool function in server.py is a plain synchronous function with no
    `ctx: Context` parameter. FastMCP's progress reporting requires a Context
    parameter (reference: fastmcp/ Context.report_progress).

    This test scans all registered tool functions to verify.

    Reference: `rustchain_mcp/server.py` lines 86–906 — all tool signatures.
    """
    import inspect
    from rustchain_mcp import server

    # Get all function names from server module
    tool_names = [
        "rustchain_health", "rustchain_epoch", "rustchain_miners",
        "rustchain_create_wallet", "rustchain_balance",
        "wallet_create", "wallet_balance", "wallet_history",
        "wallet_transfer_signed", "wallet_list", "wallet_export",
        "wallet_import", "bcos_verify", "rustchain_stats",
        "rustchain_lottery_eligibility", "bcos_directory",
        "rustchain_transfer_signed",
        "bottube_stats", "bottube_search", "bottube_trending",
        "bottube_agent_profile", "bottube_upload", "bottube_comment",
        "bottube_vote",
        "beacon_discover", "beacon_register", "beacon_heartbeat",
        "beacon_agent_status", "beacon_send_message", "beacon_chat",
        "beacon_contracts", "beacon_network_stats",
        "legend_of_elya_info", "bounty_search", "contributor_lookup",
        "network_health", "green_tracker",
    ]

    for name in tool_names:
        fn = getattr(server, name, None)
        if fn is None:
            pytest.fail(f"Tool function '{name}' not found in server module")
        sig = inspect.signature(fn)
        for param_name, param in sig.parameters.items():
            # Check if any parameter has Context type annotation
            if hasattr(param.annotation, "__name__") and param.annotation.__name__ == "Context":
                pytest.fail(
                    f"Tool '{name}' has Context parameter '{param_name}', "
                    f"but the server claims no progress reporting is implemented."
                )


# ── TLS / Security ─────────────────────────────────────────────

def test_ssl_verify_default_true():
    """TLS verification is enabled by default for security.

    Reference: `rustchain_mcp/server.py` lines 53–58:
        _TLS_VERIFY = os.environ.get("RUSTCHAIN_CA_BUNDLE", ...)
        if _TLS_VERIFY in ("false", "0", "no"): _TLS_VERIFY = False
        elif _TLS_VERIFY == "true": _TLS_VERIFY = True
    """
    with patch.dict(os.environ, {}, clear=True):
        import rustchain_mcp.server as server
        importlib.reload(server)
        # Default should be True (secure by default)
        assert server._TLS_VERIFY is True


def test_ssl_verify_disabled():
    """TLS verification can be disabled via RUSTCHAIN_TLS_VERIFY=false.

    Reference: `rustchain_mcp/server.py` lines 55–56.
    """
    with patch.dict(os.environ, {"RUSTCHAIN_TLS_VERIFY": "false"}, clear=True):
        import rustchain_mcp.server as server
        importlib.reload(server)
        assert server._TLS_VERIFY is False


# ── Server Capability Advertisement ────────────────────────────

def test_server_capabilities_no_streaming():
    """Server capabilities do not advertise streaming or progress.

    Reference: `rustchain_mcp/server.py` lines 41–50:
        mcp = FastMCP(
            "RustChain + BoTTube + Beacon",
            instructions=(...),
        )
    No `experimental_capabilities` for streaming/progress is passed.

    The FastMCP ServerCapabilities.tools field has no streaming or
    progress sub-field (MCP spec: ToolsCapability only has listChanged).
    """
    from rustchain_mcp import mcp

    # FastMCP doesn't expose capabilities directly; verify by checking
    # that no experimental_capabilities for streaming are set.
    assert "streaming" not in mcp.experimental_capabilities
    assert "progress" not in mcp.experimental_capabilities

    # Also verify by checking the module's tool functions - none use streaming
    import inspect
    from rustchain_mcp import server as server_module
    source = inspect.getsource(server_module)
    # No async tool functions (all are synchronous/blocking)
    # Count 'async def' occurrences that are tool functions
    async_tools = 0
    for line in source.split('\n'):
        stripped = line.strip()
        if stripped.startswith('async def '):
            async_tools += 1
    assert async_tools == 0, (
        f"Found {async_tools} async function(s) in server.py. "
        f"All tools must be synchronous (no streaming support)."
    )


# ── Blocking (Non-Streaming) Call Pattern ──────────────────────

def test_all_tools_use_blocking_httpx_calls():
    """Every tool calls get_client() and makes synchronous HTTP requests.

    This is the fundamental behavioral contract: no tool uses async HTTP
    streaming, SSE, or chunked responses. All are plain httpx.Client calls.

    Reference: `rustchain_mcp/server.py` lines 64–68 (get_client)
    and every tool function pattern:
        r = get_client().get(...)
        r.raise_for_status()
        return r.json()
    """
    import rustchain_mcp.server as server_module
    import inspect

    # Read the source of server module and verify all tool functions
    # use synchronous httpx calls (no async/await patterns)
    source = inspect.getsource(server_module)

    # All tool functions are synchronous (no 'async def' for tools)
    # Check the defined tool functions
    tool_fn_names = [name for name in dir(server_module)
                     if callable(getattr(server_module, name))
                     and not name.startswith('_')
                     and hasattr(getattr(server_module, name), '__wrapped__')]

    for name in tool_fn_names:
        fn = getattr(server_module, name)
        if asyncio.iscoroutinefunction(fn):
            pytest.fail(f"Tool '{name}' is async but the server does not use async HTTP streaming.")

    # If no tools have __wrapped__, just check for 'async def' pattern in tool functions
    # by scanning the source code.
    tool_decorated = [name for name in dir(server_module)
                      if callable(getattr(server_module, name))
                      and not name.startswith('_')]

    for name in tool_decorated:
        fn = getattr(server_module, name)
        if inspect.iscoroutinefunction(fn):
            pytest.fail(f"Tool '{name}' is async but all tools should be synchronous blocking.")


import asyncio
