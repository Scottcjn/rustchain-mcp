# RustChain MCP Skill Example

This skill enables Claude Code to interact with the RustChain ecosystem to find bounties, manage wallets, and monitor the blockchain.

## Setup

1. **Install the MCP Server**
   ```bash
   pip install rustchain-mcp
   ```

2. **Configure Claude Desktop/Code**
   Add the following to your configuration:
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

## Example Workflows

### 1. Hunting for Bounties
To find a high-reward bounty in the RustChain ecosystem, the agent should:
- Use `bounty_search` with `keyword="bug"` or `min_rtc=100`.
- Analyze the resulting issues to determine feasibility.
- Use `contributor_lookup` to check if other contributors are already active.

### 2. Wallet & Balance Management
To manage earnings and check status:
- Use `wallet_create` to initialize a new agent wallet.
- Use `wallet_balance` to check the current RTC balance.
- Use `wallet_list` to see all stored wallets.

### 3. Network Monitoring
To check the health of the decentralized infrastructure:
- Use `network_health` to verify all four attestation nodes are reachable.
- Use `rustchain_epoch` to track the current reward cycle.

## Wallet for Testing
For verification purposes, this example was created using the wallet: `yoshi-bounty-hunter-2026`
