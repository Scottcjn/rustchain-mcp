# RustChain Event Relay and Progressive Results

The event relay polls three read-only RustChain node endpoints and turns source
state transitions into cursor-addressable events:

- `GET /health`
- `GET /epoch`
- `GET /api/miners`

It never calls a blockchain write endpoint. Initial successful reads produce
`*.snapshot` events. Later changes produce `*.changed`; failures produce
`*.unavailable`; the next successful read produces `*.recovered`. Miner lists
are canonically sorted so an upstream ordering change alone does not create an
event.

## Direct Answer for Issue #231

`rustchain_events` does **not** stream partial miner results from one MCP tool
call. This implementation does not claim native MCP tool streaming support.
Instead, the tool implements MCP-compatible progressive consumption using
ordinary bounded results:

1. Call `rustchain_events(after_cursor=0, limit=50)`.
2. Process the returned `events` in cursor order.
3. Call it again with `after_cursor` set to the returned `next_cursor`.
4. Set `wait_seconds` to a positive value for a bounded long poll when caught up.

Each miner event contains a normalized miner snapshot rather than item-by-item
partial tool output. `has_more` means another batch is immediately available.
`timed_out` means a long poll completed without a new event.

The standalone `rustchain-event-relay` command offers an SSE endpoint for
non-MCP event consumers. That endpoint is a separate HTTP service, not an MCP
transport and not evidence of native MCP tool streaming.

## Cursor Contract

Cursors are strictly increasing integers scoped to one relay process. Events are
held in a fixed-size in-memory ring and are not persisted across restarts.

The MCP result includes:

| Field | Meaning |
|-------|---------|
| `events` | Events after the requested cursor, up to `limit` |
| `next_cursor` | Cursor to send in the next call |
| `oldest_cursor` | Oldest cursor still retained, or 0 before the first event |
| `latest_cursor` | Newest cursor observed by this process |
| `has_more` | More retained events exist after `next_cursor` |
| `cursor_expired` | Requested history was evicted; batch starts at the oldest retained event |
| `timed_out` | No event arrived within the requested long-poll duration |
| `stopped` | Relay shutdown has been requested |
| `native_mcp_streaming` | Always `false` |

A cursor greater than `latest_cursor` is rejected. When `cursor_expired` is
true, the consumer should treat the response as a detectable history gap and
reconcile current state if it requires lossless processing.

## MCP Tool

The event poller starts lazily on the first `rustchain_events` call. It does not
open the SSE listener.

```text
rustchain_events(
    after_cursor: int = 0,
    limit: int = 50,
    wait_seconds: float = 0.0,
)
```

The configured maximums are 100 events and 30 seconds by default. Invalid or
future cursors return an `INVALID_EVENT_CURSOR_REQUEST` error object.

## Standalone SSE

Start the loopback listener:

```bash
rustchain-event-relay
```

Consume from the beginning of retained history:

```bash
curl -N http://127.0.0.1:8766/events?cursor=0\&limit=50
```

Resume with either `cursor` or the standard `Last-Event-ID` header:

```bash
curl -N -H 'Last-Event-ID: 42' http://127.0.0.1:8766/events
```

SSE records use the cursor as `id`, the normalized type as `event`, and the
whole canonical event object as `data`. If retained history was missed, the
server first emits a `rustchain.cursor.expired` control event. Heartbeat comments
keep idle connections alive. `GET /healthz` reports process-local relay status.

The command also accepts `--node-url`, `--host`, `--port`, `--poll-interval`,
`--request-timeout`, `--buffer-size`, `--max-clients`, `--allow-remote`, and
`--log-level`. Run `rustchain-event-relay --help` for exact syntax.

## Configuration

| Variable | Default | Bounds or behavior |
|----------|---------|--------------------|
| `RUSTCHAIN_NODE` | `https://50.28.86.131` | Absolute HTTP(S) URL without credentials, query, or fragment |
| `RUSTCHAIN_TLS_VERIFY` | `true` | TLS verification toggle |
| `RUSTCHAIN_CA_BUNDLE` | unset | CA bundle path, overrides TLS toggle |
| `RUSTCHAIN_EVENT_POLL_INTERVAL` | `5` | 0.05 to 3600 seconds |
| `RUSTCHAIN_EVENT_REQUEST_TIMEOUT` | `5` | 0.05 to 120 seconds |
| `RUSTCHAIN_EVENT_BACKOFF_INITIAL` | `1` | Initial failure retry delay |
| `RUSTCHAIN_EVENT_BACKOFF_MAX` | `60` | Capped exponential retry delay, at most 3600 seconds |
| `RUSTCHAIN_EVENT_BUFFER_SIZE` | `256` | 1 to 100,000 retained events |
| `RUSTCHAIN_EVENT_BATCH_LIMIT` | `100` | 1 to 1,000 events per result |
| `RUSTCHAIN_EVENT_LONG_POLL_MAX` | `30` | 0 to 120 seconds |
| `RUSTCHAIN_EVENT_RESPONSE_BYTES` | `131072` | Maximum bytes accepted from one source response |
| `RUSTCHAIN_EVENT_SSE_HOST` | `127.0.0.1` | Listener address |
| `RUSTCHAIN_EVENT_SSE_PORT` | `8766` | Listener port |
| `RUSTCHAIN_EVENT_SSE_MAX_CLIENTS` | `16` | Concurrent SSE connection ceiling |
| `RUSTCHAIN_EVENT_SSE_HEARTBEAT` | `15` | Idle heartbeat interval |
| `RUSTCHAIN_EVENT_SSE_WRITE_TIMEOUT` | `30` | Slow-client write timeout |
| `RUSTCHAIN_EVENT_ALLOW_REMOTE` | `false` | Explicit non-loopback opt-in |
| `RUSTCHAIN_EVENT_TOKEN` | unset | Bearer token; required for non-loopback binds |

Backoff is deterministic, exponential, and capped. Any failed source triggers
the cycle backoff; all three fixed sources are still attempted on every cycle.

## Security Notes

- The event poller contains no POST, PUT, PATCH, DELETE, transfer, signing, or
  wallet operation.
- The node URL is an operator-controlled trust boundary. Redirects are disabled,
  source paths are fixed, credentials in the URL are rejected, and response size
  is bounded.
- TLS verification is on by default. Disabling it permits man-in-the-middle
  modification of observed state and should be limited to trusted test networks.
- The SSE listener is loopback-only by default and sends no CORS header. A
  non-loopback bind requires `--allow-remote` and a token of at least 16
  characters. Supply the token as `Authorization: Bearer ...`; URL tokens are
  not accepted.
- `/events` can reveal miner and node state. Put remote deployments behind an
  authenticated TLS reverse proxy even when relay bearer authentication is on.
- Memory, source response size, MCP batch size, long-poll duration, concurrent
  SSE clients, and slow-client writes are bounded. The default retained payload
  ceiling is approximately 32 MiB before Python object overhead.
- SIGINT and SIGTERM stop polling, wake blocked long polls, close the listener,
  and close the relay-owned HTTP client.

## Balance Endpoint

The MCP balance tools use the canonical read-only endpoint:

```http
GET /wallet/balance?miner_id=MINER_OR_WALLET_ID
```

Successful responses preserve the node's `amount_rtc` field. Missing
`amount_rtc` is a verification error and is not converted into a zero balance.
