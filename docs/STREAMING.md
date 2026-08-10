
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
