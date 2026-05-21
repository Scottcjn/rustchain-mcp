# RustChain MCP Skills for Claude Code

This skill set allows Claude Code to interact with the RustChain Proof-of-Antiquity blockchain and the BoTTube AI video platform.

## Setup
1. Install the RustChain MCP server:
   ```bash
   pip install rustchain-mcp
   ```
2. Add the server to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):
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

### 1. Check Wallet Balance
To check the balance of a specific wallet:
- **Tool:** `rustchain_balance`
- **Argument:** `wallet_id="your-wallet-id"`

### 2. Search for Open Bounties
To find new ways to earn RTC:
- **Tool:** `bounty_search`
- **Argument:** `keyword="AI"`, `min_reward=10`

### 3. Monitor Network Miners
To see active miners and their antiquity multipliers:
- **Tool:** `rustchain_miners`

### 4. Create a New AI Agent Wallet
To spin up a zero-friction wallet for a new task:
- **Tool:** `rustchain_create_wallet`
- **Argument:** `agent_name="BountyHunter-01"`

### 5. Transfer RTC Tokens
To pay another agent or settle a bounty:
- **Tool:** `wallet_transfer_signed`
- **Arguments:** `from_wallet_id="my-wallet"`, `to_address="RTC..."`, `amount_rtc=5.0`
