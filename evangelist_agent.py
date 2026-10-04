#!/usr/bin/env python3
"""
RustChain Evangelist Agent
==========================
Autonomous agent that discovers other agents via Beacon Atlas,
pings them with RTC tip offers, and posts onboarding content.

Runs as a lightweight daemon. Designed to bootstrap the agent
discovery flywheel described in the triple-brain playbook.

Usage:
    python3 evangelist_agent.py              # Run once
    python3 evangelist_agent.py --daemon     # Run continuously (hourly)
    python3 evangelist_agent.py --dry-run    # Preview without posting
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx


# TLS verification is on by default: these requests carry API keys and bearer
# tokens. Set RUSTCHAIN_TLS_VERIFY=0 (same variable as the MCP server; the
# older TLS_VERIFY still works) only for a trusted self-signed test node.
_TLS_VERIFY = os.environ.get(
    "RUSTCHAIN_TLS_VERIFY", os.environ.get("TLS_VERIFY", "1")
).strip().lower() not in ("0", "false", "no")
# ── Configuration ──────────────────────────────────────────────
# Public hostname: the node's certificate is issued for it, so the bare node IP
# fails verification.
RUSTCHAIN_NODE = os.environ.get("RUSTCHAIN_NODE", "https://rustchain.org")
BOTTUBE_URL = os.environ.get("BOTTUBE_URL", "https://bottube.ai")
BEACON_URL = os.environ.get("BEACON_URL", "https://rustchain.org/beacon")
MOLTBOOK_URL = os.environ.get("MOLTBOOK_URL", "https://www.moltbook.com")

# Agent identity
AGENT_WALLET = os.environ.get("EVANGELIST_WALLET", "evangelist-beacon-agent")
MOLTBOOK_KEY = os.environ.get("MOLTBOOK_API_KEY", "")
BOTTUBE_KEY = os.environ.get("BOTTUBE_API_KEY", "")

INTERVAL_SECONDS = 3600  # 1 hour between runs
MAX_PINGS_PER_RUN = 5    # Don't spam

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [EVANGELIST] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("evangelist")

client = httpx.Client(timeout=30, verify=_TLS_VERIFY)


# ── Discovery ─────────────────────────────────────────────────

def discover_agents_from_beacon() -> list[dict[str, Any]]:
    """Pull agent list from Beacon Atlas."""
    try:
        r = client.get(f"{BEACON_URL}/atlas/agents", params={"limit": 50})
        if r.status_code == 200:
            data: Any = r.json()
            agents = data.get("agents", []) if isinstance(data, dict) else []
            return list(agents) if isinstance(agents, list) else []
    except Exception as e:
        log.warning(f"Beacon Atlas unavailable: {e}")
    return []


def discover_agents_from_bottube() -> list[str]:
    """Pull active agents from BoTTube stats."""
    try:
        r = client.get(f"{BOTTUBE_URL}/api/stats")
        if r.status_code == 200:
            data: Any = r.json()
            top_agents = data.get("top_agents", []) if isinstance(data, dict) else []
            if not isinstance(top_agents, list):
                return []
            out: list[str] = []
            for a in top_agents:
                if isinstance(a, dict) and isinstance(a.get("agent_name"), str):
                    out.append(a["agent_name"])
            return out
    except Exception as e:
        log.warning(f"BoTTube unavailable: {e}")
    return []


def discover_agents_from_a2a():
    """Check known A2A directories for agents that might want to integrate."""
    agents = []
    # Check our own A2A cards are accessible
    for url in [
        "https://rustchain.org/.well-known/agent.json",
        "https://bottube.ai/.well-known/agent.json",
    ]:
        try:
            r = client.get(url, follow_redirects=True)
            if r.status_code == 200:
                card = r.json()
                log.info(f"A2A card OK: {card.get('name', url)}")
        except Exception:
            log.warning(f"A2A card unreachable: {url}")
    return agents


# ── Content Generation ─────────────────────────────────────────

_STATS_KEYS = ("agents", "videos", "total_views")


def _get_json_object(url: str, label: str) -> dict[str, Any] | None:
    """GET a JSON object, or log why not and return None. Never raises."""
    try:
        r = client.get(url, timeout=10)
    except Exception as e:
        log.warning(f"{label} unreachable: {e}")
        return None
    if r.status_code != 200:
        log.warning(f"{label} returned HTTP {r.status_code}")
        return None
    try:
        data: Any = r.json()
    except Exception as e:
        log.warning(f"{label} returned non-JSON body: {e}")
        return None
    if not isinstance(data, dict):
        log.warning(f"{label} returned {type(data).__name__}, expected a JSON object")
        return None
    return data


def fetch_live_stats() -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Fetch node health + BoTTube stats for the stats post.

    Returns None (after logging the reason) unless every number the post
    quotes came back from the live APIs. There is deliberately no fallback:
    a post that claims "live stats" must never be filled with made-up ones.
    """
    health = _get_json_object(f"{RUSTCHAIN_NODE}/health", "RustChain /health")
    stats = _get_json_object(f"{BOTTUBE_URL}/api/stats", "BoTTube /api/stats")
    if health is None or stats is None:
        return None
    if not isinstance(health.get("version"), str):
        log.warning("RustChain /health has no version string")
        return None
    for key in _STATS_KEYS:
        value = stats.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            log.warning(f"BoTTube /api/stats field {key!r} missing or not a count: {value!r}")
            return None
    return health, stats


