# SPDX-License-Identifier: MIT
"""Regression tests for MCP server input validation, BOTTUBE_API_KEY env fallback, and null guards."""

from __future__ import annotations

from unittest import mock

import httpx
import pytest

from rustchain_mcp import server


def _raw(tool_obj):
    return getattr(tool_obj, "fn", tool_obj)


@pytest.mark.parametrize("bad_amount", [0, -5, True, float("nan"), float("inf")])
def test_transfer_tools_reject_invalid_amount_without_http_or_signing(bad_amount):
    client = httpx.Client(transport=httpx.MockTransport(lambda req: pytest.fail("no HTTP expected")))
    with mock.patch.object(server, "get_client", return_value=client):
        r1 = _raw(server.wallet_transfer_signed)(
            from_wallet_id="nonexistent-wallet",
            to_address="RTC" + "a" * 40,
            amount_rtc=bad_amount,
            password="pw",
        )
        r2 = _raw(server.rustchain_transfer_signed)(
            from_address="RTC" + "a" * 40,
            to_address="RTC" + "b" * 40,
            amount_rtc=bad_amount,
            signature="ab" * 64,
            public_key="cd" * 32,
        )
    for res in (r1, r2):
        assert res["success"] is False
        assert res["ok"] is False
        assert res["code"] == "INVALID_ARGUMENT"
        assert res["outcome_unknown"] is False


def test_transfer_tools_reject_blank_addresses_without_http():
    client = httpx.Client(transport=httpx.MockTransport(lambda req: pytest.fail("no HTTP expected")))
    with mock.patch.object(server, "get_client", return_value=client):
        r1 = _raw(server.wallet_transfer_signed)(
            from_wallet_id="w",
            to_address="   ",
            amount_rtc=1.0,
            password="pw",
        )
        r2 = _raw(server.rustchain_transfer_signed)(
            from_address="",
            to_address="RTC" + "b" * 40,
            amount_rtc=1.0,
            signature="ab" * 64,
            public_key="cd" * 32,
        )
    assert r1["code"] == "INVALID_ARGUMENT"
    assert r2["code"] == "INVALID_ARGUMENT"


def test_bottube_comment_and_vote_fall_back_to_env_api_key(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setenv("BOTTUBE_API_KEY", "env-key-123")
    with (
        mock.patch.object(server, "get_client", return_value=client),
        mock.patch.object(server, "BOTTUBE_URL", "https://tube.test"),
    ):
        c_res = _raw(server.bottube_comment)(video_id="vid1", content="hello", api_key="")
        v_res = _raw(server.bottube_vote)(video_id="vid1", direction="up", api_key="")

    assert c_res["ok"] is True
    assert v_res["ok"] is True
    assert seen[0].headers["x-api-key"] == "env-key-123"
    assert seen[1].headers["x-api-key"] == "env-key-123"


def test_bottube_comment_and_vote_fail_closed_when_key_missing(monkeypatch):
    monkeypatch.delenv("BOTTUBE_API_KEY", raising=False)
    client = httpx.Client(transport=httpx.MockTransport(lambda req: pytest.fail("no HTTP expected")))
    with mock.patch.object(server, "get_client", return_value=client):
        c_res = _raw(server.bottube_comment)(video_id="vid1", content="hello", api_key="")
        v_res = _raw(server.bottube_vote)(video_id="vid1", direction="up", api_key="")

    assert c_res["ok"] is False and c_res["code"] == "API_KEY_REQUIRED"
    assert v_res["ok"] is False and v_res["code"] == "API_KEY_REQUIRED"


def test_beacon_endpoints_handle_wrapped_dicts_and_null_fields():
    def handler(request):
        if request.url.path == "/beacon/relay/status/bcn_native":
            return httpx.Response(404, json={"error": "not relay"})
        if request.url.path == "/beacon/api/agents":
            return httpx.Response(
                200,
                json={
                    "agents": [
                        {
                            "agent_id": "bcn_native",
                            "provider": "elyan",
                            "provider_name": None,
                            "capabilities": None,
                        },
                        "corrupt-entry",
                    ]
                },
            )
        if request.url.path == "/beacon/api/contracts":
            return httpx.Response(
                200,
                json={"contracts": [{"from": "bcn_a", "to": "bcn_b"}, "bad"]},
            )
        return httpx.Response(404, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with (
        mock.patch.object(server, "get_client", return_value=client),
        mock.patch.object(server, "BEACON_URL", "https://beacon.test/beacon"),
    ):
        disc = _raw(server.beacon_discover)(provider="anthropic", capability="coding")
        status = _raw(server.beacon_agent_status)(agent_id="bcn_native")
        contracts = _raw(server.beacon_contracts)(agent_id="bcn_a")

    assert disc["total"] == 0
    assert status["agent_id"] == "bcn_native"
    assert contracts["total"] == 1
