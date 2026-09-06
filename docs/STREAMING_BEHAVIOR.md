# Streaming & Long-Running Tool Behavior

rustchain-mcp is an MCP server that exposes RustChain, BoTTube, and Beacon
tools. This document describes how streaming, timeouts, cancellation, and
error states behave for long-running operations, with references to the
actual source code.

**Status: Streaming/progress is NOT implemented. All tools are blocking.**

---

## Execution Model

All 37 tools are synchronous Python functions (`def`, not `async def`). Each
tool obtains an `httpx.Client` via the module-level `get_client()` function
and makes a plain blocking HTTP call:

```python
# Every tool in rustchain_mcp/server.py follows this pattern
# (references: lines 86–906, all tool implementations)
r = get_client().get(f"{RUSTCHAIN_NODE}/api/endpoint")
r.raise_for_status()
return r.json()
```

- **No streaming** — results arrive only when the full HTTP response arrives.
- **No `Context.report_progress()`** — none of the tools accept a `Context`
  parameter, so FastMCP progress notifications are never sent. See
  `tests/test_streaming.py::test_no_tools_use_context` for verification.

**Code references:**
| Aspect | File | Lines |
|---|---|---|
| Module config (timeout, node URL) | `rustchain_mcp/server.py` | 34–38 |
| `get_client()` (shared httpx.Client) | `rustchain_mcp/server.py` | 64–68 |
| All tool implementations | `rustchain_mcp/server.py` | 86–906 |
| Error handler (`_handle_api_error`) | `rustchain_mcp/server.py` | 71–77 |
| No tool uses Context | `tests/test_streaming.py` | 132–171 |
| All tools are synchronous | `tests/test_streaming.py` | 231–253 |

---

## Timeout Configuration

All HTTP requests use `httpx` with a configurable timeout. The module-level
`RUSTCHAIN_TIMEOUT` variable controls the default (30s). Individual tools
can override with per-request timeouts (e.g., `network_health` uses 10s per
node, `green_tracker` uses 15s).

| Variable | Default | Description | Reference |
|---|---|---|---|
| `RUSTCHAIN_TIMEOUT` | 30 | HTTP request timeout in seconds for all RPC calls | `server.py` line 38 |
| `RUSTCHAIN_NODE` | https://50.28.86.131 | RustChain node URL | `server.py` line 35 |
| `RUSTCHAIN_CA_BUNDLE` | true | TLS verification (true/false/path) | `server.py` lines 53–58 |

To increase the timeout for slow nodes or large responses:

```bash
RUSTCHAIN_TIMEOUT=60 python -m rustchain_mcp
```

---

## Tool Timeout Behavior

| Tool Category | Typical Latency | Timeout | Behavior on Timeout | Code Reference |
|---|---|---|---|---|
| Read tools (balance, health, epoch) | <1s | 30s | `httpx.TimeoutException` → error | `server.py` line 67 |
| Transfer tools | 1–5s | 30s | `httpx.TimeoutException` → not submitted | `server.py` line 67 |
| Bounty search | 1–3s | 30s | Returns partial (empty) results | `server.py` line 1042–1051 |
| Network health (4 nodes) | 3–10s | 10s per node | Skips failed nodes, returns partial | `server.py` line 1192 |
| Green tracker | 1–15s | 15s | Falls back to known fleet data | `server.py` line 1239 |

Exception propagation:
- `httpx.TimeoutException` — raised when the server doesn't respond within
  `RUSTCHAIN_TIMEOUT` seconds. This propagates through FastMCP and surfaces
  as an MCP error message.
- `httpx.ConnectError` — raised when the host is unreachable.
- `httpx.HTTPStatusError` — caught by tools and converted to structured
  error dicts (see Error Response Format below).

---

## Error Response Format

When an HTTP endpoint returns a non-success status, tools use
`_handle_api_error()` to produce a human-readable error string:

```python
# rustchain_mcp/server.py lines 71–77
def _handle_api_error(response: httpx.Response) -> str:
    try:
        error_data = response.json()
        return error_data.get("error") or error_data.get("message")
            or f"HTTP {response.status_code}"
    except Exception:
        return f"HTTP {response.status_code}: {response.text[:200]}"
```

Tools return errors as dicts with `"error"` and `"status"` keys:

```json
{"error": "Wallet not found", "status": "error"}
```

Common error scenarios:

