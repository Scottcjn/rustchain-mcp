"""RustChain + BoTTube MCP Server — AI agent tools for the RustChain blockchain and BoTTube video platform."""

__version__ = "0.4.0"

# Re-export the FastMCP server instance so it can be used programmatically:
#     from rustchain_mcp import mcp
#     mcp.run()
# This is the same object the ``rustchain-mcp`` console script runs
# (see [project.scripts] in pyproject.toml -> rustchain_mcp.server:mcp.run).
from .server import mcp

__all__ = ["mcp", "__version__"]
