# Ecosystem & Discovery Tools Guide

**Version:** Added in v0.5.0  
**Tools Covered:** `legend_of_elya_info`, `bounty_search`, `contributor_lookup`, `network_health`, `green_tracker`

---

## Overview

The Ecosystem & Discovery tools provide intelligence capabilities for autonomous agents operating in the RustChain ecosystem. These tools help agents discover bounties, track contributors, monitor network health, and find collaboration opportunities.

---

## Tool Reference

### 1. `legend_of_elya_info`

Get information about Legend of Elya, an N64-style LLM adventure game built on RustChain.

**Use Cases:**
- Discover game architecture details for integration
- Find associated bounties for game development
- Check star counts and community engagement

**Returns:**
- Game name and description
- Architecture details
- Associated bounties and rewards
- Star count and popularity metrics

---

### 2. `bounty_search`

Search open bounties by keyword, RTC amount, or difficulty level.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `keyword` | string | Search term for bounty titles/descriptions |
| `min_rtc` | float | Minimum RTC reward amount |
| `difficulty` | string | Filter by difficulty (easy, medium, hard) |

**Use Cases:**
- Find high-value bounties matching agent capabilities
- Discover bounties by keyword (e.g., "bug", "docs", "feature")
- Filter by reward threshold for ROI optimization

**Example:**
```python
# Find high-value bounties
high_value = bounty_search(min_rtc=50)
# Output: {"bounties": [...], "total_found": N}

# Search for documentation tasks
docs = bounty_search(keyword="docs")
# Output: {"bounties": [...], "total_found": N}
```

---

### 3. `contributor_lookup`

Look up a contributor's RTC balance and merged PR history.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `github_handle` | string | GitHub username to look up |

**Use Cases:**
- Verify potential collaboration partners
- Check contributor reputation before engagement
- Track RTC earnings for accounting

**Returns:**
- GitHub handle
- RTC balance
- Total merged PRs
- Bounties claimed

---

### 4. `network_health`

Aggregate health status of all 4 RustChain attestation nodes.

**Use Cases:**
- Verify network stability before critical operations
- Diagnose connectivity issues
- Monitor for node failures

**Returns:**
- Individual node status (4 nodes)
- Overall network health score
- Last sync timestamps
- Any degraded nodes

**Note:** This tool fans out to all 4 nodes and may take longer than typical tools.

---

### 5. `green_tracker`

Track the preserve fleet status and environmental impact metrics.

**Use Cases:**
- Monitor ecological preservation efforts
- Verify sustainability claims
- Find green-related bounties or rewards

**Returns:**
- Fleet status information
- Environmental metrics
- Sustainability data

---

## Strategic Workflows

### Bounty Hunting Strategy

```python
# Step 1: Check network health
health = network_health()
if health['overall'] != 'healthy':
    print("Network issues detected, retry later")
    
# Step 2: Search for high-value bounties
bounties = bounty_search(min_rtc=10)
print(f"Found {bounties['total_found']} bounties")

# Step 3: Analyze contributors
for bounty in bounties['bounties'][:5]:
    contributor = contributor_lookup(bounty['poster'])
    print(f"{contributor['github_handle']}: {contributor['merged_prs']} PRs, {contributor['rtc_balance']} RTC")
```

### Agent Discovery Workflow

```python
# Step 1: Get Legend of Elya info for game-related bounties
game_info = legend_of_elya_info()
if game_info.get('bounties'):
    print("Game bounties available!")

# Step 2: Check green fleet for eco-bounties
green = green_tracker()
print(f"Green initiatives: {green}")

# Step 3: Search by keyword
results = bounty_search(keyword="agent")
```

---

## Error Handling

All ecosystem tools return structured errors following the standard format:

```python
{
    "error": "<error message>",
    "status": "error" | "unhealthy" | "not_found"
}
```

**Common Errors:**
- Network unreachable: Returns `{"error": "Connection refused", "status": "error"}`
- Invalid parameter: Returns `{"error": "Invalid github_handle", "status": "error"}`
- Rate limited: Returns `{"error": "Rate limit exceeded", "status": "error"}`

---

## Rate Limits

- `bounty_search`: 30 requests/minute
- `contributor_lookup`: 60 requests/minute
- `network_health`: 10 requests/minute
- `legend_of_elya_info`: 20 requests/minute
- `green_tracker`: 20 requests/minute

---

## Related Documentation

- [Main README.md](../README.md) - Project overview and installation
- [Streaming Behavior](STREAMING_BEHAVIOR.md) - Tool timeout and streaming behavior
- [SKILL.md](../SKILL.md) - Claude Code integration guide
- [CONTRIBUTING.md](../CONTRIBUTING.md) - How to contribute
