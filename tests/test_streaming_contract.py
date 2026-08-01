"""Contract tests pinning down rustchain-mcp streaming / long-running behavior.

Answers rustchain-mcp#231: the server does NOT stream results and does NOT
emit MCP progress notifications. Tools are synchronous, blocking callables
that return a single completed result. These tests fail if streaming /
progress support is later added (i.e. the documented capability claim is
flipped), which is exactly what the bounty requires.
"""

import asyncio
import inspect
import time
from unittest.mock import MagicMock

from rustchain_mcp import server


def _all_tool_fns():
    """Return {name: underlying_callable} for every registered MCP tool."""
    tools = asyncio.run(server.mcp.list_tools())
    return {t.name: t.fn for t in tools}


def test_no_tool_accepts_progress_context():
    """No tool takes a `ctx`/`context` param, so none can emit progress.

    FastMCP only reports `notifications/progress` when a tool accepts a
    `Context` argument and calls `ctx.report_progress(...)`. Asserting the
    absence of such a parameter proves the server cannot stream progress.
    """
    for name, fn in _all_tool_fns().items():
        params = list(inspect.signature(fn).parameters.keys())
        assert not any(p in ("ctx", "context") for p in params), (
            f"Tool '{name}' accepts a progress context ({params}); "
            "this contradicts the documented 'no streaming/progress' behavior"
        )


def test_no_tool_is_a_generator_or_async_generator():
    """Streaming tools would be generators/async-generators; ours are not.

    A streaming tool yields partial results; a blocking tool returns a single
    value. Asserting no tool is a generator pins the blocking contract.
    """
    for name, fn in _all_tool_fns().items():
        assert not (inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn)), (
            f"Tool '{name}' is a generator — it would stream partial results, "
            "contradicting the documented blocking behavior"
        )


def test_server_advertises_no_experimental_streaming_capability():
    """The server exposes no experimental capability flag for streaming."""
    assert getattr(server.mcp, "experimental_capabilities", None) == {}, (
        "experimental_capabilities is non-empty; streaming may be advertised"
    )


def test_slow_tool_blocks_until_complete_and_returns_single_result():
    """A slow upstream call blocks the tool until the full result is ready.

    We mock the shared httpx client so GET /health is slow, then assert the
    tool returns exactly one completed dict after the full delay (never a
    partial/early result). If the server streamed, this would return early or
    yield progress instead of a single result.
    """
    payload = {"status": "ok", "version": "1.2.3"}

    def _slow_get(url, **kwargs):
        time.sleep(0.25)
        resp = MagicMock()
        resp.status_code = 200
        resp.json = lambda: dict(payload)
        resp.raise_for_status = lambda: None
        return resp

    fake = MagicMock()
    fake.get.side_effect = _slow_get

    saved = server._client
    server._client = fake
    try:
        start = time.perf_counter()
        result = server.rustchain_health()
        elapsed = time.perf_counter() - start
    finally:
        server._client = saved

    # Blocked for (at least) the full upstream delay -> single blocking call.
    assert elapsed >= 0.2, (
        f"tool returned early ({elapsed:.3f}s); expected to block ~0.25s"
    )
    # Single completed result, not a stream/partial.
    assert isinstance(result, dict), f"expected a single dict result, got {type(result)}"
    assert result.get("status") == "ok"
    # Exactly one upstream GET happened (no partial chunking / progress polling).
    assert fake.get.call_count == 1
