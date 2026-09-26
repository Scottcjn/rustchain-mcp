# Changelog

## 0.5.0

### Breaking
- **`wallet_create` and `wallet_export` require a `password`.** Earlier
  versions fell back to the wallet ID (stored in plaintext in the same file) or
  a fixed string, so keystores only looked encrypted. The tool schemas now mark
  `password` as required, and wallet import refuses to run without one.
- **Wallet IDs must be safe filenames:** 1–128 characters of letters, digits,
  `.`, `_` and `-`, starting with a letter or digit, with no `..`. IDs that could
  name a path outside `~/.rustchain/mcp_wallets/` are rejected. Wallets imported
  by older versions under other IDs (for example with spaces) no longer load;
  rename the keystore file to a valid ID to use it again.
- Importing several wallets from keystore JSON with an explicit `wallet_id` is
  refused; each wallet keeps its own ID.

### Security
- Keystores are never overwritten. They are written under a temporary name,
  fsynced and hard-linked into place, so a crash or full disk can't leave a
  truncated keystore behind, and they are always created with mode 0600.
- TLS verification is on by default in the LangChain, CrewAI and evangelist
  clients. They read `RUSTCHAIN_TLS_VERIFY`, the same variable as the MCP
  server; the older `TLS_VERIFY` is still honoured.

### Changed
- All tools declare MCP tool annotations (read-only, destructive, idempotent,
  open-world).
- The server reports this package's version in `serverInfo`.
- Batch keystore imports report wallets that failed to write under `failed`,
  instead of stopping partway through.
- CI tests Python 3.10–3.14 and runs the onboarding-post tests again.
