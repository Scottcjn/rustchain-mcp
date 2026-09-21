"""The out-of-the-box node URL must work with TLS verification enabled.

The node's certificate is issued for a hostname, so a bare-IP default
(``https://50.28.86.131``) failed certificate verification on every RustChain
tool for a fresh install. The default is now the public hostname, and
``rustchain_stats`` copes with the one endpoint that hostname does not proxy.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from rustchain_mcp import events, server

PUBLIC_DEFAULT = "https://rustchain.org"


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class RoutedClient:
    """Return canned responses by URL suffix and record every URL requested."""

    def __init__(self, routes: dict[str, FakeResponse]):
        self.routes = routes
        self.requested: list[str] = []

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.requested.append(url)
        for suffix, response in self.routes.items():
            if url.endswith(suffix):
                return response
        return FakeResponse(500, {"error": "no route"})


@pytest.fixture(autouse=True)
def _reset_client():
    server._client = None
    yield
    server._client = None


# ── Defaults ───────────────────────────────────────────────────────


def test_server_default_node_is_public_hostname():
    # The module reads the env var once at import. Reloading the module would
    # swap the FastMCP instance other tests hold, so skip if the env overrides it.
    if "RUSTCHAIN_NODE" in os.environ:
        pytest.skip("RUSTCHAIN_NODE is set in this environment")
    assert server.RUSTCHAIN_NODE == PUBLIC_DEFAULT


def test_event_relay_default_node_matches_server_default():
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("RUSTCHAIN_NODE", None)
        config = events.EventRelayConfig.from_env()
    assert config.node_url == PUBLIC_DEFAULT
    assert events.EventRelayConfig.node_url == PUBLIC_DEFAULT


def test_event_relay_env_override_still_wins():
    with mock.patch.dict(os.environ, {"RUSTCHAIN_NODE": "https://node.example.test"}):
        config = events.EventRelayConfig.from_env()
    assert config.node_url == "https://node.example.test"


def test_default_is_not_a_bare_ip_literal():
    """A bare IP cannot match a hostname certificate; never ship one as default."""
    for url in (PUBLIC_DEFAULT, events.EventRelayConfig.node_url):
        host = url.split("//", 1)[1].split("/", 1)[0].split(":", 1)[0]
        assert not host.replace(".", "").isdigit(), url


# ── rustchain_stats fallback ───────────────────────────────────────


def test_stats_uses_api_stats_when_available():
    client = RoutedClient({
        "/api/stats": FakeResponse(200, {"total_miners": 1768, "epoch": 292}),
    })
    with mock.patch.object(server, "get_client", return_value=client):
        result = server.rustchain_stats()

    assert result["total_miners"] == 1768
    assert result["source"] == "/api/stats"
    assert client.requested == [f"{server.RUSTCHAIN_NODE}/api/stats"]


def test_stats_composes_from_epoch_and_health_on_404():
    """rustchain.org does not proxy /api/stats; the tool must still answer."""
    client = RoutedClient({
        "/api/stats": FakeResponse(404, "<html>404</html>"),
        "/epoch": FakeResponse(200, {
            "epoch": 292, "slot": 42172, "enrolled_miners": 14,
            "epoch_pot": 1.5, "blocks_per_epoch": 144,
            "total_supply_rtc": 8388608,
        }),
        "/health": FakeResponse(200, {
            "ok": True, "version": "2.2.1-rip200", "tip_age_slots": 0,
        }),
    })
    with mock.patch.object(server, "get_client", return_value=client):
        result = server.rustchain_stats()

    assert result["source"] == "composed"
    assert result["epoch"] == 292
    assert result["enrolled_miners"] == 14
    assert result["total_supply_rtc"] == 8388608
    assert result["node_ok"] is True
    assert result["node_version"] == "2.2.1-rip200"
    assert [u.rsplit("/", 1)[-1] for u in client.requested] == ["stats", "epoch", "health"]


def test_stats_other_errors_still_raise():
    client = RoutedClient({"/api/stats": FakeResponse(503, {"error": "down"})})
    with mock.patch.object(server, "get_client", return_value=client), pytest.raises(Exception, match="HTTP 503"):
        server.rustchain_stats()
    assert len(client.requested) == 1
