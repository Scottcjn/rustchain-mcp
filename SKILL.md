# RustChain MCP Skill: Ecosystem Intelligence

This skill allows Claude Code to interact with the RustChain blockchain, monitor the network, and hunt for bounties.

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

## Tool-Based Workflows

### 1. Bounty Hunting & Intelligence
To identify high-value opportunities, the agent should use a strategic sequence:
- **Discovery:** Use `bounty_search` with `keyword="bug"` or `min_rtc=50` to find potential targets.
- **Analysis:** Once a bounty is identified, cross-reference with `contributor_lookup` to see if the target is already dogpiled.
- **Planning:** Use `rustchain_epoch` to determine the current reward cycle and payout window.

### 2. Wallet & Balance Management
For managing an agent's financial state on-chain:
- **Initialization:** Use `wallet_create` to generate a new RTC wallet.
- **Verification:** Use `wallet_balance` to check current holdings and confirm reward arrivals.
- **Listing:** Use `wallet_list` to manage multiple agent personas.

###  la-standard: Proof-of-Delivery Only
This skill follows the la-standard for agent deliverables.

## Wallet for Testing
For verification purposes, this example was created using the wallet: `yoshi-bounty-hunter-2026`
