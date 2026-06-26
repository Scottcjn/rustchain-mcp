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
