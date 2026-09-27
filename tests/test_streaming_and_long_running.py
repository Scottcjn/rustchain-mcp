import os

from rustchain_mcp import server


def test_rustchain_timeout_default_and_override():
    assert server.RUSTCHAIN_TIMEOUT in (
        30,
        int(os.environ.get("RUSTCHAIN_TIMEOUT", "30")),
    )


def test_mcp_server_instructions_and_name():
    assert server.mcp.name == "RustChain + BoTTube + Beacon"
    assert "RustChain" in server.mcp.instructions


def test_client_timeout_uses_configuration():
    client = server.get_client()
    assert client.timeout.read == server.RUSTCHAIN_TIMEOUT
