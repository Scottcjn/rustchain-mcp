"""Every network-facing tool's request construction, checked against fixtures.

The RustChain, BoTTube, and Beacon APIs drift; a tool can silently start
hitting a path or sending a payload the node no longer accepts while every
unit test that mocks ``get_client`` keeps passing. This test pins the exact
HTTP requests each tool builds (method, URL, query params, JSON body, headers)
to ``tests/fixtures/tool_requests.json``.

Each fixture case has:

* ``tool`` and ``args``: what to call.
* ``responses``: canned response(s) the fake client returns, in order. A
  single object is reused for every request.
* ``requests``: the exact requests the tool must make, in order. Volatile
  values (timestamps, nonces) are written as ``"<any>"``.

To regenerate after an intentional change, run:

    RUSTCHAIN_MCP_UPDATE_FIXTURES=1 pytest tests/test_tool_requests.py

then review the diff of the fixture file like any other code change.
"""

from __future__ import annotations

import contextlib
import copy
import json
import os
import pathlib
from typing import Any
from unittest import mock

import pytest

from rustchain_mcp import server

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "tool_requests.json"
UPDATE = os.environ.get("RUSTCHAIN_MCP_UPDATE_FIXTURES") == "1"

# Fixed bases so the fixture never depends on deployment defaults.
BASES = {
    "RUSTCHAIN_NODE": "https://rustchain.test",
    "BOTTUBE_URL": "https://bottube.test",
    "BEACON_URL": "https://beacon.test/beacon",
}

ANY = "<any>"

# Tool -> arguments. Tools that touch only the local keystore, the event
# relay, or a dynamic node list are covered elsewhere and deliberately omitted.
CASES: dict[str, dict[str, Any]] = {
    "rustchain_health": {},
    "rustchain_epoch": {},
    "rustchain_miners": {},
    "rustchain_create_wallet": {"agent_name": "fixture-agent"},
    "rustchain_balance": {"wallet_id": "dual-g4-125"},
    "wallet_balance": {"wallet_id": "RTCfixture0000000000000000000000000000000000"},
    "wallet_history": {"wallet_id": "RTCfixture0000000000000000000000000000000000", "limit": 500},
    "rustchain_stats": {},
    "rustchain_lottery_eligibility": {"miner_id": "dual-g4-125"},
    "rustchain_transfer_signed": {
        "from_address": "RTCfrom", "to_address": "RTCto", "amount_rtc": 1.25,
        "signature": "ab" * 64, "public_key": "cd" * 32, "memo": "fixture",
        "nonce": 1700000000000,
    },
    "bcos_verify": {"cert_id": "BCOS-9fef0ce3"},
    "bcos_directory": {"tier": "gold", "limit": 5},
    "bottube_stats": {},
    "bottube_search": {"query": "vintage", "page": 2},
    "bottube_trending": {"limit": 500},
    "bottube_agent_profile": {"agent_name": "sophia-elya"},
    "bottube_comment": {"video_id": "vid1", "content": "hello", "api_key": "k"},
    "bottube_vote": {"video_id": "vid1", "direction": "down", "api_key": "k"},
    "beacon_discover": {"provider": "anthropic", "capability": "coding"},
    "beacon_register": {
        "name": "fixture-bot", "pubkey_hex": "ef" * 32, "model_id": "m",
        "provider": "other", "capabilities": "coding, research",
        "webhook_url": "https://hook.test/in",
    },
    "beacon_heartbeat": {"agent_id": "bcn_x", "relay_token": "tok", "status": "degraded"},
    "beacon_agent_status": {"agent_id": "bcn_x"},
    "beacon_send_message": {
        "relay_token": "tok", "from_agent": "bcn_a", "to_agent": "bcn_b",
        "content": "hi", "kind": "hello",
    },
    "beacon_chat": {"agent_id": "bcn_sophia_elya", "message": "hi"},
    "beacon_contracts": {"agent_id": "bcn_a"},
    "beacon_network_stats": {},
    "bounty_search": {"keyword": "docs", "difficulty": "easy", "repo": "all"},
    "contributor_lookup": {"username": "createkr"},
    "green_tracker": {},
}

# Tools whose endpoints return a JSON array rather than an object.
LIST_RESPONSE = {
    "status": 200,
    "body": [
        {"agent_id": "bcn_a", "provider": "anthropic", "capabilities": ["coding"],
         "from": "bcn_a", "to": "bcn_b"},
    ],
}
RESPONSE_OVERRIDES: dict[str, dict[str, Any]] = {
    "beacon_discover": LIST_RESPONSE,
    "beacon_contracts": LIST_RESPONSE,
}

# Keys in JSON bodies whose values change per call.
VOLATILE_JSON_KEYS = {"nonce", "ts"}


class FakeResponse:
    def __init__(self, spec: dict[str, Any]):
        self.status_code = spec.get("status", 200)
        self._body = spec.get("body", {})
        self.text = json.dumps(self._body) if not isinstance(self._body, str) else self._body

    def json(self):
        if isinstance(self._body, str):
            # Same exception family httpx raises for a non-JSON body.
            raise json.JSONDecodeError("not JSON", self._body, 0)
        # Tools mutate the dict they get back (setdefault, nested assignment);
        # hand out a copy so the fixture's canned body is never altered.
        return copy.deepcopy(self._body)

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=None
            )


