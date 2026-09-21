"""Guard the public-facing text against claims that are no longer true.

This package is listed on MCP directories, so its README, skill files, and
tool descriptions are often the first thing a stranger reads about RustChain.
Each pattern below was found in the repo at least once and corrected; the test
keeps them from drifting back in.

If a pattern trips legitimately (for example a node really is added), update
the pattern and the prose together.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent

# Files a stranger or an LLM reads first. Source files are included because
# tool docstrings become the MCP tool descriptions.
PUBLIC_TEXT = [
    "README.md",
    "SKILL.md",
    "llms.txt",
    "CONTRIBUTING.md",
    "rustchain_mcp/server.py",
    "rustchain_mcp/events.py",
    *[str(p.relative_to(REPO)) for p in (REPO / "docs").glob("*.md")],
    *[str(p.relative_to(REPO)) for p in (REPO / ".claude" / "skills").glob("*.md")],
    *[str(p.relative_to(REPO)) for p in (REPO / "examples").rglob("SKILL.md")],
]

FORBIDDEN = {
    # Node fleet: two live attestation nodes. The HK host is gone and the
    # Proxmox node is Tailscale-only (unreachable and a private address).
    "dead HK node address": re.compile(r"38\.76\.217\.189"),
    "Tailscale-only node address": re.compile(r"100\.88\.109\.32"),
    "four-node claim": re.compile(r"\b(all 4|4 nodes|four (attestation )?nodes|4 RustChain)\b", re.IGNORECASE),
    # RTC is not priced, sold, bridged, or wrapped. The internal reference
    # rate may be mentioned only as a sizing convention, never as a price.
    "dollar price for RTC": re.compile(r"1\s*RTC\s*=\s*\$|\$\s*0\.10\s*(USD)?\s*/?\s*(per\s*)?RTC|\$0\.10/RTC", re.IGNORECASE),
    "wrapped RTC / bridge": re.compile(r"\bwRTC\b|wrapped RTC|RTC bridge|bridge (RTC|to Solana)|token bridge", re.IGNORECASE),
    "buy / invest call-to-action": re.compile(r"\b(buy|purchase|invest in)\s+RTC\b|RTC\s+(is|are)\s+(for sale|tradeable|tradable)", re.IGNORECASE),
    # No API key is needed for this server.
    "API key prerequisite": re.compile(r"(valid|your)\s+RustChain\s+API\s+key|RUSTCHAIN_API_KEY", re.IGNORECASE),
    # The console script parses no flags.
    "nonexistent CLI flags": re.compile(r"rustchain-mcp\s+--(debug|log-file|api-key|network)\b"),
    # Supply is 2^23; the old whitepaper figure is wrong.
    "stale supply figure": re.compile(r"8,?192,?000"),
}


@pytest.mark.parametrize("relpath", PUBLIC_TEXT)
def test_public_text_has_no_stale_claims(relpath):
    path = REPO / relpath
    if not path.exists():
        pytest.skip(f"{relpath} not present")
    text = path.read_text(encoding="utf-8")
    hits = []
    for label, pattern in FORBIDDEN.items():
        for match in pattern.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            hits.append(f"{relpath}:{line_no}: {label}: {match.group(0)!r}")
    assert hits == [], "\n".join(hits)


def test_supply_is_stated_as_two_to_the_23():
    server_text = (REPO / "rustchain_mcp" / "server.py").read_text(encoding="utf-8")
    assert "8,388,608" in server_text
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "8,388,608" in readme


def test_readme_states_rtc_is_not_for_sale():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert re.search(r"not offered for sale|not for sale", readme, re.IGNORECASE)
    assert re.search(r"internal reference rate", readme, re.IGNORECASE)
    assert re.search(r"not a price", readme, re.IGNORECASE)


def test_readme_states_two_nodes():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert re.search(r"two live attestation nodes|currently 2", readme, re.IGNORECASE)