| Scenario | Error | Retryable | Code Reference |
|---|---|---|---|
| Node unreachable | `MaxRetryError` / `ConnectError` | Yes | httpx default |
| Node timeout | `TimeoutException` after 30s | Yes | `server.py` line 67 |
| Invalid wallet | `{"error": "Wallet not found", ...}` | No | `server.py` lines 93–98 |
| Invalid address | `{"error": "Invalid RTC address format", ...}` | No | Upstream node |
| Insufficient balance | `{"error": "Insufficient balance", ...}` | No | Upstream node |
| Network error | DNS / TLS failure | Yes | httpx default |

---

## Capability Advertisement

The MCP server's `InitializeResult` does **not** advertise streaming or
progress capabilities:

```python
# rustchain_mcp/server.py lines 41–50
mcp = FastMCP(
    "RustChain + BoTTube + Beacon",
    instructions=(...),
    # No experimental_capabilities for streaming or progress
)
```

- No `"streaming"` or `"progress"` key in `experimental_capabilities`
  (verified in `tests/test_streaming.py::test_server_capabilities_no_streaming`).
- The FastMCP `ToolsCapability` only supports `listChanged`
  (reference: `mcp.types.ToolsCapability` model).
- MCP progress notifications (`notifications/progress`) are never sent.

---

## Progress Reporting

FastMCP 3.4+ provides `Context.report_progress()` for sending MCP
`notifications/progress` to clients. **rustchain-mcp does not use this.**
Adding progress reporting requires:

1. Adding a `ctx: Context` parameter to the tool function
2. Calling `ctx.report_progress(current, total, message)` during execution

No existing tool does this (verified by
`tests/test_streaming.py::test_no_tools_use_context`).

Future implementations should annotate tools with `progress=True` and
follow the FastMCP progress pattern.

---

## Cancellation

MCP client-initiated cancellation stops waiting for the HTTP response at the
transport layer (FastMCP handles this). However, the upstream
RustChain/BoTTube/Beacon node may still process a submitted request —
especially transfers where `POST /wallet/transfer/signed` has already been
accepted by the node — even if the MCP client cancels the response wait.

This is standard MCP transport behavior: cancellation only severs the
local connection, not the upstream operation.

**Recommendations:**

1. **Set appropriate timeouts** — increase `RUSTCHAIN_TIMEOUT` for slow
   remote nodes.
2. **Retry on network errors** — transient failures are safe to retry.
3. **Verify after timeout** — if a transfer times out, check the balance
   before retrying to avoid double-submission.
4. **Use idempotency keys** — for critical operations, include a nonce
   (the `wallet_transfer_signed` tool already uses timestamp-based nonces
   at `server.py` lines 292–299).

---

## Test Coverage

| Test | File | What It Asserts |
|---|---|---|
| `test_timeout_config_respected` | `tests/test_streaming.py` | Timeout env var is read correctly |
| `test_timeout_default_value` | `tests/test_streaming.py` | Default timeout is 30 |
| `test_get_client_timeout_propagates` | `tests/test_streaming.py` | httpx.Client uses module timeout |
| `test_timeout_raises_exception` | `tests/test_streaming.py` | Timeout → exception |
| `test_connection_refused_raises_exception` | `tests/test_streaming.py` | Connection refused → exception |
| `test_http_error_formatting` | `tests/test_streaming.py` | Error responses formatted correctly |
| `test_no_tools_use_context` | `tests/test_streaming.py` | No tool uses Context (no progress) |
| `test_server_capabilities_no_streaming` | `tests/test_streaming.py` | No streaming capability advertised |
| `test_all_tools_use_blocking_httpx_calls` | `tests/test_streaming.py` | All tools are synchronous |

---

## Adding Streaming Support (Future Work)

To add streaming or progress to a tool in the future:

1. Add `from fastmcp import Context` import
2. Accept `ctx: Context` as a parameter in the tool function
3. Call `ctx.report_progress(current, total, message)` at intervals
4. (Optional) Use `async def` and `httpx.AsyncClient` for true streaming

Example:

```python
from fastmcp import FastMCP, Context

mcp = FastMCP("my-server")

@mcp.tool()
def long_running_tool(ctx: Context, param: str) -> dict:
    ctx.report_progress(0, 10, "Starting")
    # ... step 1 ...
    ctx.report_progress(3, 10, "Step 1 complete")
    # ... step 2 ...
    ctx.report_progress(7, 10, "Step 2 complete")
    # ... step 3 ...
    ctx.report_progress(10, 10, "Done")
    return {"status": "complete"}
```

This would send `notifications/progress` to MCP clients that support it
(e.g., Claude Code with SSE transport).

---

*Documented for Bounty #16255 (8 RTC). Last updated: July 26, 2026.*
