import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from aaby.mcp_server import mcp


def test_registered_tools():
    async def check():
        tools = await mcp.list_tools()
        assert {tool.name for tool in tools} == {"search_instructions", "read_instruction"}
    asyncio.run(check())


def test_stdio_roundtrip():
    async def check():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-c", "from aaby.mcp_server import main; main()"],
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                assert len(listing.tools) == 2
                result = await session.call_tool("search_instructions", {"query": "доступ"})
                assert not result.isError
                assert "demo-access-v1" in result.content[0].text
                instruction = await session.call_tool("read_instruction", {
                    "instruction_id": "demo-access-v1",
                })
                assert not instruction.isError
                assert "synthetic" in instruction.content[0].text
    asyncio.run(asyncio.wait_for(check(), timeout=30))
