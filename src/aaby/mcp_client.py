import json
import sys
from contextlib import asynccontextmanager
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from aaby.errors import AgentError


class MCPKnowledge:
    """The only allowed tool is read-only instruction search on our local MCP server."""

    def __init__(self, session: ClientSession):
        self.session = session

    async def search(self, query: str) -> list[dict]:
        result = await self.session.call_tool("search_instructions", {"query": query})
        if result.isError:
            raise AgentError("knowledge_unavailable")
        try:
            # FastMCP represents list results as one JSON text content block per item.
            documents = []
            for block in result.content:
                if block.type == "text":
                    value = json.loads(block.text)
                    documents.extend(value if isinstance(value, list) else [value])
            if any(not isinstance(d, dict) or not isinstance(d.get("id"), str)
                   or not isinstance(d.get("text"), str) for d in documents):
                raise ValueError("Invalid instruction")
            return documents
        except (ValueError, TypeError) as error:
            raise AgentError("knowledge_invalid_response") from error


@asynccontextmanager
async def connect_knowledge():
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from aaby.mcp_server import main; main()"],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as session:
            await session.initialize()
            yield MCPKnowledge(session)
