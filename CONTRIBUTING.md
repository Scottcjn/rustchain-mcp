# Contributing to rustchain-mcp

Thanks for helping improve `rustchain-mcp`, the MCP server for RustChain, BoTTube, and Beacon.

## Development Setup

Prereqs:

- Python 3.10+
- Git

Steps:

1. Fork the repo on GitHub.
2. Clone your fork locally.
3. Create and activate a virtualenv.
4. Install in editable mode:

```bash
python -m pip install -e .
```

## Run Locally

Start the MCP server:

```bash
rustchain-mcp
```

Or run the module directly:

```bash
python -m rustchain_mcp.server
```

Useful environment variables (see `README.md` for the full list):

```bash
export RUSTCHAIN_NODE="https://rustchain.org"
export BOTTUBE_URL="https://bottube.ai"
export BEACON_URL="https://rustchain.org/beacon"
```

## Making Changes

Guidelines:

- Prefer small, focused PRs.
- Avoid changing API/behavior without a clear rationale in the PR description.
- Do not commit secrets (API keys, private keys, tokens).

Quick sanity checks:

```bash
python -m py_compile rustchain_mcp/server.py
```

## Pull Request Checklist

- Explain what changed and why.
- Include validation steps (example commands and outputs, screenshots when relevant).
- If you touched network calls, mention which endpoints were tested.

## Reporting Issues / Security

- Bugs and feature requests: open a GitHub issue.
- Security concerns: please avoid disclosing details publicly; contact the maintainers via a private channel if available.

