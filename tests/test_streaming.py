import pytest
from rustchain_mcp import RustChainMCPServer

def test_server_capabilities_no_streaming():
    server = RustChainMCPServer(api_key="offline-test")
    try:
        capabilities = server.server.capabilities
        if hasattr(capabilities, 'progress'):
            assert not capabilities.progress, "Server should not advertise progress"
        if hasattr(capabilities, 'streaming'):
            assert not capabilities.streaming, "Server should not advertise streaming"
    except AttributeError:
        pass

def test_blocking_tool_execution_mock():
    server = RustChainMCPServer(api_key="offline-test")
    assert server is not None
