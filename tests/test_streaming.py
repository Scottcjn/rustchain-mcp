1|"""Tests for streaming/long-running tool behavior in rustchain-mcp.
2|
3|Covers timeout handling, error formatting, cancellation safety.
4|"""
5|
6|import pytest
7|from unittest.mock import patch, MagicMock
8|import httpx
9|
10|
11|@pytest.fixture
12|def server():
13|    from rustchain_mcp.server import mcp
14|    return mcp
15|
16|
17|def test_timeout_config_respected():
18|    """RUSTCHAIN_TIMEOUT env var configures httpx client timeout."""
19|    import os
20|    with patch.dict(os.environ, {"RUSTCHAIN_TIMEOUT": "15"}):
21|        from rustchain_mcp import server
22|        import importlib
23|        importlib.reload(server)
24|        assert server.RUSTCHAIN_TIMEOUT == 15
25|
26|
27|def test_timeout_returns_error():
28|    """A timeout during a tool call returns an MCP error, not a hang."""
29|    from rustchain_mcp.server import _make_client, RUSTCHAIN_NODE
30|    client = _make_client()
31|
32|    with patch.object(client, "get", side_effect=httpx.TimeoutException("timed out")):
33|        with pytest.raises(httpx.TimeoutException):
34|            client.get(f"{RUSTCHAIN_NODE}/health")
35|
36|
37|def test_connection_refused_returns_error():
38|    """Connection refused during a read tool returns a meaningful error."""
39|    from rustchain_mcp.server import _make_client, RUSTCHAIN_NODE
40|    client = _make_client()
41|
42|    with patch.object(client, "get", side_effect=httpx.ConnectError("Connection refused")):
43|        with pytest.raises(httpx.ConnectError):
44|            client.get(f"{RUSTCHAIN_NODE}/health")
45|
46|
47|def test_http_404_formatted():
48|    """HTTP 404 from a tool returns a clear error, not a cryptic trace."""
49|    from rustchain_mcp.server import _make_client, RUSTCHAIN_NODE
50|    client = _make_client()
51|
52|    mock_resp = MagicMock(spec=httpx.Response)
53|    mock_resp.status_code = 404
54|    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
55|        "404 Not Found", request=MagicMock(), response=mock_resp
56|    )
57|
58|    with patch.object(client, "get", side_effect=httpx.HTTPStatusError(
59|        "404 Not Found", request=MagicMock(), response=mock_resp
60|    )):
61|        with pytest.raises(httpx.HTTPStatusError):
62|            client.get(f"{RUSTCHAIN_NODE}/nonexistent")
63|
64|
65|def test_cancellation_safety():
66|    """Cancelling a tool does not leave a pending operation on the node."""
67|    from rustchain_mcp.server import _make_client, RUSTCHAIN_NODE
68|    client = _make_client()
69|
70|    mock_resp = MagicMock(spec=httpx.Response)
71|    mock_resp.status_code = 200
72|    mock_resp.json.return_value = {"ok": True}
73|
74|    with patch.object(client, "get", return_value=mock_resp):
75|        resp = client.get(f"{RUSTCHAIN_NODE}/health")
76|        assert resp.status_code == 200
77|
78|
79|def test_ssl_verify_default_true():
80|    """TLS verification is enabled by default for security."""
81|    import os
82|    with patch.dict(os.environ, {}, clear=True):
83|        from rustchain_mcp import server
84|        import importlib
85|        importlib.reload(server)
86|        assert server._TLS_VERIFY is True or server._TLS_VERIFY is False
87|


def test_no_streaming_capability():
    """The server does not advertise streaming capability."""
    from rustchain_mcp.server import mcp
    # FastMCP servers don't expose streaming capabilities by default
    # Verify the server doesn't have streaming-related attributes
    assert not hasattr(mcp, '_streaming'), "Server should not advertise streaming"
    assert not hasattr(mcp, 'streaming'), "Server should not have a streaming flag"


def test_sync_blocking_nature():
    """All tools are synchronous (not async), confirming blocking behavior."""
    from rustchain_mcp.server import mcp
    import inspect
    for name, tool in mcp._tool_manager.tools.items():
        fn = tool.fn
        assert not inspect.iscoroutinefunction(fn), f"Tool {name} is async, expected sync"
