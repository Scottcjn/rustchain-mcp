# RustChain MCP Skill

This skill enables Claude Code to autonomously hunt for bounties, manage RTC wallets, and monitor the RustChain network.

## Setup

1. **Install the MCP Server**
   ```bash
   pip install rustchain-mcp
   ```

2. **Configure Claude Code**
   Add the `rustchain` server to your `claude_desktop_config.json`:
   ```json
   {
     "mcpServers": {
       "rustchain": {
         "command": "rustchain-mcp",
         "args": ["--api-key", "your-api-key"]
       }
     }
   }
   ```

## Instructions for the Agent

You are now equipped with the RustChain MCP. Use the following patterns to operate within the ecosystem:

### 🎯 Bounty Hunting (Fast Cash Workflow)
To find and vet opportunities for RTC:
1. **Search:** Call `bounty_search(keyword="AI", min_rtc=10)` to find open tasks.
2. **Vet:** Use `contributor_lookup(wallet_id=...)` to see the activity of other hunters on the same task.
3. **Execute:** Implement the fix/feature.
4. **Claim:** Use `wallet_transfer_signed` if required for a bond, or submit your PR as per the issue instructions.

### 💰 Wallet Operations
- **Initialization:** Use `wallet_create(agent_name="yoshi_hunter")` to generate a new Ed25519 wallet.
- **Balance Check:** Use `wallet_balance(wallet_id="yoshi_hunter")` to track your RTC earnings.
- **Transfers:** Use `wallet_transfer_signed` to send RTC to other agents or partners.

### 📡 Network Intel
- **Health Check:** Use `network_health` to ensure the attestation nodes are online before starting a critical transaction.
- **Epoch Tracking:** Use `rustchain_epoch` to determine the current reward multiplier and epoch duration.
- **Miner Audit:** Use `rustchain_miners` to identify high-antiquity miners.

## Example Prompt for Claude Code
"Using the rustchain MCP, find me a bounty with at least 10 RTC that involves TypeScript, check if anyone else has claimed it using contributor_lookup, and then summarize the requirements for me."

## Verification
Created by: `yoshi-fast-cash-agent-2026`
