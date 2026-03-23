# RustChain MCP Skill

Query miners, check balances, and browse bounties on the RustChain
Proof-of-Antiquity blockchain via the `rustchain-mcp` MCP server.

## Setup

Install the MCP server:

```bash
pip install rustchain-mcp
```

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "rustchain": {
      "command": "rustchain-mcp"
    }
  }
}
```

Restart Claude Desktop. The 25 RustChain/BoTTube/Beacon tools will appear automatically — no API key required for read-only operations.

## Querying Miners

Ask Claude:

> "Show me all active RustChain miners"

Claude will call `rustchain_miners` and return each miner's wallet address, hardware type, and antiquity multiplier. Vintage hardware earns more:

| Hardware | Multiplier |
|----------|-----------|
| Apple G4 | 2.5× |
| Apple G5 | 2.0× |
| Apple Silicon | 1.2× |
| Modern x86_64 | 1.0× |

Example follow-up:

> "Which miner has the highest antiquity multiplier?"

## Checking Balances

Ask Claude:

> "What is the RTC balance for wallet dual-g4-125?"

Claude will call `rustchain_balance(wallet_id="dual-g4-125")` and return the balance in RTC tokens (reference rate: $0.10 USD per RTC).

You can also check your own wallet:

> "Create a wallet for my agent called my-research-bot, then show its balance"

Claude will call `rustchain_create_wallet` followed by `rustchain_balance`.

## Browsing Bounties

Ask Claude:

> "What bounties are available on RustChain?"

Claude will call `rustchain_bounties` and list open earning opportunities:

- **Code contributions:** 5–500 RTC
- **Security audits:** 100–200 RTC
- **Documentation:** 5–50 RTC
- **Integration plugins:** 75–150 RTC
- **Bug fixes:** 10–100 RTC

To claim a bounty, comment on the relevant GitHub issue and submit a PR. Include your RTC wallet address (format: `RTC...`) in the PR body.

## Network Stats

> "Show RustChain network stats"

Claude calls `rustchain_stats` — returns total miners, current epoch info, reward distribution, and network health.

## Example Session

```
You: Show me the top 5 miners by antiquity multiplier

Claude: I'll query the active miners for you.
[calls rustchain_miners]

Here are the top 5 miners ranked by antiquity multiplier:

1. dual-g4-125 — Apple G4 (2.5×) — last attested 2h ago
2. g5-quad-tower — Apple G5 (2.0×) — last attested 4h ago
...

You: Check the balance for dual-g4-125

Claude: [calls rustchain_balance(wallet_id="dual-g4-125")]

Wallet dual-g4-125 holds 1,240.5 RTC (~$124 USD at reference rate).

You: What bounties can I work on to earn RTC?

Claude: [calls rustchain_bounties]

Active bounties on RustChain GitHub:
- Code contributions: 5–500 RTC
- Bug fixes: 10–100 RTC
...
23,300+ RTC paid out to 218 recipients so far.
```

## Wallet

Drop your RTC wallet address in any PR you submit for bounties:

```
rtc wallet: RTC2fe3c33c77666ff76a1cd0999fd4466ee81250ff
```

## Links

- [RustChain](https://rustchain.org)
- [Bounties](https://github.com/Scottcjn/rustchain-bounties)
- [MCP server source](https://github.com/Scottcjn/rustchain-mcp)
- [PyPI package](https://pypi.org/project/rustchain-mcp/)
