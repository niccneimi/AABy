from concurrent.futures import Future

import pytest

from aaby.api import create_app
from aaby.contracts import Hint
from aaby.errors import AgentError


class Runtime:
    def __init__(self):
        self.futures = []

    def submit(self, turn, history):
        future = Future()
        self.futures.append(future)
        return future


def payload(request_id="req-1"):
    return {"request_id": request_id, "message": "Нужен доступ", "page": {
        "snapshot_id": "s1", "url": "https://demo.invalid", "title": "test", "elements": [],
    }}


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("AABY_AGENT_MODE", "openrouter")
    runtime = Runtime()
    path = str(tmp_path / "runs.sqlite3")
    client = create_app(path, runtime=runtime).test_client()
    sid = client.post("/v1/sessions").json["id"]
    return client, sid, runtime, path


def test_nonblocking_and_idempotent(setup):
    client, sid, runtime, _ = setup
    url = f"/v1/sessions/{sid}/runs"
    first = client.post(url, json=payload())
    assert first.status_code == 202
    assert first.json["state"] == "pending"
    repeated = client.post(url, json=payload())
    assert repeated.json["id"] == first.json["id"]
    assert len(runtime.futures) == 1
    assert client.post(url, json=payload("req-2")).json["error"] == "session_busy"
    changed = payload()
    changed["message"] = "other"
    assert client.post(url, json=changed).json["error"] == "idempotency_conflict"
    runtime.futures[0].set_result(Hint(snapshot_id="s1", text="Уточни ресурс", status="needs_context", mode="openrouter"))
    result = client.get(f"{url}/{first.json['id']}").json
    assert result["state"] == "succeeded"
    assert result["response"]["snapshot_id"] == "s1"
    assert len(client.get(f"/v1/sessions/{sid}").json["hints"]) == 1
    assert client.post(url, json=payload()).json["state"] == "succeeded"
    assert len(runtime.futures) == 1


@pytest.mark.parametrize("error,code", [
    (AgentError("model_timeout"), "model_timeout"),
    (RuntimeError("secret text"), "agent_failed"),
])
def test_failures_are_sanitized(setup, error, code):
    client, sid, runtime, _ = setup
    url = f"/v1/sessions/{sid}/runs"
    run = client.post(url, json=payload()).json
    runtime.futures[0].set_exception(error)
    result = client.get(f"{url}/{run['id']}").json
    assert result["state"] == "failed"
    assert result["error"] == code
    assert "secret text" not in str(result)
    assert client.get(f"/v1/sessions/{sid}").json["hints"] == []


def test_queue_full(setup, monkeypatch):
    client, sid, runtime, _ = setup
    def full(*args):
        raise AgentError("queue_full")
    monkeypatch.setattr(runtime, "submit", full)
    assert client.post(f"/v1/sessions/{sid}/runs", json=payload()).json["error"] == "queue_full"


def test_restart_interrupts_pending(setup):
    client, sid, runtime, path = setup
    run = client.post(f"/v1/sessions/{sid}/runs", json=payload()).json
    restarted = create_app(path, runtime=Runtime()).test_client()
    assert restarted.get(f"/v1/sessions/{sid}/runs/{run['id']}").json["error"] == "run_interrupted"
    # A late completion from an old worker cannot overwrite the interrupted run.
    runtime.futures[0].set_result(Hint(snapshot_id="s1", text="x", status="waiting_user"))
    assert restarted.get(f"/v1/sessions/{sid}").json["hints"] == []


def test_run_routes(setup):
    client, sid, _, _ = setup
    assert client.post(f"/v1/sessions/{sid}/turns", json=payload()).json["error"] == "async_runs_required"
    assert client.post(f"/v1/sessions/{sid}/runs", json={}).status_code == 422
    assert client.post("/v1/sessions/missing/runs", json=payload()).status_code == 404
    assert client.get(f"/v1/sessions/{sid}/runs/missing").status_code == 404
    assert client.get("/health").json["mode"] == "openrouter"


def test_demo_run(tmp_path):
    client = create_app(str(tmp_path / "demo.sqlite3")).test_client()
    sid = client.post("/v1/sessions").json["id"]
    result = client.post(f"/v1/sessions/{sid}/runs", json=payload())
    assert result.status_code == 202
    assert result.json["state"] == "succeeded"
