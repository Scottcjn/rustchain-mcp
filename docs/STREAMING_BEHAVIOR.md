# Streaming & Long-Running Tool Behavior

rustchain-mcp is an MCP server that exposes RustChain, BoTTube, and Beacon
tools. This document describes how streaming, timeouts, cancellation, and
error states behave for long-running operations.

## MCP Protocol Streaming

The MCP protocol natively supports:
- **Tool execution streaming** — results are returned when complete
- **Progress notifications** — not yet implemented (see below)
- **Cancellation** — client-initiated abort of in-progress tools (handled by
  the MCP transport layer)

## Timeout Configuration

All HTTP requests use `httpx` with a configurable timeout:

| Variable | Default | Description |
|---|---|---|
| `RUSTCHAIN_TIMEOUT` | 30s | HTTP request timeout for all RPC calls |
| `RUSTCHAIN_NODE` | https://50.28.86.131 | RustChain node URL |
| `RUSTCHAIN_CA_BUNDLE` | true | TLS verification (true/false/path) |

To increase the timeout for slow nodes or large responses:

```bash
RUSTCHAIN_TIMEOUT=60 python -m rustchain_mcp
```

## Tool Timeout Behavior

| Tool Category | Typical Latency | Timeout | Behavior on Timeout |
|---|---|---|---|
| Balance/read tools | <1s | 30s | `httpx.TimeoutException` → MCP error response |
| Transfer tools | 1-5s | 30s | `httpx.TimeoutException` → transfer NOT submitted |
| Bounty search | 1-3s | 30s | Returns partial results or timeout error |
| BoTTube video list | 1-3s | 30s | Partial results or timeout error |
| Beacon messaging | 1-5s | 30s | Timeout → message may or may not be delivered |

## Error Response Format

All tools return errors in a consistent format via MCP:

```json
{
    "error": "human-readable message",
    "tool": "tool_name",
    "input": { ... }
}
```

Common error scenarios:

| Scenario | Error | Retryable |
|---|---|---|
| Node unreachable | `Connection refused` | Yes |
| Node timeout | `Request timed out after 30s` | Yes |
| Invalid wallet | `Wallet not found` | No |
| Invalid address | `Invalid RTC address format` | No |
| Transfer fail | `Insufficient balance` | No |
| Network error | `DNS resolution failed` | Yes |

## Progress Reporting

Progress notifications are not yet implemented. Long-running tools
(transfers, balance checks on slow nodes) block until completion or
timeout. Future versions may add `@mcp.tool(progress=True)` for:

- Wallet creation (signing operations)
- Balance check aggregation across multiple nodes
- Bounty search across multiple repositories

## Cancellation

MCP client-initiated cancellation stops tool execution at the transport
layer. The RustChain node may still process a submitted transfer even if
the MCP client cancels — cancellation only stops waiting for the response.
This is a known limitation; clients should use idempotency keys for
transfers where this matters.

## Best Practices

1. **Set appropriate timeouts** — increase `RUSTCHAIN_TIMEOUT` for slow
   remote nodes.
2. **Retry on network errors** — transient failures are safe to retry.
3. **Verify after timeout** — if a transfer times out, check the balance
   before retrying to avoid double-submission.
4. **Use short-lived wallets** — generate wallets per-session for safety.


## Long-Running Tool Behavior (Detailed)

### Current Status
| Feature | Status |
|---------|--------|
| MCP tool execution | Complete |
| HTTP timeout control | Complete |
| Error response format | Complete |
| Transport cancellation | Complete |
| Input validation | Complete |

### Planned Features
| Feature | Status |
|---------|--------|
| Progress notifications | Planned |
| SSE streaming | Planned |
| Partial results | Planned |
| Idempotency keys | Planned |

### Known Limitations
1. No real streaming - all tools are request-response
2. No progress notifications - long ops appear to hang
3. No partial results - single source failure may fail entire call
4. Blocking I/O - synchronous httpx calls

### Answer to #231
rustchain-mcp does NOT currently support real streaming or progressive results.
All tools return results only when fully complete.
