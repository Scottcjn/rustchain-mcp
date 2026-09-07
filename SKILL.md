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
         "command": "rustchain-mcp"
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

### 3. Progressive Network Monitoring
Use `rustchain_events` to consume bounded health, epoch, and miner change
batches. Save `next_cursor`, request again with that value, and use a positive
`wait_seconds` only when a bounded long poll is useful. This MCP tool does not
stream partial miners from one call and does not claim native MCP tool streaming.
The separate `rustchain-event-relay` command provides SSE to non-MCP consumers.

###  la-standard: Proof-of-Delivery Only
This skill follows the la-standard for agent deliverables.

## Wallet for Testing
For verification purposes, this example was created using the wallet: `yoshi-bounty-hunter-2026`


## Streaming and long-running tool behavior

**Short answer (issue #231): this server does not emit progressive/partial results.** Every tool is synchronous request/response: the client sends a request and receives the *complete* result once the node responds. There is no SSE, no incremental chunks, and no per-tool `progress` callback.

### What that means in practice

- A call to a slow tool (e.g. `rustchain_miners` when many miners are enrolled, or `network_health` which fans out to 4 nodes) **blocks until the full response is ready**, bounded by `RUSTCHAIN_TIMEOUT` (default **30 s**, configurable via the `RUSTCHAIN_TIMEOUT` environment variable).
- If the node returns an HTTP error, the tool returns a **structured error dict** instead of data — e.g. `{"status": "error", "error": "<server diagnostic>"}`. The server never fabricates an empty "success" result.
- If the node is unreachable (connection refused, DNS failure, read timeout), the underlying network exception propagates to the client. Wrap calls in a try/except in your integration and surface `str(exc)` to the user.
- Results are **bounded** for large payloads (e.g. `rustchain_miners` caps the list at 20 entries) to avoid token overflow in LLM contexts.

### Building a real-time dashboard anyway

Because the MCP protocol supports concurrent tool calls, the recommended pattern for "progressive" UIs is client-side:

1. Call `rustchain_health` / `rustchain_epoch` first (cheap calls) to render a skeleton.
2. Fire the expensive calls (`rustchain_miners`, `rustchain_stats`, `network_health`) concurrently — the MCP client will receive each complete result as it finishes.
3. Re-poll on your own cadence (e.g. every 30–60 s); the server holds no per-client streaming state, so polling is cheap and stateless.

### If you need true streaming

`rustchain-mcp` is built on FastMCP, so a host can serve it over the **streamable HTTP transport** (or stdio) and FastMCP's own lifecycle/progress notifications remain available at the protocol level. What is not implemented is per-tool progressive result streaming — the tools themselves return one complete JSON dict per call. Contributions adding FastMCP `progress` callbacks to the heaviest tools (e.g. `network_health`, `beacon_discover`) are welcome.
