"""Offline regression tests for the documented MCP capability & tool-context contract (#231 / #16255).

All tests are synchronous (using ``asyncio.run(...)`` where FastMCP methods are
coroutines) so they pass in CI without ``pytest-asyncio``.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from unittest.mock import patch

from mcp.server.lowlevel.server import NotificationOptions

from rustchain_mcp import server


def test_advertised_mcp_capabilities_match_readme_contract():
    """The server's advertised MCP capabilities must match the README contract:
    tools(list_changed=False), resources(subscribe=False, list_changed=False),
    prompts(list_changed=False), and no experimental streaming capability."""
    low_server = getattr(server.mcp, "_mcp_server", None)
    assert low_server is not None
    caps = low_server.get_capabilities(NotificationOptions(), {})

    assert caps.tools is not None
    assert caps.tools.list_changed is False
    assert caps.resources is not None
    assert caps.resources.subscribe is False
    assert caps.resources.list_changed is False
    assert caps.prompts is not None
    assert caps.prompts.list_changed is False
    assert caps.experimental in (None, {})


def test_no_registered_tool_accepts_fastmcp_context_or_progress_param():
    """Every registered tool on the FastMCP server is synchronous request/response
    and does not accept a FastMCP Context or progress callback parameter."""
    tools = asyncio.run(server.mcp.list_tools())
    assert len(tools) >= 35

    for tool in tools:
        schema = getattr(tool, "parameters", None) or getattr(tool, "inputSchema", {}) or {}
        props = schema.get("properties", {}) if isinstance(schema, dict) else {}
        assert "ctx" not in props, f"{tool.name} exposes ctx in tool schema"
        assert "context" not in props, f"{tool.name} exposes context in tool schema"
        assert "progress" not in props, f"{tool.name} exposes progress in tool schema"

        fn = getattr(server, tool.name, None)
        if callable(fn):
            sig = inspect.signature(fn)
            for param_name, param in sig.parameters.items():
                ann = str(param.annotation)
                assert "Context" not in ann, (
                    f"{tool.name} parameter {param_name} uses FastMCP Context ({ann})"
                )


def test_slow_mocked_tool_blocks_and_returns_single_complete_dict():
    """A slow mocked tool call blocks until the upstream response arrives and
    returns a single complete dict without emitting incremental chunks."""

    class SlowResponse:
        status_code = 200
        text = '{"ok": true}'

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "ok": True,
                "version": "2.2.1-rip200",
                "uptime_s": 867443,
                "db_rw": True,
            }

    class SlowClient:
        def get(self, url, *args, **kwargs):
            time.sleep(0.05)
            return SlowResponse()

    start = time.monotonic()
    with patch.object(server, "get_client", return_value=SlowClient()):
        result = server.rustchain_health()
    elapsed = time.monotonic() - start

    assert elapsed >= 0.045
    assert isinstance(result, dict)
    assert result.get("ok") is True
    assert result.get("version") == "2.2.1-rip200"


def test_tests_init_files_exist_for_pytest_collection():
    """Ensure tests/ and tests/unit/ and tests/mocks/ are importable under plain pytest."""
    from pathlib import Path

    tests_dir = Path(__file__).resolve().parent
    assert (tests_dir / "__init__.py").exists()
    assert (tests_dir / "mocks" / "__init__.py").exists()
    assert (tests_dir / "unit" / "__init__.py").exists()