class RecordingClient:
    def __init__(self, responses: list[dict[str, Any]]):
        self._responses = responses
        self.recorded: list[dict[str, Any]] = []

    def _record(self, method: str, url: str, kwargs: dict[str, Any]) -> FakeResponse:
        entry: dict[str, Any] = {"method": method, "url": url}
        for key in ("params", "json", "headers"):
            if key in kwargs and kwargs[key] not in (None, {}):
                entry[key] = kwargs[key]
        self.recorded.append(entry)
        index = min(len(self.recorded) - 1, len(self._responses) - 1)
        return FakeResponse(self._responses[index])

    def get(self, url: str, **kwargs):
        return self._record("GET", url, kwargs)

    def post(self, url: str, **kwargs):
        return self._record("POST", url, kwargs)


def _normalize(entry: dict[str, Any]) -> dict[str, Any]:
    """Replace volatile values with the ANY sentinel so fixtures are stable."""
    out = json.loads(json.dumps(entry))
    body = out.get("json")
    if isinstance(body, dict):
        for key in VOLATILE_JSON_KEYS:
            if key in body:
                body[key] = ANY
    return out


def _matches(expected: Any, actual: Any) -> bool:
    if expected == ANY:
        return True
    if isinstance(expected, dict) and isinstance(actual, dict):
        return expected.keys() == actual.keys() and all(
            _matches(expected[k], actual[k]) for k in expected
        )
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(
            _matches(e, a) for e, a in zip(expected, actual)
        )
    return expected == actual


def _load_fixtures() -> dict[str, Any]:
    if not FIXTURE_PATH.exists():
        return {}
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _run_tool(name: str, args: dict[str, Any], responses: list[dict[str, Any]]):
    client = RecordingClient(responses)
    patches = [
        mock.patch.object(server, key, value) for key, value in BASES.items()
    ]
    patches.append(mock.patch.object(server, "get_client", return_value=client))
    # Keep the keystore out of it: tools that accept a wallet_id fall back to
    # treating it as an address when no local wallet exists.
    patches.append(mock.patch.object(server.rustchain_crypto, "load_wallet", return_value=None))
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        getattr(server, name)(**args)
    return [_normalize(e) for e in client.recorded]


# Default canned response: generous enough for every tool to run to the end
# of its request sequence without raising.
DEFAULT_RESPONSE = {
    "status": 200,
    "body": {
        "ok": True, "amount_rtc": 5.0, "miner_id": "x", "miners": [],
        "items": [], "agents": [], "relay": True, "version": "fixture",
    },
}


@pytest.mark.parametrize("tool_name", sorted(CASES))
def test_tool_builds_expected_requests(tool_name):
    fixtures = _load_fixtures()
    args = CASES[tool_name]
    case = fixtures.get(tool_name, {})
    responses = (
        case.get("responses")
        or RESPONSE_OVERRIDES.get(tool_name)
        or [DEFAULT_RESPONSE]
    )
    if isinstance(responses, dict):
        responses = [responses]

    recorded = _run_tool(tool_name, args, responses)
    assert recorded, f"{tool_name} made no HTTP requests"

    if UPDATE:
        fixtures[tool_name] = {"args": args, "responses": responses, "requests": recorded}
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_text(
            json.dumps(dict(sorted(fixtures.items())), indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        return

    assert tool_name in fixtures, (
        f"no fixture for {tool_name}; run with RUSTCHAIN_MCP_UPDATE_FIXTURES=1"
    )
    expected = fixtures[tool_name]["requests"]
    assert fixtures[tool_name]["args"] == args, "fixture args drifted from CASES"
    assert _matches(expected, recorded), (
        f"{tool_name} request drift\nexpected: {json.dumps(expected, indent=1)}\n"
        f"actual:   {json.dumps(recorded, indent=1)}"
    )


def test_every_network_tool_has_a_case():
    """New network tools must be added to CASES (and the fixture)."""
    import asyncio

    async def _names():
        from fastmcp import Client

        async with Client(server.mcp) as client:
            return {t.name for t in await client.list_tools()}

    registered = asyncio.run(_names())
    local_only = {
        "wallet_create", "wallet_list", "wallet_export", "wallet_import",
        "wallet_transfer_signed",  # needs a keystore; see test_transfer_signed_message_format
        "rustchain_events",        # event relay; see test_event_relay
        "network_health",          # dynamic node list; see test_ecosystem_tools
        "legend_of_elya_info",     # static info + optional GitHub call
        "bottube_upload",          # multipart file upload; see test_bottube_upload
    }
    missing = registered - local_only - set(CASES)
    assert not missing, f"network tools without a request fixture: {sorted(missing)}"


def test_fixture_urls_use_configured_bases():
    """Every recorded URL is built from a configurable base or an allowlisted host."""
    fixtures = _load_fixtures()
    allowed_hosts = tuple(BASES.values()) + ("https://api.github.com", "https://rustchain.org/preserved.html")
    for tool_name, case in fixtures.items():
        for req in case["requests"]:
            assert req["url"].startswith(allowed_hosts), f"{tool_name}: {req['url']}"
