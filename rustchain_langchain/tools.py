"""
RustChain + BoTTube + Beacon LangChain Tools
==============================================
Drop-in tools for LangChain and CrewAI agents.
Built on createkr's RustChain Python SDK.

Usage with LangChain:
    from rustchain_langchain import rustchain_balance, bottube_search, beacon_discover
    agent = initialize_agent([rustchain_balance, bottube_search, beacon_discover], llm)

Usage with CrewAI:
    from rustchain_langchain import rustchain_balance, beacon_discover
    agent = Agent(tools=[rustchain_balance, beacon_discover])
"""

import ipaddress
import math
import os
import pathlib
import socket
import tempfile
from urllib.parse import urljoin, urlsplit

import requests

# TLS verification is on by default: these requests carry API keys and bearer
# tokens. Set RUSTCHAIN_TLS_VERIFY=0 (same variable as the MCP server; the
# older TLS_VERIFY still works) only for a trusted self-signed test node.
_TLS_VERIFY = os.environ.get(
    "RUSTCHAIN_TLS_VERIFY", os.environ.get("TLS_VERIFY", "1")
).strip().lower() not in ("0", "false", "no")

try:
    from langchain_core.tools import tool
except ImportError:
    try:
        from langchain.tools import tool
    except ImportError:
        # Fallback: create a simple decorator if langchain not installed
        def tool(func):
            func.is_tool = True
            return func

# Public hostname: the node's certificate is issued for it, so the bare node IP
# fails verification.
RUSTCHAIN_NODE = os.environ.get("RUSTCHAIN_NODE", "https://rustchain.org")
BOTTUBE_URL = os.environ.get("BOTTUBE_URL", "https://bottube.ai")
BEACON_URL = os.environ.get("BEACON_URL", "https://rustchain.org/beacon")

_ALLOWED_VIDEO_EXT = (".mp4", ".webm", ".avi", ".mkv", ".mov")
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024
_MAX_REDIRECTS = 5
_DOWNLOAD_CHUNK = 64 * 1024
_CONTENT_TYPE_EXT = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/x-msvideo": ".avi",
    "video/avi": ".avi",
    "video/x-matroska": ".mkv",
    "video/quicktime": ".mov",
}
_EXT_CONTENT_TYPE = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
}


def _safe_nonneg_int(val, default: int = 0) -> int:
    if val is None or isinstance(val, bool):
        return default
    try:
        return max(0, int(val))
    except (TypeError, ValueError):
        return default


def _check_public_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError("video_url must use http:// or https://")
    host = parts.hostname
    if not host:
        raise ValueError("video_url has no hostname")
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise ValueError(f"could not resolve video_url host {host!r}")
    for addr in addresses:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
        if not ip.is_global:
            raise ValueError(
                f"video_url host {host!r} resolves to non-public IP {ip}; use video_path instead"
            )


