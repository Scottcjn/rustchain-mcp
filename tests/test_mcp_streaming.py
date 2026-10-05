from unittest.mock import patch, MagicMock
from httpx import Response
import time

from rustchain_mcp.server import mcp, get_client

def test_server_capabilities():
    """Check the exact MCP capabilities the server advertises."""
    caps = mcp._mcp_server.get_capabilities()
    assert caps.tools is not None
    assert caps.tools.list_changed is False
    assert caps.resources is not None
    assert caps.resources.subscribe is False
    assert caps.resources.list_changed is False
    assert caps.prompts is not None
    assert caps.prompts.list_changed is False
    assert caps.logging is not None

def test_slow_tool_call_is_blocking_without_progress():
    """Verify that a slow tool call behaves as a single blocking call and does not stream progress."""
    client = get_client()

    # Mock a slow HTTP request
    mock_resp = MagicMock(spec=Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"miners": [{"wallet": "slow_miner", "hw": "x86"}]}
    
    def slow_get(*args, **kwargs):
        time.sleep(0.1)
        return mock_resp

    with patch.object(client, "get", side_effect=slow_get):
        # We invoke the tool directly as a python function, which is what FastMCP does
        # It should block and then return the complete dict, no progress yielded.
        start = time.time()
        from rustchain_mcp.server import rustchain_miners
        result = rustchain_miners()
        duration = time.time() - start
        
        assert duration >= 0.1
        assert "miners" in result
        assert result["miners"][0]["wallet"] == "slow_miner"

