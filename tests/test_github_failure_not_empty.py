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


# --- Review fixes (codex / grok / astra) -------------------------------------


def test_bounty_search_incomplete_results_is_not_complete():
    def handler(request):
        return httpx.Response(200, json={
            "total_count": 31, "incomplete_results": True, "items": [],
        })

    result = _run(server.bounty_search, handler)

    assert result["complete"] is False
    assert result["truncated"] == [{
        "repo": server.BOUNTIES_REPO, "total_count": 31, "returned": 0,
        "incomplete_results": True,
    }]


def test_bounty_search_more_matches_than_one_page_is_not_complete():
    items = [
        {"title": f"B{i} - 5 RTC", "number": i, "labels": [], "html_url": "u"}
        for i in range(30)
    ]

    def handler(request):
        return httpx.Response(200, json={
            "total_count": 45, "incomplete_results": False, "items": items,
        })

    result = _run(server.bounty_search, handler)

    assert result["total"] == 30
    assert result["complete"] is False
    assert result["truncated"][0]["total_count"] == 45


def test_bounty_search_full_page_with_matching_total_is_complete():
    def handler(request):
        return httpx.Response(200, json={
            "total_count": 1, "incomplete_results": False,
            "items": [{"title": "B - 5 RTC", "number": 1, "labels": [], "html_url": "u"}],
        })

    result = _run(server.bounty_search, handler)

    assert result["complete"] is True
    assert "truncated" not in result


def test_contributor_lookup_merged_prs_truncated_is_not_complete():
    def handler(request):
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={
                "total_count": 25, "incomplete_results": False,
                "items": [{"title": "p", "html_url": "u", "closed_at": ""}] * 20,
            })
        return httpx.Response(200, json={"amount_rtc": 0, "miner_id": "x"})

    result = _run(server.contributor_lookup, handler, "someone")

    assert result["merged_prs"]["complete"] is False
    assert result["merged_prs"]["truncated"]


def test_contributor_lookup_partial_node_failure_is_not_no_wallet():
    # One candidate 503s while the others return zero: the failed one may
    # hold the balance, so "No RTC wallet found" would be a false negative.
    def handler(request):
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={"items": []})
        if request.url.params["miner_id"] == "Alice":
            return httpx.Response(503, json={"error": "maintenance"})
        return httpx.Response(200, json={"amount_rtc": 0, "miner_id": "x"})

    result = _run(server.contributor_lookup, handler, "Alice")

    assert result["rtc_balance"] is None
    assert "No RTC wallet found" not in result["note"]
    assert "lookup failed for: Alice" in result["note"]
    assert result["balance_complete"] is False
    assert result["balance_errors"] == [{"wallet_id": "Alice", "error": "NODE_UNAVAILABLE"}]


def test_contributor_lookup_invalid_wallet_id_is_not_a_node_outage():
    # The node answers 400 "invalid miner_id" for IDs outside
    # ^[A-Za-z0-9._:-]{1,80}$ such as GitHub bot logins.
    def handler(request):
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={"items": []})
        return httpx.Response(400, json={"ok": False, "error": "invalid miner_id"})

    result = _run(server.contributor_lookup, handler, "dependabot[bot]")

    assert result["rtc_balance"] is None
    assert "lookup failed" not in result["note"]
    assert "not a valid RustChain wallet ID" in result["note"]
    assert "balance_errors" not in result
    assert result["balance_complete"] is True
    assert "dependabot[bot]" in result["invalid_wallet_ids"]


def test_balance_400_is_invalid_identifier_not_node_unavailable():
    def handler(request):
        return httpx.Response(400, json={"ok": False, "error": "invalid miner_id"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with mock.patch.object(server, "RUSTCHAIN_NODE", "https://node.test"):
        result = server._get_rustchain_balance("bad id!", client)

    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_IDENTIFIER"
    assert result["error"]["retryable"] is False