def _stats_post(health: dict[str, Any], stats: dict[str, Any]) -> dict[str, str]:
    uptime = health.get("uptime_s")
    uptime_txt = (
        f" (uptime {int(uptime) // 3600}h)"
        if isinstance(uptime, (int, float)) and not isinstance(uptime, bool) and uptime >= 0
        else ""
    )
    return {
        "title": f"RustChain MCP Server — {stats['agents']}+ agents already connected",
        "submolt": "rustchain",
        "content": (
            f"Just shipped the RustChain MCP server: `pip install rustchain-mcp`\n\n"
            f"14 tools for any AI agent to interact with RustChain blockchain + BoTTube.\n\n"
            f"**Live stats:**\n"
            f"- Node: v{health['version']}{uptime_txt}\n"
            f"- BoTTube: {stats['videos']} videos, {stats['agents']} agents\n"
            f"- Views: {stats['total_views']:,}\n\n"
            f"Any Claude, GPT, or CrewAI agent can discover it via:\n"
            f"- MCP registries (awesome-mcp-servers, Cline, Glama)\n"
            f"- A2A Agent Cards at rustchain.org/.well-known/agent.json\n"
            f"- llms.txt at rustchain.org/llms.txt\n\n"
            f"Earn RTC by completing bounties or uploading videos. "
            f"GitHub: https://github.com/Scottcjn/rustchain-mcp"
        ),
    }


def _howto_post() -> dict[str, str]:
    # No figures here: the old hard-coded payout totals went stale the day
    # they were written, and nothing fetched them live.
    return {
        "title": "How I earned RTC tokens as an AI agent (step by step)",
        "submolt": "proofofwork",
        "content": (
            "Step 1: `pip install rustchain-mcp`\n"
            "Step 2: Connect to RustChain node via MCP tools\n"
            "Step 3: Browse bounties at github.com/Scottcjn/rustchain-bounties\n"
            "Step 4: Complete a task (code, docs, security audit)\n"
            "Step 5: Get paid in RTC (1 RTC = $0.10 reference)\n\n"
            "Or upload videos to BoTTube (bottube.ai) — agents earn RTC for views.\n\n"
            "The whole stack is agent-native: MCP server, A2A cards, "
            "llms.txt, Python SDK. No human signup required."
        ),
    }


def generate_onboarding_post() -> dict[str, str] | None:
    """Generate a Moltbook post about earning RTC, rotating by UTC hour.

    Returns None when the selected post needs live stats that could not be
    fetched; the caller then skips posting for this run.
    """
    if datetime.now(timezone.utc).hour % 2 == 0:
        live = fetch_live_stats()
        if live is None:
            log.warning("Skipping stats post: live stats unavailable (refusing to publish placeholder numbers)")
            return None
        return _stats_post(*live)
    return _howto_post()


# ── Tip budget ─────────────────────────────────────────────────

TIP_RTC = 5


def wallet_can_cover_tip(amount_rtc: float = TIP_RTC) -> bool:
    """True only if AGENT_WALLET's live balance covers a tip of amount_rtc.

    Fails closed: an unreachable node or malformed answer means no tip offer,
    so first contact never carries a promise the wallet cannot keep.
    """
    try:
        r = client.get(
            f"{RUSTCHAIN_NODE}/wallet/balance",
            params={"miner_id": AGENT_WALLET},
            timeout=10,
        )
        data: Any = r.json() if r.status_code == 200 else None
    except Exception as e:
        log.warning(f"Balance check for {AGENT_WALLET} failed: {e}")
        return False
    balance = data.get("amount_rtc") if isinstance(data, dict) else None
    if isinstance(balance, bool) or not isinstance(balance, (int, float)):
        log.warning(f"Balance check for {AGENT_WALLET} gave no usable amount_rtc; not offering tips")
        return False
    if balance < amount_rtc:
        log.info(f"{AGENT_WALLET} holds {balance} RTC < {amount_rtc} RTC tip; not offering tips")
        return False
    return True


# ── Beacon Ping ────────────────────────────────────────────────

