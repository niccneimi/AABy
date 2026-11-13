import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from aaby.contracts import Hint, Turn
from aaby.errors import AgentError
from aaby.mcp_client import MCPKnowledge, connect_knowledge
from aaby.openrouter import OpenRouterConfig
from aaby.runtime import AgentRuntime


def turn():
    return Turn.model_validate({"message": "доступ", "page": {
        "snapshot_id": "s1", "url": "https://demo.invalid", "title": "test",
    }})


@pytest.mark.parametrize("failure,code", [
    (None, None),
    (AgentError("model_timeout"), "model_timeout"),
    (TimeoutError(), "agent_timeout"),
    (RuntimeError("private error"), "agent_failed"),
])
def test_worker_reuses_connection(monkeypatch, failure, code):
    entered = []
    exited = []

    @asynccontextmanager
    async def connector():
        entered.append(1)
        try:
            yield object()
        finally:
            exited.append(1)

    async def respond(self, request, history):
        if failure:
            raise failure
        return Hint(snapshot_id=request.page.snapshot_id, text="Уточни ресурс", status="needs_context")

    monkeypatch.setattr("aaby.runtime.OpenRouterAgent.respond", respond)
    runtime = AgentRuntime(OpenRouterConfig("fake", "test/model"), connector=connector)
    try:
        for _ in range(2):
            future = runtime.submit(turn(), [])
            if code:
                with pytest.raises(AgentError, match=code):
                    future.result(timeout=10)
            else:
                assert future.result(timeout=10).snapshot_id == "s1"
    finally:
        runtime.close()
    assert entered == [1]
    assert exited == [1]
    with pytest.raises(AgentError, match="runtime_unavailable"):
        runtime.submit(turn(), [])


def test_startup_failure():
    @asynccontextmanager
    async def broken():
        raise RuntimeError("private error")
        yield  # pragma: no cover

    runtime = AgentRuntime(OpenRouterConfig("fake", "test/model"), connector=broken)
    try:
        with pytest.raises(AgentError, match="knowledge_unavailable"):
            runtime.submit(turn(), []).result(timeout=10)
    finally:
        runtime.close()


def test_real_mcp_connection_reused():
    async def check():
        async with connect_knowledge() as knowledge:
            assert (await knowledge.search("доступ"))[0]["synthetic"] is True
            assert await knowledge.search("unknown") == []
    asyncio.run(asyncio.wait_for(check(), timeout=30))


@pytest.mark.parametrize("blocks,is_error,code", [
    ([], True, "knowledge_unavailable"),
    ([SimpleNamespace(type="text", text="invalid")], False, "knowledge_invalid_response"),
    ([SimpleNamespace(type="text", text='{"id":1}')], False, "knowledge_invalid_response"),
])
def test_mcp_failures(blocks, is_error, code):
    class Session:
        async def call_tool(self, *args):
            return SimpleNamespace(content=blocks, isError=is_error)
    with pytest.raises(AgentError, match=code):
        asyncio.run(MCPKnowledge(Session()).search("доступ"))


def test_app_manages_runtime(monkeypatch, tmp_path):
    from aaby.api import create_app
    monkeypatch.setenv("AABY_AGENT_MODE", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake")
    monkeypatch.setenv("OPENROUTER_MODEL", "test/model")
    app = create_app(str(tmp_path / "db.sqlite3"))
    assert isinstance(app.extensions["aaby_runtime"], AgentRuntime)
    app.extensions["aaby_runtime"].close()
