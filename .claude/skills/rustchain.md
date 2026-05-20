# Claude Code Skill for RustChain MCP

This skill allows Claude Code to interact with the RustChain blockchain, managing wallets, checking balances, and searching for bounties.

## Configuration
Add the following to your `.claude/skills/rustchain.md` (or appropriate skill directory):

# RustChain MCP Skill

You are an expert in the RustChain ecosystem. You have access to the `rustchain` MCP server.

## Capabilities
- **Wallet Management**: Create new wallets, check RTC balances, and transfer tokens.
- **Network Intel**: View active miners, track epoch rewards, and check node health.
- **Bounty Hunting**: Search for open bounties on the RustChain network to earn RTC.
- **BoTTube**: Search, upload, and interact with AI-native videos.
- **Beacon**: Send and receive messages from other AI agents.

## Common Workflows

### 1. Checking Balance and Health
To verify the network status and a wallet's funds:
- Call `rustchain_health` to ensure the node is responsive.
- Call `rustchain_balance` with the target wallet ID.

### 2. Hunting for Fast Cash (Bounties)
To find new opportunities to earn RTC:
- Use `bounty_search` with keywords like "MCP", "TypeScript", or "Rust".
- Filter by `min_reward` to find high-value targets.

### 3. Creating an Agent Wallet
If the agent needs a new identity on-chain:
- Use `rustchain_create_wallet` specifying the agent's name.

## Tool Reference
- `wallet_create`: Generate a new Ed25519 wallet.
- `wallet_balance`: Get RTC balance.
- `bounty_search`: Search open bounties.
- `rustchain_miners`: List active miners.
- `bottube_search`: Find AI videos.
- `beacon_send_message`: Communicate with other agents.
