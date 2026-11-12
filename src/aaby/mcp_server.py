"""Read-only local MCP server; run using aaby-mcp (stdio transport)."""
from mcp.server.fastmcp import FastMCP

from aaby.knowledge import read_instruction, search_instructions

mcp = FastMCP("aaby-knowledge")
mcp.tool()(search_instructions)
mcp.tool()(read_instruction)


def main():  # pragma: no cover
    mcp.run(transport="stdio")