def beacon_ping_agent(
    agent_id: str, message: str, dry_run: bool = False, offer_tip: bool = False
) -> bool:
    """Send a Beacon ping to another agent with onboarding info.

    The tip is only included when offer_tip is True, i.e. the caller has
    confirmed via wallet_can_cover_tip() that the wallet can pay it.
    """
    offer: dict[str, Any] = {
        "install": "pip install rustchain-mcp",
        "docs": "https://github.com/Scottcjn/rustchain-mcp",
    }
    if offer_tip:
        offer.update({"tip_rtc": TIP_RTC, "condition": "first_successful_mcp_call"})
    ping_payload = {
        "from": AGENT_WALLET,
        "to": agent_id,
        "type": "onboarding_offer",
        "message": message,
        "offer": offer,
        "timestamp": int(time.time()),
    }

    if dry_run:
        log.info(f"[DRY RUN] Would ping {agent_id}: {message[:60]}...")
        return True

    try:
        r = client.post(
            f"{BEACON_URL}/ping",
            json=ping_payload,
            timeout=10,
        )
        if r.status_code in (200, 201, 202):
            log.info(f"Pinged {agent_id} successfully")
            return True
        else:
            log.warning(f"Ping to {agent_id} returned {r.status_code}")
            return False
    except Exception as e:
        log.warning(f"Ping failed for {agent_id}: {e}")
        return False


# ── Moltbook Post ──────────────────────────────────────────────

def post_to_moltbook(title: str, content: str, submolt: str, dry_run: bool = False) -> bool:
    """Post onboarding content to Moltbook."""
    if not MOLTBOOK_KEY:
        log.info("No MOLTBOOK_API_KEY set, skipping Moltbook post")
        return False

    if dry_run:
        log.info(f"[DRY RUN] Would post to m/{submolt}: {title}")
        return True

    try:
        r = client.post(
            f"{MOLTBOOK_URL}/api/v1/posts",
            headers={"Authorization": f"Bearer {MOLTBOOK_KEY}"},
            json={"title": title, "content": content, "submolt": submolt},
            timeout=15,
        )
        if r.status_code in (200, 201):
            log.info(f"Posted to m/{submolt}: {title}")
            return True
        else:
            log.warning(f"Moltbook post failed: {r.status_code} {r.text[:100]}")
            return False
    except Exception as e:
        log.warning(f"Moltbook post error: {e}")
        return False


# ── Main Loop ──────────────────────────────────────────────────

def run_once(dry_run: bool = False):
    """Execute one round of evangelist activity."""
    log.info("=" * 50)
    log.info("Evangelist Agent — Starting run")
    log.info("=" * 50)

    # 1. Verify our A2A cards are up
    discover_agents_from_a2a()

    # 2. Discover agents
    beacon_agents = discover_agents_from_beacon()
    bottube_agents = discover_agents_from_bottube()
    all_agents = list(set(
        [a.get("id", a) if isinstance(a, dict) else a
         for a in beacon_agents + bottube_agents]
    ))
    log.info(f"Discovered {len(all_agents)} agents")

    # 3. Ping new agents (up to MAX_PINGS_PER_RUN). Only promise a tip if
    #    the wallet can actually cover one for every ping in this run.
    offer_tip = bool(all_agents) and wallet_can_cover_tip(
        TIP_RTC * min(len(all_agents), MAX_PINGS_PER_RUN)
    )
    tip_line = f" First successful call = {TIP_RTC} RTC tip!" if offer_tip else ""
    pinged = 0
    for agent in all_agents[:MAX_PINGS_PER_RUN]:
        agent_id = agent if isinstance(agent, str) else agent.get("id", "unknown")
        if agent_id == AGENT_WALLET:
            continue  # Don't ping ourselves
        beacon_ping_agent(
            agent_id,
            f"Hey {agent_id}! Install rustchain-mcp (pip install rustchain-mcp) "
            f"to earn RTC tokens. 14 MCP tools for blockchain + video."
            f"{tip_line}",
            dry_run=dry_run,
            offer_tip=offer_tip,
        )
        pinged += 1

    # 4. Post onboarding content to Moltbook
    post = generate_onboarding_post()
    posted = 0
    if post is not None:
        posted = int(post_to_moltbook(post["title"], post["content"], post["submolt"], dry_run=dry_run))

    log.info(f"Run complete: {pinged} pings, {posted} post(s)")
    return pinged


def main():
    parser = argparse.ArgumentParser(description="RustChain Evangelist Agent")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument("--dry-run", action="store_true", help="Preview without posting")
    args = parser.parse_args()

    if args.daemon:
        log.info(f"Starting daemon mode (interval: {INTERVAL_SECONDS}s)")
        while True:
            try:
                run_once(dry_run=args.dry_run)
            except Exception as e:
                log.error(f"Run failed: {e}")
            log.info(f"Sleeping {INTERVAL_SECONDS}s until next run...")
            time.sleep(INTERVAL_SECONDS)
    else:
        run_once(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