def _download_public_video(url: str, limit: int = _MAX_UPLOAD_BYTES) -> tuple[pathlib.Path, str]:
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        _check_public_url(current)
        with requests.get(
            current,
            stream=True,
            allow_redirects=False,
            timeout=120,
            verify=_TLS_VERIFY,
        ) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                if not loc:
                    raise ValueError(f"redirect ({resp.status_code}) missing Location header")
                current = urljoin(current, loc)
                continue
            resp.raise_for_status()
            ext = pathlib.PurePosixPath(urlsplit(current).path).suffix.lower()
            if ext not in _ALLOWED_VIDEO_EXT:
                mime = (resp.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
                ext = _CONTENT_TYPE_EXT.get(mime, "")
                if not ext:
                    raise ValueError(f"unsupported video format; allowed: {', '.join(_ALLOWED_VIDEO_EXT)}")
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > limit:
                raise ValueError("video_url exceeds 500 MB upload limit")
            fd, tmp_name = tempfile.mkstemp(prefix="bottube-lc-", suffix=ext)
            tmp_path = pathlib.Path(tmp_name)
            total = 0
            try:
                with os.fdopen(fd, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=_DOWNLOAD_CHUNK):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > limit:
                            raise ValueError("video_url exceeded 500 MB upload limit while downloading")
                        fh.write(chunk)
                if total == 0:
                    raise ValueError("video_url returned an empty body")
            except BaseException:
                tmp_path.unlink(missing_ok=True)
                raise
            name = pathlib.PurePosixPath(urlsplit(current).path).name
            if not name.lower().endswith(ext):
                name = f"video{ext}"
            return tmp_path, name
    raise ValueError(f"video_url redirected more than {_MAX_REDIRECTS} times")


def _get(url: str, params: dict = None, timeout: int = 30) -> dict:
    """Make GET request with error handling."""
    r = requests.get(url, params=params, timeout=timeout, verify=_TLS_VERIFY)
    r.raise_for_status()
    return r.json()


def _post(url: str, json_data: dict, headers: dict = None, timeout: int = 30) -> dict:
    """Make POST request with error handling."""
    r = requests.post(url, json=json_data, headers=headers, timeout=timeout, verify=_TLS_VERIFY)
    r.raise_for_status()
    return r.json()


@tool
def rustchain_health() -> str:
    """Check RustChain node health. Returns version, uptime, and database status."""
    data = _get(f"{RUSTCHAIN_NODE}/health")
    uptime_s = _safe_nonneg_int(data.get("uptime_s"), 0)
    return (
        f"RustChain Node: {'Healthy' if data.get('ok') else 'Unhealthy'}\n"
        f"Version: {data.get('version', 'unknown')}\n"
        f"Uptime: {uptime_s // 3600}h {(uptime_s % 3600) // 60}m\n"
        f"Database: {'Read/Write' if data.get('db_rw') else 'Read-only'}"
    )


@tool
def rustchain_balance(wallet_id: str) -> str:
    """Check RTC token balance for a RustChain wallet.

    Args:
        wallet_id: Wallet address or miner ID (e.g., "dual-g4-125" or "RTCa1b2c3...")

    Returns balance in RTC tokens. 1 RTC = $0.10 USD reference rate.
    """
    data = _get(f"{RUSTCHAIN_NODE}/wallet/balance", params={"miner_id": wallet_id})
    for key in ("amount_rtc", "balance", "amount"):
        if key in data:
            raw = data[key]
            break
    else:
        raw = 0
    if isinstance(raw, bool):
        return f"Wallet {wallet_id}: balance unavailable (node returned {raw!r})"
    # The node may return a null/absent/non-numeric balance (e.g. for an unknown
    # or empty wallet). Coerce safely so the tool never crashes with TypeError/
    # ValueError on float(None) / float("not-a-number").
    try:
        balance = float(raw)
    except (TypeError, ValueError):
        return f"Wallet {wallet_id}: balance unavailable (node returned {raw!r})"
    if not math.isfinite(balance):
        return f"Wallet {wallet_id}: balance unavailable (node returned {raw!r})"
    return f"Wallet {wallet_id}: {balance:g} RTC (${balance * 0.10:.2f} USD reference)"


@tool
def rustchain_miners() -> str:
    """List active RustChain miners with hardware types and antiquity multipliers.

    Returns miners sorted by multiplier. Vintage hardware earns more:
    PowerPC G4 = 2.5x, G5 = 2.0x, Apple Silicon = 1.2x, Modern = 1.0x.
    """
    data = _get(f"{RUSTCHAIN_NODE}/api/miners")
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


@tool
def rustchain_epoch() -> str:
    """Get current RustChain epoch information including rewards and enrolled miners."""
    data = _get(f"{RUSTCHAIN_NODE}/epoch")
    return (
        f"Epoch: {data.get('epoch', 'unknown')}\n"
        f"Slot: {data.get('slot', 'unknown')}\n"
        f"Enrolled miners: {data.get('enrolled_miners', 0)}\n"
        f"Epoch reward pot: {data.get('epoch_pot', 0)} RTC\n"
        f"Blocks per epoch: {data.get('blocks_per_epoch', 0)}"
    )


@tool
def rustchain_bounties_info() -> str:
    """Get information about available RustChain bounties for earning RTC tokens.

    Browse and claim bounties at https://github.com/Scottcjn/rustchain-bounties
    """
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


@tool
def bottube_stats() -> str:
    """Get BoTTube AI video platform statistics.

    BoTTube.ai is where AI agents create and share video content.
    """
    data = _get(f"{BOTTUBE_URL}/api/stats")
    lines = [
        "BoTTube Platform Stats",
        f"  Videos: {data.get('videos', 0)}",
        f"  AI Agents: {data.get('agents', 0)}",
        f"  Humans: {data.get('humans', 0)}",
        f"  Total Views: {data.get('total_views', 0):,}",
        f"  Comments: {data.get('comments', 0):,}",
        f"  Likes: {data.get('likes', 0):,}",
    ]
    top = [a for a in (data.get("top_agents") or []) if isinstance(a, dict)][:5]
    if top:
        lines.append("  Top creators:")
        for a in top:
            agent_name = a.get("agent_name", a.get("username", "unknown"))
            video_count = _safe_nonneg_int(a.get("video_count"), 0)
            total_views = _safe_nonneg_int(a.get("total_views"), 0)
            lines.append(
                f"    {agent_name}: {video_count} videos, "
                f"{total_views:,} views"
            )
    return "\n".join(lines)


@tool
def bottube_search(query: str) -> str:
    """Search for videos on BoTTube AI video platform.

    Args:
        query: Search query (matches title, description, tags)
    """
    data = _get(f"{BOTTUBE_URL}/api/search", params={"q": query})
    videos = data if isinstance(data, list) else (data.get("videos") or [])
    if not videos:
        return f"No videos found for '{query}'"
    lines = [f"Found {len(videos)} videos for '{query}':"]
    for v in videos[:5]:
        if not isinstance(v, dict):
            continue
        title = str(v.get("title") or "Untitled")[:60]
        creator = v.get("creator", v.get("agent_name", "unknown"))
        views = _safe_nonneg_int(v.get("views"), 0)
        lines.append(f"  [{title}] by {creator} ({views} views)")
    return "\n".join(lines)


@tool
def bottube_upload(
    title: str,
    video_url: str = "",
    description: str = "",
    tags: str = "",
    video_path: str = "",
) -> str:
    """Upload a video to BoTTube AI video platform via multipart/form-data.

    Args:
        title: Video title (max 200 chars)
        video_url: Public HTTP(S) URL of the video file to download & upload
        description: Video description
        tags: Comma-separated tags
        video_path: Local file path of the video (.mp4, .webm, .avi, .mkv, .mov)

    Requires BOTTUBE_API_KEY environment variable. Provide either video_url or video_path.
    """
    api_key = os.environ.get("BOTTUBE_API_KEY", "").strip()
    if not api_key:
        return "Error: BOTTUBE_API_KEY environment variable not set. Get one at bottube.ai"

    clean_title = (title or "").strip()
    if not clean_title:
        return "Error: title is required"
    if len(clean_title) > 200:
        return f"Error: title is {len(clean_title)} chars; max is 200"

    v_url = (video_url or "").strip()
    v_path = (video_path or "").strip()
    if bool(v_url) == bool(v_path):
        return "Error: provide exactly one of video_url or video_path"

    clean_tags = ",".join(t.strip() for t in (tags or "").split(",") if t.strip())
    fields = {
        "title": clean_title,
        "description": (description or "").strip(),
        "tags": clean_tags,
    }

    tmp_path = None
    try:
        if v_path:
            file_path = pathlib.Path(v_path).expanduser()
            if not file_path.is_file():
                return f"Error: video_path not found: {v_path}"
            if file_path.suffix.lower() not in _ALLOWED_VIDEO_EXT:
                return f"Error: unsupported video extension {file_path.suffix!r}"
            if file_path.stat().st_size == 0:
                return f"Error: video_path is empty: {v_path}"
            filename = file_path.name
        else:
            tmp_path, filename = _download_public_video(v_url)
            file_path = tmp_path

        mime = _EXT_CONTENT_TYPE.get(
            pathlib.PurePosixPath(filename).suffix.lower(),
            "application/octet-stream",
        )
        with open(file_path, "rb") as fh:
            resp = requests.post(
                f"{BOTTUBE_URL}/api/upload",
                headers={"X-API-Key": api_key},
                data=fields,
                files={"video": (filename, fh, mime)},
                timeout=300,
                verify=_TLS_VERIFY,
            )
        resp.raise_for_status()
        data = resp.json()
    except (ValueError, requests.exceptions.RequestException, OSError) as exc:
        return f"Error uploading video: {exc}"
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    video_id = data.get("video_id", data.get("id", "unknown"))
    watch_url = data.get("watch_url") or f"https://bottube.ai/watch/{video_id}"
    if isinstance(watch_url, str) and watch_url.startswith("/"):
        watch_url = f"{BOTTUBE_URL}{watch_url}"
    return f"Video uploaded! ID: {video_id}, Watch at: {watch_url}"


# ═══════════════════════════════════════════════════════════════
# BEACON TOOLS — Agent-to-agent communication
# ═══════════════════════════════════════════════════════════════

@tool
def beacon_discover(capability: str = "") -> str:
    """Discover AI agents on the Beacon network. Filter by capability
    (coding, research, creative, video-production, blockchain, etc.).

    Args:
        capability: Filter by capability. Empty = list all agents.
    """
    data = _get(f"{BEACON_URL}/api/agents")
    raw_agents = data if isinstance(data, list) else (data.get("agents") or []) if isinstance(data, dict) else []
    agents = [a for a in raw_agents if isinstance(a, dict)]
    if capability:
        cap_lower = capability.lower()
        agents = [
            a for a in agents
            if cap_lower in [c.lower() for c in (a.get("capabilities") or []) if isinstance(c, str)]
        ]
    lines = [f"Beacon agents: {len(agents)}"]
    for a in agents[:15]:
        agent_id = a.get("agent_id", "?")
        name = a.get("name", agent_id)
        status = a.get("status", "unknown")
        relay = " (relay)" if a.get("relay") else ""
        lines.append(f"  {agent_id}: {name} [{status}]{relay}")
    if len(agents) > 15:
        lines.append(f"  ... and {len(agents) - 15} more")
    return "\n".join(lines)


@tool
def beacon_network_stats() -> str:
    """Get Beacon network statistics — total agents, active count, provider breakdown."""
    data = _get(f"{BEACON_URL}/relay/stats")
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


@tool
def beacon_chat(agent_id: str, message: str) -> str:
    """Chat with a native Beacon agent (Sophia Elya, Boris Volkov, DeepSeeker, etc.).

    Args:
        agent_id: Agent to chat with (e.g., "bcn_sophia_elya", "bcn_deep_seeker")
        message: Your message
    """
    data = _post(
        f"{BEACON_URL}/api/chat",
        json_data={"agent_id": agent_id, "message": message},
    )
    agent = data.get("agent", "Unknown")
    response = data.get("response", "No response")
    return f"{agent}: {response}"
