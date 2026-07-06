"""
RustChain CrewAI Tools
======================
Native RustChain tools for CrewAI agents.
Built on createkr's RustChain Python SDK.

Usage with CrewAI:
    from rustchain_crewai import RustChainCheckBalance, RustChainListBounties
    from crewai import Agent, Task, Crew

    agent = Agent(
        role="Blockchain Analyst",
        tools=[RustChainCheckBalance(), RustChainListBounties()],
        ...
    )
"""

import os
import requests
from typing import Type
from pydantic import BaseModel, Field

try:
    from crewai.tools import BaseTool
except ImportError:
    raise ImportError(
        "crewai is required. Install with: pip install crewai"
    )

# Self-signed cert on dev nodes
_TLS_VERIFY = os.environ.get("TLS_VERIFY", "0") != "0"

RUSTCHAIN_NODE = os.environ.get("RUSTCHAIN_NODE", "https://50.28.86.131")
BOTTUBE_URL = os.environ.get("BOTTUBE_URL", "https://bottube.ai")
BEACON_URL = os.environ.get("BEACON_URL", "https://rustchain.org/beacon")


def _get(url: str, params: dict = None, timeout: int = 30) -> dict:
    """Make GET request with error handling."""
    try:
        r = requests.get(url, params=params, timeout=timeout, verify=_TLS_VERIFY)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


def _post(url: str, json_data: dict, headers: dict = None, timeout: int = 30) -> dict:
    """Make POST request with error handling."""
    try:
        r = requests.post(url, json=json_data, headers=headers, timeout=timeout, verify=_TLS_VERIFY)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


class CheckBalanceInput(BaseModel):
    """Input for checking RustChain wallet balance."""
    wallet_id: str = Field(
        description="Wallet address or miner ID (e.g., 'dual-g4-125' or 'RTCa1b2c3...')"
    )


class RustChainCheckBalance(BaseTool):
    """Check RTC token balance for a RustChain wallet."""
    name: str = "rustchain_check_balance"
    description: str = (
        "Check RTC token balance for a RustChain wallet. "
        "Returns balance in RTC tokens. 1 RTC = $0.10 USD reference rate."
    )
    args_schema: Type[BaseModel] = CheckBalanceInput

    def _run(self, wallet_id: str) -> str:
        data = _get(f"{RUSTCHAIN_NODE}/balance", params={"miner_id": wallet_id})
        if "error" in data:
            return f"Error checking balance: {data['error']}"
        balance = data.get("balance", data.get("amount", 0))
        return f"Wallet {wallet_id}: {balance} RTC (${float(balance) * 0.10:.2f} USD reference)"


class ListBountiesInput(BaseModel):
    """Input for listing RustChain bounties."""
    limit: int = Field(default=10, description="Maximum number of bounties to return")


class RustChainListBounties(BaseTool):
    """List available RustChain bounties for earning RTC tokens."""
    name: str = "rustchain_list_bounties"
    description: str = (
        "List available RustChain bounties for earning RTC tokens. "
        "Browse and claim bounties at https://github.com/Scottcjn/rustchain-bounties"
    )
    args_schema: Type[BaseModel] = ListBountiesInput

    def _run(self, limit: int = 10) -> str:
        return (
            "RustChain Bounty Program\n"
            "========================\n"
            "- 23,300+ RTC paid to 218 recipients across 716 transactions\n"
            "- Bounties range from 5-500 RTC per task\n"
            "- Categories: Code (5-500 RTC), Security audits (100-200 RTC),\n"
            "  Documentation (5-50 RTC), Integrations (75-150 RTC)\n"
            "- RTC reference rate: $0.10 USD\n"
            "- Browse: https://github.com/Scottcjn/rustchain-bounties\n"
            "- Claim by commenting on an issue, submit PR, get paid!"
        )


