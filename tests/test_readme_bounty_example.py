"""The README bounty example must run against bounty_search's real output.

The example previously read ``bounty['reward']`` (and a proposed fix used
``bounty['reward_rtc']``); bounty_search returns the amount under
``rtc_reward``. This test executes the documented snippet verbatim with the
real tool and a mocked GitHub search API, so a key or shape drift in either
the docs or the tool fails CI.
"""

from __future__ import annotations

import pathlib
import re

import httpx
import pytest

from rustchain_mcp import server

README = pathlib.Path(__file__).resolve().parent.parent / "README.md"

GITHUB_ITEMS = [
    {
        "title": "[BOUNTY] Harden epoch settlement (150 RTC)",
        "html_url": "https://github.com/Scottcjn/Rustchain/issues/1",
        "number": 1,
        "body": "",
        "labels": [{"name": "bounty"}],
        "created_at": "2026-09-01T00:00:00Z",
        "comments": 2,
    },
    {
        "title": "[BOUNTY] Fix a typo",
        "html_url": "https://github.com/Scottcjn/Rustchain/issues/2",
        "number": 2,
        "body": "Reward: 5 RTC",
        "labels": [{"name": "bounty"}],
        "created_at": "2026-09-02T00:00:00Z",
        "comments": 0,
    },
]


def _readme_block(heading: str) -> str:
    text = README.read_text(encoding="utf-8")
    match = re.search(
        rf"^### {re.escape(heading)}\n+```python\n(.*?)^```", text, re.MULTILINE | re.DOTALL
    )
    assert match, f"README section {heading!r} with a python block not found"
    return match.group(1)


@pytest.fixture
def github(monkeypatch):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "api.github.com"
        return httpx.Response(200, json={"items": GITHUB_ITEMS})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(server, "get_client", lambda: client)
    return requests


def test_readme_bounty_example_runs_against_real_output(github, capsys):
    snippet = _readme_block("Find and Complete Bounties")
    # Executes a trusted, repo-controlled README snippet on purpose.
    code = compile(snippet, "README.md:bounty-example", "exec")
    exec(code, {"bounty_search": server.bounty_search})  # noqa: S102

    out = capsys.readouterr().out
    assert github, "example must go through bounty_search's GitHub query"
    assert "Harden epoch settlement (150 RTC) - 150.0 RTC" in out
    assert "https://github.com/Scottcjn/Rustchain/issues/1" in out
    assert "Fix a typo" not in out  # filtered out by min_rtc=100


def test_bounty_search_reward_key_is_rtc_reward(github):
    bounty = server.bounty_search()["bounties"][0]
    assert "rtc_reward" in bounty
    assert "reward_rtc" not in bounty and "reward" not in bounty


def test_no_wrong_reward_keys_in_docs():
    root = README.parent
    wrong = re.compile(r"""\[['"](reward_rtc|reward)['"]\]""")
    offenders = []
    for path in [README, root / "llms.txt", root / "SKILL.md", *root.glob("docs/**/*.md"),
                 *root.glob("examples/**/*.md"), *root.glob("examples/**/*.py")]:
        if path.is_file() and wrong.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(root)))
    assert offenders == [], f"use bounty['rtc_reward'] (bounty_search's key): {offenders}"
