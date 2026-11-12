import asyncio
import queue
import threading
from concurrent.futures import Future

import httpx

from aaby.errors import AgentError
from aaby.mcp_client import connect_knowledge
from aaby.openrouter import OpenRouterAgent


class AgentRuntime:
    """One bounded local worker; MCP contexts enter and exit within the same task.

    Sequential work avoids crossing session privileges and overlapping model turns.
    This is not a distributed queue. Restarted pending runs are marked interrupted.
    """

    def __init__(self, config, capacity=8, connector=connect_knowledge):
        self.config = config
        self.connector = connector
        self.jobs = queue.Queue(maxsize=capacity)
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.thread = None

    def submit(self, turn, history) -> Future:
        with self.lock:
            if self.stopping.is_set():
                raise AgentError("runtime_unavailable")
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name="aaby-agent", daemon=True)
                self.thread.start()
            future = Future()
            try:
                self.jobs.put_nowait((future, turn, history))
            except queue.Full as error:
                raise AgentError("queue_full") from error
            return future

    def _run(self):
        try:
            asyncio.run(self._serve())
        except Exception:
            # Exceptions may contain provider text, document contents or credentials.
            with self.lock:
                self.stopping.set()
                while not self.jobs.empty():
                    future, _, _ = self.jobs.get_nowait()
                    future.set_exception(AgentError("knowledge_unavailable"))

    async def _serve(self):
        async with self.connector() as knowledge:
            async with httpx.AsyncClient() as client:
                agent = OpenRouterAgent(self.config, client, knowledge)
                while not self.stopping.is_set():
                    try:
                        future, turn, history = self.jobs.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(0.05)
                        continue
                    try:
                        hint = await asyncio.wait_for(agent.respond(turn, history), timeout=60)
                    except TimeoutError:
                        future.set_exception(AgentError("agent_timeout"))
                    except AgentError as error:
                        future.set_exception(error)
                    except Exception:
                        future.set_exception(AgentError("agent_failed"))
                    else:
                        future.set_result(hint)
        while not self.jobs.empty():
            future, _, _ = self.jobs.get_nowait()
            future.set_exception(AgentError("runtime_unavailable"))

    def close(self):
        with self.lock:
            self.stopping.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
