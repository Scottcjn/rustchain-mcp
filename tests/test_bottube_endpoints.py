"""Lock the BoTTube tool endpoints to the LIVE API paths (verified 2026-06-26).

These guard against regressing back to the dead /api/v1/videos/* paths, and assert
the write tools send the X-API-Key header BoTTube requires (not Authorization: Bearer).
"""
import pytest

import rustchain_mcp.server as srv


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


class _Recorder:
    """Stand-in httpx client that records calls and returns a canned response."""
    def __init__(self, payload=None):
        self.calls = []
        self.payload = payload if payload is not None else {"videos": []}

    def get(self, url, params=None, headers=None, **kw):
        self.calls.append(("GET", url, params or {}, headers or {}))
        return _Resp(self.payload)

    def post(self, url, json=None, headers=None, **kw):
        self.calls.append(("POST", url, json or {}, headers or {}))
        return _Resp(self.payload)


@pytest.fixture
def rec(monkeypatch):
    r = _Recorder()
    monkeypatch.setattr(srv, "_client", r)        # get_client() returns the cached client
    return r


def _last(rec):
    return rec.calls[-1]


def test_search_hits_live_path(rec):
    srv.bottube_search("ai", page=2)
    m, url, params, _ = _last(rec)
    assert m == "GET" and url.endswith("/api/search")
    assert params == {"q": "ai", "page": 2}
    assert "/api/v1/" not in url


def test_trending_hits_live_path(rec):
    srv.bottube_trending(5)
    m, url, params, _ = _last(rec)
    assert m == "GET" and url.endswith("/api/trending") and params["limit"] == 5


def test_agent_profile_hits_live_path(rec):
    srv.bottube_agent_profile("sophia-elya")
    _, url, _, _ = _last(rec)
    assert url.endswith("/api/agents/sophia-elya") and "/api/v1/" not in url


def test_upload_path_and_xapikey_header(rec):
    srv.bottube_upload("t", "http://v", api_key="secret")
    m, url, _, headers = _last(rec)
    assert m == "POST" and url.endswith("/api/upload")
    assert headers.get("X-API-Key") == "secret" and "Authorization" not in headers


def test_comment_singular_path_and_xapikey(rec):
    srv.bottube_comment("vid123", "nice", api_key="secret")
    m, url, _, headers = _last(rec)
    assert m == "POST" and url.endswith("/api/videos/vid123/comment")   # singular
    assert headers.get("X-API-Key") == "secret"


def test_vote_path_and_xapikey(rec):
    srv.bottube_vote("vid123", "up", api_key="secret")
    m, url, _, headers = _last(rec)
    assert m == "POST" and url.endswith("/api/videos/vid123/vote")
    assert headers.get("X-API-Key") == "secret"


def test_no_dead_v1_paths_anywhere(rec):
    """Exercise every read tool; none may target the dead /api/v1/* namespace."""
    srv.bottube_search("x")
    srv.bottube_trending()
    srv.bottube_agent_profile("a")
    assert all("/api/v1/" not in url for _, url, _, _ in rec.calls)


# --- RustChain balance endpoint lock: canonical /wallet/balance?miner_id=... ---
def test_rustchain_balance_uses_canonical_query_endpoint(rec):
    srv.rustchain_balance("sophia-elya")
    m, url, params, _ = _last(rec)
    assert m == "GET" and url.endswith("/wallet/balance")
    assert params == {"miner_id": "sophia-elya"} and "?" not in url


def test_wallet_balance_uses_canonical_query_endpoint(rec):
    srv.wallet_balance("dual-g4-125")
    _, url, params, _ = _last(rec)
    assert url.endswith("/wallet/balance")
    assert params == {"miner_id": "dual-g4-125"}


def test_balance_requires_amount_rtc_from_canonical_response(monkeypatch):
    recorder = _Recorder({"amount_rtc": 12.5, "miner_id": "miner-a"})
    monkeypatch.setattr(srv, "_client", recorder)

    result = srv.rustchain_balance("miner-a")

    assert result["amount_rtc"] == 12.5
    assert result["balance"] == 12.5
    assert result["balance_rtc"] == 12.5
    assert result["miner_id"] == "miner-a"
    assert result["wallet_id"] == "miner-a"
    assert _last(recorder)[2] == {"miner_id": "miner-a"}


def test_balance_does_not_turn_missing_amount_into_zero(monkeypatch):
    recorder = _Recorder({"balance": 0})
    monkeypatch.setattr(srv, "_client", recorder)

    result = srv.rustchain_balance("miner-a")

    assert result["ok"] is False
    assert result["error"]["code"] == "MISSING_EXPECTED_FIELD"


def test_rustchain_miners_requests_bounded_page_and_preserves_node_total(monkeypatch):
    recorder = _Recorder(
        {
            "miners": [{"miner_id": "a"}, {"miner_id": "b"}],
            "pagination": {"limit": 20, "offset": 0, "total": 91},
        }
    )
    monkeypatch.setattr(srv, "_client", recorder)

    result = srv.rustchain_miners()

    method, url, params, _ = _last(recorder)
    assert method == "GET" and url.endswith("/api/miners")
    assert params == {"limit": 20, "offset": 0}
    assert result["page_count"] == 2
    assert result["total_miners"] == 91
    assert result["total_known"] is True
    assert result["pagination"]["total"] == 91


def test_rustchain_miners_does_not_infer_global_total_from_page(monkeypatch):
    recorder = _Recorder({"miners": [{"miner_id": "only-page-item"}]})
    monkeypatch.setattr(srv, "_client", recorder)

    result = srv.rustchain_miners()

    assert result["page_count"] == 1
    assert result["total_known"] is False
    assert "total_miners" not in result


def test_gas_tools_removed():
    # the relay has no gas routes — these dead tools must not exist
    assert not hasattr(srv, "beacon_gas_balance") and not hasattr(srv, "beacon_gas_deposit")