class RustChainGetNodeHealth(BaseTool):
    """Check RustChain node health status."""
    name: str = "rustchain_get_node_health"
    description: str = (
        "Check RustChain node health. Returns version, uptime, and database status."
    )

    def _run(self) -> str:
        data = _get(f"{RUSTCHAIN_NODE}/health")
        if "error" in data:
            return f"Error checking health: {data['error']}"
        return (
            f"RustChain Node: {'Healthy' if data.get('ok') else 'Unhealthy'}\n"
            f"Version: {data.get('version', 'unknown')}\n"
            f"Uptime: {data.get('uptime_s', 0) // 3600}h {(data.get('uptime_s', 0) % 3600) // 60}m\n"
            f"Database: {'Read/Write' if data.get('db_rw') else 'Read-only'}"
        )


class RustChainGetCurrentEpoch(BaseTool):
    """Get current RustChain epoch information."""
    name: str = "rustchain_get_current_epoch"
    description: str = (
        "Get current RustChain epoch information including rewards and enrolled miners."
    )

    def _run(self) -> str:
        data = _get(f"{RUSTCHAIN_NODE}/epoch")
        if "error" in data:
            return f"Error getting epoch: {data['error']}"
        return (
            f"Epoch: {data.get('epoch', 'unknown')}\n"
            f"Slot: {data.get('slot', 'unknown')}\n"
            f"Enrolled miners: {data.get('enrolled_miners', 0)}\n"
            f"Epoch reward pot: {data.get('epoch_pot', 0)} RTC\n"
            f"Blocks per epoch: {data.get('blocks_per_epoch', 0)}"
        )


class RustChainGetMiners(BaseTool):
    """List active RustChain miners with hardware types and antiquity multipliers."""
    name: str = "rustchain_get_miners"
    description: str = (
        "List active RustChain miners with hardware types and antiquity multipliers. "
        "Vintage hardware earns more: PowerPC G4 = 2.5x, G5 = 2.0x, Apple Silicon = 1.2x."
    )

    def _run(self) -> str:
        data = _get(f"{RUSTCHAIN_NODE}/api/miners")
        if "error" in data:
            return f"Error getting miners: {data['error']}"
        miners = data if isinstance(data, list) else data.get("miners", [])
        lines = [f"Active miners: {len(miners)}"]
        for m in miners[:10]:
            wallet = m.get("miner", "unknown")[:25]
            hw = m.get("hardware_type", m.get("device_arch", "unknown"))
            mult = m.get("antiquity_multiplier", 1.0)
            lines.append(f"  {wallet}... | {hw} | {mult}x")
        if len(miners) > 10:
            lines.append(f"  ... and {len(miners) - 10} more")
        return "\n".join(lines)


class BoTTubeSearchInput(BaseModel):
    """Input for searching BoTTube videos."""
    query: str = Field(description="Search query (matches title, description, tags)")


class RustChainBoTTubeSearch(BaseTool):
    """Search for videos on BoTTube AI video platform."""
    name: str = "rustchain_bottube_search"
    description: str = (
        "Search for videos on BoTTube AI video platform. "
        "BoTTube.ai is where AI agents create and share video content."
    )
    args_schema: Type[BaseModel] = BoTTubeSearchInput

    def _run(self, query: str) -> str:
        data = _get(f"{BOTTUBE_URL}/api/v1/videos/search", params={"q": query})
        if "error" in data:
            return f"Error searching videos: {data['error']}"
        videos = data if isinstance(data, list) else data.get("videos", [])
        if not videos:
            return f"No videos found for '{query}'"
        lines = [f"Found {len(videos)} videos for '{query}':"]
        for v in videos[:5]:
            title = v.get("title", "Untitled")[:60]
            creator = v.get("creator", v.get("agent_name", "unknown"))
            views = v.get("views", 0)
            lines.append(f"  [{title}] by {creator} ({views} views)")
        return "\n".join(lines)


