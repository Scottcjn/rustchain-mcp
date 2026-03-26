"""
Unit tests for the 5 new ecosystem & discovery MCP tools.

Tests for:
- legend_of_elya_info
- bounty_search
- contributor_lookup
- network_health
- green_tracker
"""

from __future__ import annotations

import re
from typing import Any
from unittest import mock

import pytest

from rustchain_mcp import server


# ═══════════════════════════════════════════════════════════════
# Test Helpers
# ═══════════════════════════════════════════════════════════════

class FakeResponse:
    """Minimal httpx.Response stand-in."""

    def __init__(self, status_code: int = 200, payload: Any = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = str(self._payload)

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class FakeClient:
    """Fake httpx.Client that returns canned responses based on URL patterns."""

    def __init__(self, routes: dict[str, FakeResponse] | None = None):
        self._routes = routes or {}
        self._default = FakeResponse(500, {"error": "no route configured"})

    def get(self, url: str, **kwargs) -> FakeResponse:
        for pattern, resp in self._routes.items():
            if pattern in url:
                return resp
        return self._default

    def post(self, url: str, **kwargs) -> FakeResponse:
        for pattern, resp in self._routes.items():
            if pattern in url:
                return resp
        return self._default


@pytest.fixture(autouse=True)
def _reset_client():
    """Reset the shared HTTP client before each test."""
    server._client = None
    yield
    server._client = None


def _patch_client(routes: dict[str, FakeResponse]):
    """Return a mock.patch that replaces get_client with a FakeClient."""
    fake = FakeClient(routes)
    return mock.patch.object(server, "get_client", return_value=fake)


# ═══════════════════════════════════════════════════════════════
# Test: legend_of_elya_info
# ═══════════════════════════════════════════════════════════════

class TestLegendOfElyaInfo:
    """Tests for legend_of_elya_info tool."""

    def test_returns_project_metadata(self):
        """Tool returns core project info even when GitHub API is unreachable."""
        with _patch_client({}):
            result = server.legend_of_elya_info()

        assert result["project"] == "The Legend of Elya"
        assert "github" in result
        assert "architecture" in result
        assert "bounties" in result

    def test_architecture_has_engine_and_llm(self):
        with _patch_client({}):
            result = server.legend_of_elya_info()

        arch = result["architecture"]
        assert "Godot" in arch["engine"]
        assert "llama.cpp" in arch["llm_backend"]

    def test_includes_live_stars_when_api_available(self):
        gh_response = FakeResponse(200, {
            "stargazers_count": 55,
            "forks_count": 12,
            "open_issues_count": 7,
        })
        with _patch_client({"api.github.com/repos/Scottcjn/legend-of-elya": gh_response}):
            result = server.legend_of_elya_info()

        assert result["github_stars"] == 55
        assert result["github_forks"] == 12
        assert result["open_issues"] == 7

    def test_falls_back_when_github_api_fails(self):
        with _patch_client({"api.github.com": FakeResponse(403, {})}):
            result = server.legend_of_elya_info()

        # Should still return valid data with fallback star count
        assert result["project"] == "The Legend of Elya"
        assert "github_stars" in result

    def test_related_projects_listed(self):
        with _patch_client({}):
            result = server.legend_of_elya_info()

        related = result["related_projects"]
        assert any("edge-node" in p for p in related)
        assert any("grail-v" in p for p in related)


# ═══════════════════════════════════════════════════════════════
# Test: bounty_search
# ═══════════════════════════════════════════════════════════════

class TestBountySearch:
    """Tests for bounty_search tool."""

    def _github_search_response(self, items: list[dict]) -> FakeResponse:
        return FakeResponse(200, {"items": items, "total_count": len(items)})

    def _make_issue(self, title: str, number: int, labels: list[str] | None = None):
        return {
            "title": title,
            "html_url": f"https://github.com/Scottcjn/Rustchain/issues/{number}",
            "number": number,
            "labels": [{"name": lb} for lb in (labels or ["bounty"])],
            "body": "",
            "created_at": "2026-03-20T12:00:00Z",
            "comments": 3,
        }

    def test_returns_bounties_from_github(self):
        items = [
            self._make_issue("Fix miner crash — 50 RTC", 100),
            self._make_issue("Add SPARC port — 200 RTC", 101),
        ]
        with _patch_client({"api.github.com/search/issues": self._github_search_response(items)}):
            result = server.bounty_search()

        assert result["total"] == 2
        assert result["bounties"][0]["title"] == "Fix miner crash — 50 RTC"
        assert result["bounties"][0]["rtc_reward"] == 50.0
        assert result["bounties"][1]["rtc_reward"] == 200.0

    def test_min_rtc_filter(self):
        items = [
            self._make_issue("Small task — 10 RTC", 200),
            self._make_issue("Big task — 300 RTC", 201),
        ]
        with _patch_client({"api.github.com/search/issues": self._github_search_response(items)}):
            result = server.bounty_search(min_rtc=100)

        assert result["total"] == 1
        assert result["bounties"][0]["rtc_reward"] == 300.0

    def test_max_rtc_filter(self):
        items = [
            self._make_issue("Small task — 10 RTC", 200),
            self._make_issue("Big task — 300 RTC", 201),
        ]
        with _patch_client({"api.github.com/search/issues": self._github_search_response(items)}):
            result = server.bounty_search(max_rtc=50)

        assert result["total"] == 1
        assert result["bounties"][0]["rtc_reward"] == 10.0

    def test_empty_results(self):
        with _patch_client({"api.github.com/search/issues": self._github_search_response([])}):
            result = server.bounty_search(keyword="nonexistent")

        assert result["total"] == 0
        assert result["bounties"] == []

    def test_github_api_failure_returns_empty(self):
        with _patch_client({"api.github.com": FakeResponse(500, {})}):
            result = server.bounty_search()

        assert result["total"] == 0

    def test_tip_always_present(self):
        with _patch_client({"api.github.com/search/issues": self._github_search_response([])}):
            result = server.bounty_search()

        assert "tip" in result
        assert "claim" in result["tip"].lower() or "PR" in result["tip"]


# ═══════════════════════════════════════════════════════════════
# Test: _extract_rtc_amount helper
# ═══════════════════════════════════════════════════════════════

class TestExtractRtcAmount:
    """Tests for the _extract_rtc_amount helper."""

    def test_extracts_from_title(self):
        assert server._extract_rtc_amount("Fix bug — 100 RTC") == 100.0

    def test_extracts_no_space(self):
        assert server._extract_rtc_amount("50RTC bounty") == 50.0

    def test_extracts_decimal(self):
        assert server._extract_rtc_amount("Reward: 12.5 RTC") == 12.5

    def test_case_insensitive(self):
        assert server._extract_rtc_amount("75 rtc reward") == 75.0

    def test_prefers_title_over_body(self):
        assert server._extract_rtc_amount("100 RTC", "200 RTC in body") == 100.0

    def test_falls_back_to_body(self):
        assert server._extract_rtc_amount("No amount here", "Reward: 50 RTC") == 50.0

    def test_returns_zero_when_not_found(self):
        assert server._extract_rtc_amount("No reward mentioned") == 0.0


# ═══════════════════════════════════════════════════════════════
# Test: contributor_lookup
# ═══════════════════════════════════════════════════════════════

class TestContributorLookup:
    """Tests for contributor_lookup tool."""

    def test_returns_merged_prs(self):
        items = [
            {"title": "Fix epoch calc", "html_url": "https://...", "closed_at": "2026-03-15"},
            {"title": "Add tests", "html_url": "https://...", "closed_at": "2026-03-10"},
        ]
        routes = {
            "api.github.com/search/issues": FakeResponse(200, {"items": items}),
            "/balance": FakeResponse(200, {"balance_rtc": 0}),
        }
        with _patch_client(routes):
            result = server.contributor_lookup("testuser")

        assert result["username"] == "testuser"
        assert result["merged_prs"]["total"] >= 2  # May double-count across repos
        assert result["github_profile"] == "https://github.com/testuser"

    def test_finds_rtc_balance_by_username(self):
        routes = {
            "api.github.com/search/issues": FakeResponse(200, {"items": []}),
            "/balance": FakeResponse(200, {"balance_rtc": 42.5, "amount_i64": 42500000}),
        }
        with _patch_client(routes):
            result = server.contributor_lookup("createkr")

        assert result["rtc_balance"] is not None
        assert result["rtc_balance"]["balance_rtc"] == 42.5

    def test_no_wallet_found(self):
        routes = {
            "api.github.com/search/issues": FakeResponse(200, {"items": []}),
            "/balance": FakeResponse(200, {"balance_rtc": 0, "amount_i64": 0}),
        }
        with _patch_client(routes):
            result = server.contributor_lookup("newcontributor")

        assert result["rtc_balance"] is None
        assert "note" in result

    def test_github_api_failure_still_returns_profile(self):
        with _patch_client({}):
            result = server.contributor_lookup("someuser")

        assert result["username"] == "someuser"
        assert result["github_profile"] == "https://github.com/someuser"
        assert result["merged_prs"]["total"] == 0


# ═══════════════════════════════════════════════════════════════
# Test: network_health
# ═══════════════════════════════════════════════════════════════

class TestNetworkHealth:
    """Tests for network_health tool."""

    def test_all_nodes_healthy(self):
        healthy = FakeResponse(200, {
            "ok": True, "version": "2.2.1-rip200",
            "uptime_s": 3600, "db_rw": True, "tip_age_slots": 0,
        })
        with _patch_client({"/health": healthy}):
            result = server.network_health()

        assert result["summary"]["total_nodes"] == 4
        assert result["summary"]["healthy"] == 4
        assert result["summary"]["network_ok"] is True
        assert len(result["nodes"]) == 4
        for node in result["nodes"]:
            assert node["healthy"] is True

    def test_partial_failure(self):
        """Network is still OK with 2+ nodes healthy (majority quorum)."""
        call_count = {"n": 0}
        healthy = FakeResponse(200, {"ok": True, "version": "2.2.1-rip200", "uptime_s": 100, "db_rw": True, "tip_age_slots": 0})

        class PartialClient:
            def get(self, url, **kw):
                call_count["n"] += 1
                # First 2 succeed, last 2 fail
                if call_count["n"] <= 2:
                    return healthy
                raise ConnectionError("unreachable")

        with mock.patch.object(server, "get_client", return_value=PartialClient()):
            result = server.network_health()

        assert result["summary"]["healthy"] == 2
        assert result["summary"]["degraded"] == 2
        assert result["summary"]["network_ok"] is True

    def test_all_nodes_down(self):
        class DeadClient:
            def get(self, url, **kw):
                raise ConnectionError("network down")

        with mock.patch.object(server, "get_client", return_value=DeadClient()):
            result = server.network_health()

        assert result["summary"]["healthy"] == 0
        assert result["summary"]["network_ok"] is False
        for node in result["nodes"]:
            assert node["healthy"] is False
            assert "error" in node

    def test_node_returns_non_200(self):
        with _patch_client({"/health": FakeResponse(503, {})}):
            result = server.network_health()

        for node in result["nodes"]:
            assert node["healthy"] is False

    def test_node_urls_present(self):
        with _patch_client({"/health": FakeResponse(200, {"ok": True, "version": "2.2.1", "uptime_s": 0, "db_rw": True, "tip_age_slots": 0})}):
            result = server.network_health()

        urls = [n["url"] for n in result["nodes"]]
        assert any("50.28.86.131" in u for u in urls)
        assert any("50.28.86.153" in u for u in urls)
        assert any("100.88.109.32" in u for u in urls)
        assert any("38.76.217.189" in u for u in urls)


# ═══════════════════════════════════════════════════════════════
# Test: green_tracker
# ═══════════════════════════════════════════════════════════════

class TestGreenTracker:
    """Tests for green_tracker tool."""

    def test_returns_fallback_fleet_when_page_unreachable(self):
        with _patch_client({}):
            result = server.green_tracker()

        assert result["total_preserved"] > 0
        assert len(result["machines"]) > 0
        assert "by_architecture" in result
        assert "mission" in result

    def test_fallback_fleet_has_vintage_machines(self):
        with _patch_client({}):
            result = server.green_tracker()

        names = [m["name"] for m in result["machines"]]
        # Should include PowerPC, POWER8, and vintage x86
        assert any("G4" in n for n in names)
        assert any("G5" in n for n in names)
        assert any("POWER8" in n for n in names)

    def test_architecture_breakdown(self):
        with _patch_client({}):
            result = server.green_tracker()

        archs = result["by_architecture"]
        assert "PowerPC G4" in archs
        assert archs["PowerPC G4"] >= 2  # Multiple G4 machines

    def test_parses_html_table(self):
        html = """
        <table>
        <tr><td>Machine</td><td>Arch</td><td>Status</td></tr>
        <tr><td>Test G4</td><td>PowerPC</td><td>active</td></tr>
        <tr><td>Test SPARC</td><td>SPARC</td><td>reserve</td></tr>
        </table>
        """
        with _patch_client({"preserved.html": FakeResponse(200, html)}):
            # Need to make .text work on our FakeResponse
            pass

        # Test the parser directly
        machines = server._parse_preserved_html(html)
        assert len(machines) == 2
        assert machines[0]["name"] == "Test G4"
        assert machines[0]["architecture"] == "PowerPC"
        assert machines[1]["name"] == "Test SPARC"

    def test_parse_html_skips_header_row(self):
        html = '<tr><td>Machine</td><td>Arch</td><td>Status</td></tr>'
        machines = server._parse_preserved_html(html)
        assert len(machines) == 0

    def test_source_url_present(self):
        with _patch_client({}):
            result = server.green_tracker()

        assert "rustchain.org/preserved.html" in result["source"]
