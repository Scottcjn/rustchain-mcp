"""A failed upstream lookup must not read as an empty/zero result.

bounty_search and contributor_lookup call GitHub's search API, which allows
only ~10 unauthenticated requests per minute and answers HTTP 403 when the
limit is hit. They previously swallowed that and reported "total": 0, and
contributor_lookup reported "No RTC wallet found" when the node lookup itself
failed.
"""

from unittest import mock

import httpx

from rustchain_mcp import server


def _run(fn, handler, *args, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with (
        mock.patch.object(server, "get_client", return_value=client),
        mock.patch.object(server, "RUSTCHAIN_NODE", "https://node.test"),
    ):
        return getattr(fn, "fn", fn)(*args, **kwargs)


def _rate_limited_github(request):
    if request.url.host == "api.github.com":
        return httpx.Response(403, json={"message": "API rate limit exceeded"})
    return httpx.Response(200, json={"amount_rtc": 0, "miner_id": "x"})


def test_bounty_search_rate_limit_is_an_error_not_zero_bounties():
    result = _run(server.bounty_search, _rate_limited_github, repo="all")

    assert result["ok"] is False
    assert result["complete"] is False
    assert "not 'no bounties'" in result["error"]
    assert {e["repo"] for e in result["errors"]} == {
        server.BOUNTIES_REPO, server.BOTTUBE_BOUNTIES_REPO,
    }
    assert "rate limit" in result["errors"][0]["error"]


def test_bounty_search_partial_failure_keeps_results_and_flags_incomplete():
    def handler(request):
        if server.BOTTUBE_BOUNTIES_REPO in request.url.params["q"]:
            return httpx.Response(500)
        return httpx.Response(200, json={"items": [
            {"title": "Fix it - 5 RTC", "number": 1, "labels": [], "html_url": "u"},
        ]})

    result = _run(server.bounty_search, handler, repo="all")

    assert result["total"] == 1
    assert result["complete"] is False
    assert "ok" not in result
    assert result["errors"] == [{"repo": server.BOTTUBE_BOUNTIES_REPO, "error": "HTTP 500"}]


def test_bounty_search_success_is_complete():
    def handler(request):
        return httpx.Response(200, json={"items": []})

    result = _run(server.bounty_search, handler)

    assert result["complete"] is True
    assert "errors" not in result


def test_contributor_lookup_flags_incomplete_pr_count_on_rate_limit():
    result = _run(server.contributor_lookup, _rate_limited_github, "someone")

    assert result["merged_prs"]["total"] == 0
    assert result["merged_prs"]["complete"] is False
    assert len(result["merged_prs"]["errors"]) == 2


def test_contributor_lookup_node_down_is_not_no_wallet():
    def handler(request):
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={"items": []})
        return httpx.Response(503, json={"error": "maintenance"})

    result = _run(server.contributor_lookup, handler, "someone")

    assert result["rtc_balance"] is None
    assert "No RTC wallet found" not in result["note"]
    assert "lookup failed" in result["note"]
    assert result["balance_errors"]


def test_contributor_lookup_zero_balance_still_means_no_wallet():
    def handler(request):
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={"items": []})
        return httpx.Response(200, json={"amount_rtc": 0, "miner_id": "someone"})

    result = _run(server.contributor_lookup, handler, "someone")

    assert result["rtc_balance"] is None
    assert "No RTC wallet found" in result["note"]
    assert result["merged_prs"]["complete"] is True
