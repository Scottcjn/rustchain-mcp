"""Regression test for the documented per-tool progress contract."""

from __future__ import annotations

import inspect

import pytest

from rustchain_mcp import server


def _is_context_parameter(parameter: inspect.Parameter) -> bool:
    """Return whether a function parameter is an MCP/FastMCP Context."""
    annotation = parameter.annotation
    annotation_name = getattr(annotation, "__name__", str(annotation))
    return parameter.name in {"ctx", "context"} or annotation_name.endswith("Context")


@pytest.mark.asyncio
async def test_registered_tools_have_no_context_progress_parameter():
    """Every currently registered tool is request/response, not progress-reporting.

    FastMCP 3.4+ exposes registered tools through public list_tools/get_tool APIs.
    Inspecting each public FunctionTool's callable avoids the old private
    _tool_manager dependency while enforcing the same contract as
    ``context_kwarg is None`` in older MCP/FastMCP implementations.
    """
    listed = await server.mcp.list_tools()
    assert listed, "expected registered MCP tools"

    offenders = []
    for listed_tool in listed:
        tool = await server.mcp.get_tool(listed_tool.name)
        assert tool is not None, listed_tool.name
        signature = inspect.signature(tool.fn)
        if any(_is_context_parameter(p) for p in signature.parameters.values()):
            offenders.append(listed_tool.name)

    assert offenders == [], (
        "README says built-in tools do not emit per-tool progress; "
        f"Context-enabled tools found: {offenders}"
    )
