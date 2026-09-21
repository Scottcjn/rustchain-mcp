"""Boot-level compatibility tests for the MCP server.

Context: ``mcp`` 2.0.0 (2026-07-28) removed ``mcp.server.fastmcp``. This
package builds on the standalone ``fastmcp`` distribution instead, which
tracks the ``mcp`` SDK on its own release cadence. These tests pin down the
things that must stay true for a fresh ``pip install rustchain-mcp`` to boot:

* nothing in the package imports the removed ``mcp.server.fastmcp`` path;
* the server object can be driven end-to-end by a real MCP client (in-memory
  transport, no subprocess) under whichever ``fastmcp`` version is installed;
* every documented tool and resource is actually registered.

They run against the installed ``fastmcp`` without pytest-asyncio so the CI
matrix needs nothing beyond ``pytest`` and the package itself.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
from unittest import mock

import pytest

import rustchain_mcp
from rustchain_mcp import server

PACKAGE_DIR = pathlib.Path(rustchain_mcp.__file__).parent

# Every tool the README documents. If a tool is added or renamed, update this
# list and the README together.
EXPECTED_TOOLS = {
    # Wallet management
    "wallet_create", "wallet_balance", "wallet_history", "wallet_transfer_signed",
    "wallet_list", "wallet_export", "wallet_import",
    # RustChain
    "rustchain_health", "rustchain_epoch", "rustchain_miners",
    "rustchain_create_wallet", "rustchain_balance", "rustchain_stats",
    "rustchain_lottery_eligibility", "rustchain_transfer_signed",
    "rustchain_events",
    # Ecosystem & discovery
    "legend_of_elya_info", "bounty_search", "contributor_lookup",
    "network_health", "green_tracker",
    # BCOS
    "bcos_verify", "bcos_directory",
    # BoTTube
    "bottube_stats", "bottube_search", "bottube_trending",
    "bottube_agent_profile", "bottube_upload", "bottube_comment", "bottube_vote",
    # Beacon
    "beacon_discover", "beacon_register", "beacon_heartbeat",
    "beacon_agent_status", "beacon_send_message", "beacon_chat",
    "beacon_contracts", "beacon_network_stats",
}

EXPECTED_RESOURCES = {
    "rustchain://about",
    "bottube://about",
    "beacon://about",
    "rustchain://bounties",
    "rustchain://green-tracker",
}


def _run(coro):
    """Run a coroutine to completion without requiring pytest-asyncio."""
    return asyncio.run(coro)


def _client():
    """An in-memory MCP client bound directly to the server object."""
    from fastmcp import Client

    return Client(server.mcp)


def _text_payload(result) -> dict:
    """Extract the JSON dict a tool returned, across fastmcp result shapes."""
    content = getattr(result, "content", result)
    first = content[0]
    return json.loads(first.text)


# ── Import-path guard ──────────────────────────────────────────────


def test_package_does_not_import_removed_mcp_fastmcp_path():
    """``mcp.server.fastmcp`` no longer exists in mcp>=2; we must never use it."""
    pattern = re.compile(r"^\s*(from|import)\s+mcp\.server\.fastmcp\b", re.MULTILINE)
    offenders = [
        str(path.relative_to(PACKAGE_DIR.parent))
        for path in PACKAGE_DIR.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"removed import path used in: {offenders}"


def test_server_is_a_standalone_fastmcp_instance():
    from fastmcp import FastMCP

    assert isinstance(server.mcp, FastMCP)
    assert rustchain_mcp.mcp is server.mcp


# ── Protocol-level boot ────────────────────────────────────────────


def test_client_lists_every_documented_tool():
    async def _list():
        async with _client() as client:
            return {tool.name for tool in await client.list_tools()}

    names = _run(_list())
    missing = EXPECTED_TOOLS - names
    extra = names - EXPECTED_TOOLS
    assert not missing, f"tools documented but not registered: {sorted(missing)}"
    assert not extra, f"tools registered but undocumented: {sorted(extra)}"


def test_client_lists_every_documented_resource():
    async def _list():
        async with _client() as client:
            return {str(res.uri) for res in await client.list_resources()}

    assert _run(_list()) == EXPECTED_RESOURCES


def test_every_tool_has_a_description():
    """Tool descriptions are a stranger's first contact; none may be blank."""

    async def _list():
        async with _client() as client:
            return await client.list_tools()

    blank = [t.name for t in _run(_list()) if not (t.description or "").strip()]
    assert blank == [], f"tools with empty descriptions: {blank}"


def test_tool_call_round_trips_through_the_protocol():
    """A real client call reaches the tool body and returns its JSON."""

    class FakeResponse:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"ok": True, "version": "test-boot"}

    class FakeClient:
        def get(self, url, **kwargs):
            assert url.endswith("/health"), url
            return FakeResponse()

    async def _call():
        async with _client() as client:
            return await client.call_tool("rustchain_health", {})

    with mock.patch.object(server, "get_client", return_value=FakeClient()):
        payload = _text_payload(_run(_call()))

    assert payload == {"ok": True, "version": "test-boot"}


def test_tool_input_validation_is_enforced_by_the_protocol():
    """Missing required arguments are rejected before the tool body runs."""
    from fastmcp.exceptions import ToolError

    async def _call():
        async with _client() as client:
            await client.call_tool("rustchain_balance", {})

    with pytest.raises(ToolError):
        _run(_call())
