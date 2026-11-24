# SPDX-License-Identifier: MIT
"""Regression tests for rustchain_langchain and rustchain_crewai live endpoints and guards."""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import Mock, patch

import pytest


def _raw(tool_obj):
    return getattr(tool_obj, "func", tool_obj)


def _ensure_requests_stub(monkeypatch):
    try:
        import requests  # noqa: F401
    except ImportError:
        requests_mod = types.ModuleType("requests")
        exc_mod = types.ModuleType("requests.exceptions")
        exc_mod.RequestException = type("RequestException", (Exception,), {})
        requests_mod.exceptions = exc_mod
        requests_mod.get = lambda *a, **kw: None
        requests_mod.post = lambda *a, **kw: None
        monkeypatch.setitem(sys.modules, "requests", requests_mod)
        monkeypatch.setitem(sys.modules, "requests.exceptions", exc_mod)


@pytest.fixture
def lc_module(monkeypatch):
    saved = {
        k: sys.modules.get(k)
        for k in ("requests", "requests.exceptions", "rustchain_langchain", "rustchain_langchain.tools")
    }
    try:
        _ensure_requests_stub(monkeypatch)
        sys.modules.pop("rustchain_langchain.tools", None)
        sys.modules.pop("rustchain_langchain", None)
        yield importlib.import_module("rustchain_langchain.tools")
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


@pytest.fixture
def crewai_module(monkeypatch):
    saved = {
        k: sys.modules.get(k)
        for k in ("requests", "requests.exceptions", "crewai", "crewai.tools", "rustchain_crewai")
    }
    try:
        _ensure_requests_stub(monkeypatch)
        try:
            import crewai.tools  # noqa: F401
        except ImportError:
            from pydantic import BaseModel

            crewai = types.ModuleType("crewai")
            crewai_tools = types.ModuleType("crewai.tools")
            crewai_tools.BaseTool = type("BaseTool", (BaseModel,), {})
            crewai.tools = crewai_tools
            monkeypatch.setitem(sys.modules, "crewai", crewai)
            monkeypatch.setitem(sys.modules, "crewai.tools", crewai_tools)
        sys.modules.pop("rustchain_crewai", None)
        yield importlib.import_module("rustchain_crewai")
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def test_langchain_balance_uses_live_wallet_balance_endpoint_and_amount_rtc(lc_module):
    mock_resp = Mock()
    mock_resp.json.return_value = {
        "amount_i64": 718514429,
        "amount_rtc": 718.514429,
        "miner_id": "dual-g4-125",
    }
    mock_resp.raise_for_status = Mock()

    with patch.object(lc_module.requests, "get", return_value=mock_resp) as mock_get:
        out = _raw(lc_module.rustchain_balance)("dual-g4-125")

    assert mock_get.call_args[0][0].endswith("/wallet/balance")
    assert mock_get.call_args[1]["params"] == {"miner_id": "dual-g4-125"}
    assert "718.514" in out
    assert "RTC" in out


@pytest.mark.parametrize("bad", [None, "bad", True, float("nan"), float("inf")])
def test_langchain_balance_handles_non_numeric_or_bool(lc_module, bad):
    with patch.object(lc_module, "_get", return_value={"amount_rtc": bad}):
        out = _raw(lc_module.rustchain_balance)("w1")
    assert "balance unavailable" in out


def test_langchain_health_bottube_stats_and_beacon_discover_handle_null_fields(lc_module):
    with patch.object(
        lc_module,
        "_get",
        return_value={"ok": True, "version": "2.2", "uptime_s": None, "db_rw": True},
    ):
        health = _raw(lc_module.rustchain_health)()
    assert "0h 0m" in health

    with patch.object(
        lc_module,
        "_get",
        return_value={"videos": 10, "agents": 2, "top_agents": [{"video_count": None}]},
    ):
        stats = _raw(lc_module.bottube_stats)()
    assert "unknown: 0 videos, 0 views" in stats

    with patch.object(
        lc_module,
        "_get",
        return_value=[{"agent_id": "bcn_null", "capabilities": None}],
    ):
        disc = _raw(lc_module.beacon_discover)(capability="coding")
    assert disc == "Beacon agents: 0"


def test_langchain_bottube_upload_sends_multipart_form_data(lc_module, tmp_path, monkeypatch):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    monkeypatch.setenv("BOTTUBE_API_KEY", "test-secret-key")

    mock_resp = Mock()
    mock_resp.json.return_value = {"ok": True, "video_id": "vid_123"}
    mock_resp.raise_for_status = Mock()

    with patch.object(lc_module.requests, "post", return_value=mock_resp) as mock_post:
        out = _raw(lc_module.bottube_upload)(
            title="Demo Clip",
            description="Multipart test",
            tags="ai,demo",
            video_path=str(video),
        )

    assert "vid_123" in out
    assert mock_post.call_args[0][0].endswith("/api/upload")
    kwargs = mock_post.call_args[1]
    assert kwargs["headers"] == {"X-API-Key": "test-secret-key"}
    assert kwargs["data"]["title"] == "Demo Clip"
    assert "video" in kwargs["files"]
    assert "json" not in kwargs


def test_langchain_bottube_upload_blocks_private_url_ssrf(lc_module, monkeypatch):
    monkeypatch.setenv("BOTTUBE_API_KEY", "test-secret-key")
    with patch.object(lc_module.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 0))]):
        out = _raw(lc_module.bottube_upload)(title="SSRF", video_url="http://127.0.0.1/secret.mp4")
    assert "non-public IP" in out


def test_crewai_live_endpoints_and_null_guards(crewai_module):
    with patch.object(
        crewai_module,
        "_get",
        return_value={"amount_i64": 718514429, "amount_rtc": 718.514429, "miner_id": "dual-g4-125"},
    ) as mock_get:
        res = crewai_module.RustChainCheckBalance()._run("dual-g4-125")
    assert mock_get.call_args[0][0].endswith("/wallet/balance")
    assert "718.514" in res

    with patch.object(crewai_module, "_get", return_value={"amount_rtc": None}):
        res_null = crewai_module.RustChainCheckBalance()._run("missing")
    assert "balance unavailable" in res_null

    with patch.object(crewai_module, "_get", return_value={"videos": [{"title": "Clip", "views": 5}]}) as mock_search:
        s_out = crewai_module.RustChainBoTTubeSearch()._run("ai")
    assert mock_search.call_args[0][0].endswith("/api/search")
    assert "Clip" in s_out

    with patch.object(crewai_module, "_get", return_value={"ok": True, "uptime_s": None}):
        h_out = crewai_module.RustChainGetNodeHealth()._run()
    assert "0h 0m" in h_out

    with patch.object(crewai_module, "_get", return_value=[{"agent_id": "bcn_1", "capabilities": None}]):
        d_out = crewai_module.RustChainBeaconDiscover()._run(capability="coding")
    assert d_out == "Beacon agents: 0"
