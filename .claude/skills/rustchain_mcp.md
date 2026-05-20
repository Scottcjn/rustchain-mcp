# Claude Code Skill Example: RustChain MCP

This skill allows Claude to interact with the RustChain blockchain and BoTTube platform.

## Setup
Ensure the `rustchain-mcp` server is installed and configured in your MCP settings.

## Example Skill Definitions

### 1. Check RTC Balance
- **Tool:** `rustchain_balance`
- **Goal:** Get the current RTC token balance for a specific wallet.
- **Example:** "Check the RTC balance for wallet RTCa1b2c3d4..."

### 2. Monitor Network Miners
- **Tool:** `rustchain_miners`
- **Goal:** List active miners to analyze hardware types and antiquity multipliers.
- **Example:** "Who are the top miners on RustChain right now?"

### 3. Hunt Bounties
- **Tool:** `bounty_search`
- **Goal:** Find open bounties to earn RTC.
- **Example:** "Search for open RustChain bounties with a reward of at least 100 RTC."

### 4. Wallet Management
- **Tool:** `rustchain_create_wallet`
- **Goal:** Create a zero-friction wallet for a new AI agent.
- **Example:** "Create a new RustChain wallet for the 'BountyHunter-Alpha' agent."

