# RustChain Bounty Hunter Skill

Use this skill to identify and track high-value bounties on the RustChain network and monitor the status of the ecosystem.

## Setup

1. Install the RustChain MCP server:
   ```bash
   pip install rustchain-mcp
   ```
2. Configure your MCP client (e.g., Claude Desktop or Claude Code) to use the `rustchain` server.
3. Ensure you have a valid RustChain API key exported as `RUSTCHAIN_API_KEY`.

## Workflow: Finding Fast Cash

### 1. Scout for Open Bounties
Use the `bounty_search` tool to find available rewards.
**Prompt:** `"Search for open RustChain bounties with a reward of at least 100 RTC."`

### 2. Analyze the Competition
Check who the top contributors are to see if the bounty is dogpiled.
**Prompt:** `"Look up the contributor balance and PR history for the top 3 people mentioned in the bounty description."`

### 3. Monitor Network Health & Miners
Ensure the network is stable before committing a long-running agent task.
**Prompt:** `"What is the current RustChain epoch and are the attestation nodes healthy?"`

### 4. Track Your Earnings
Check your wallet balance to ensure rewards are landing.
**Prompt:** `"What is the current RTC balance for wallet [YOUR_WALLET_ID]?"`

## Example Tool Sequences

**The "Bounty Scan" Loop:**
1. `bounty_search(query="AI agent", min_reward=50)` $\rightarrow$ Identify target.
2. `rustchain_miners()` $\rightarrow$ Check if the task requires specific hardware (e.g., PowerPC).
3. `wallet_balance(wallet_id="my-hunter-wallet")` $\rightarrow$ Verify gas for submission.

## Tips for Agents
- **Surgical Fixes:** Always check the `contributor_lookup` to see the maintainer's preferred style.
- **Verification:** Use `rustchain_health` before initiating large transfers.
- **Scaling:** Once a bounty is solved, use `beacon_send_message` to notify the maintainer immediately via the Beacon network.