class RustChainBoTTubeStats(BaseTool):
    """Get BoTTube AI video platform statistics."""
    name: str = "rustchain_bottube_stats"
    description: str = (
        "Get BoTTube AI video platform statistics. "
        "BoTTube.ai is where AI agents create and share video content."
    )

    def _run(self) -> str:
        data = _get(f"{BOTTUBE_URL}/api/stats")
        if "error" in data:
            return f"Error getting stats: {data['error']}"
        lines = [
            "BoTTube Platform Stats",
            f"  Videos: {data.get('videos', 0)}",
            f"  AI Agents: {data.get('agents', 0)}",
            f"  Humans: {data.get('humans', 0)}",
            f"  Total Views: {data.get('total_views', 0):,}",
            f"  Comments: {data.get('comments', 0):,}",
            f"  Likes: {data.get('likes', 0):,}",
        ]
        top = data.get("top_agents", [])[:5]
        if top:
            lines.append("  Top creators:")
            for a in top:
                lines.append(
                    f"    {a['agent_name']}: {a['video_count']} videos, "
                    f"{a['total_views']:,} views"
                )
        return "\n".join(lines)


class BeaconDiscoverInput(BaseModel):
    """Input for discovering Beacon agents."""
    capability: str = Field(
        default="",
        description="Filter by capability (coding, research, creative, video-production, blockchain, etc.)"
    )


class RustChainBeaconDiscover(BaseTool):
    """Discover AI agents on the Beacon network."""
    name: str = "rustchain_beacon_discover"
    description: str = (
        "Discover AI agents on the Beacon network. Filter by capability "
        "(coding, research, creative, video-production, blockchain, etc.)."
    )
    args_schema: Type[BaseModel] = BeaconDiscoverInput

    def _run(self, capability: str = "") -> str:
        data = _get(f"{BEACON_URL}/api/agents")
        if "error" in data:
            return f"Error discovering agents: {data['error']}"
        agents = data if isinstance(data, list) else []
        if capability:
            agents = [a for a in agents if capability.lower() in
                      [c.lower() for c in a.get("capabilities", [])]]
        lines = [f"Beacon agents: {len(agents)}"]
        for a in agents[:15]:
            name = a.get("name", a.get("agent_id", "?"))
            status = a.get("status", "unknown")
            relay = " (relay)" if a.get("relay") else ""
            lines.append(f"  {a['agent_id']}: {name} [{status}]{relay}")
        if len(agents) > 15:
            lines.append(f"  ... and {len(agents) - 15} more")
        return "\n".join(lines)


class RustChainBeaconNetworkStats(BaseTool):
    """Get Beacon network statistics."""
    name: str = "rustchain_beacon_network_stats"
    description: str = (
        "Get Beacon network statistics — total agents, active count, provider breakdown."
    )

    def _run(self) -> str:
        data = _get(f"{BEACON_URL}/relay/stats")
        if "error" in data:
            return f"Error getting stats: {data['error']}"
        lines = [
            "Beacon Network Stats",
            f"  Native agents: {data.get('native_agents', 0)}",
            f"  Relay agents: {data.get('total_relay_agents', 0)}",
            f"  Active: {data.get('active', 0)}",
            f"  Silent: {data.get('silent', 0)}",
            f"  Presumed dead: {data.get('presumed_dead', 0)}",
        ]
        providers = data.get("by_provider", {})
        if providers:
            lines.append("  By provider:")
            for p, count in sorted(providers.items(), key=lambda x: -x[1]):
                lines.append(f"    {p}: {count}")
        return "\n".join(lines)


class BeaconChatInput(BaseModel):
    """Input for chatting with Beacon agents."""
    agent_id: str = Field(description="Agent to chat with (e.g., 'bcn_sophia_elya', 'bcn_deep_seeker')")
    message: str = Field(description="Your message")


class RustChainBeaconChat(BaseTool):
    """Chat with a native Beacon agent."""
    name: str = "rustchain_beacon_chat"
    description: str = (
        "Chat with a native Beacon agent (Sophia Elya, Boris Volkov, DeepSeeker, etc.)."
    )
    args_schema: Type[BaseModel] = BeaconChatInput

    def _run(self, agent_id: str, message: str) -> str:
        data = _post(
            f"{BEACON_URL}/api/chat",
            json_data={"agent_id": agent_id, "message": message},
        )
        if "error" in data:
            return f"Error chatting: {data['error']}"
        agent = data.get("agent", "Unknown")
        response = data.get("response", "No response")
        return f"{agent}: {response}"
