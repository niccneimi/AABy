import os
import atexit

from flask import Flask, jsonify, request
from pydantic import ValidationError
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from aaby.agent import DemoAgent
from aaby.contracts import Turn, RunRequest
from aaby.errors import AgentError
from aaby.openrouter import OpenRouterConfig
from aaby.runtime import AgentRuntime
from aaby.store import Store, RunConflict


def create_app(db_path: str | None = None, runtime=None) -> Flask:
    mode = os.environ.get("AABY_AGENT_MODE", "demo")
    if mode not in ("demo", "openrouter"):
        raise ValueError("Unsupported AABY_AGENT_MODE")
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 8_000_000
    store = Store(db_path or os.environ.get("AABY_DB", "data/aaby.sqlite3"))
    agent = DemoAgent()
    if mode == "openrouter" and runtime is None:
        runtime = AgentRuntime(OpenRouterConfig.from_env())
        atexit.register(runtime.close)
    store.interrupt_pending_runs()
    app.extensions["aaby_runtime"] = runtime

    @app.errorhandler(BadRequest)
    def bad_json(error):
        return jsonify(error="invalid_json"), 400

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(error):
        return jsonify(error="payload_too_large"), 413

    @app.get("/health")
    def health():
        return jsonify(status="ok", mode=mode)

    @app.post("/v1/sessions")
    def create_session():
        return jsonify(id=store.create_session()), 201

    @app.get("/v1/sessions/<session_id>")
    def get_session(session_id):
        session = store.get_session(session_id)
        if session is None:
            return jsonify(error="session_not_found"), 404
        return jsonify(session)

    @app.post("/v1/sessions/<session_id>/turns")
    def create_turn(session_id):
        if mode != "demo":
            return jsonify(error="async_runs_required"), 409
        if store.get_session(session_id) is None:
            return jsonify(error="session_not_found"), 404
        try:
            turn = Turn.model_validate(request.get_json(silent=False))
        except ValidationError:
            # Validation errors must not echo user payloads into logs or responses.
            return jsonify(error="invalid_turn"), 422
        hint = agent.respond(turn)
        store.save_hint(session_id, hint)
        return jsonify(hint.model_dump())

    @app.post("/v1/sessions/<session_id>/runs")
    def create_run(session_id):
        session = store.get_session(session_id)
        if session is None:
            return jsonify(error="session_not_found"), 404
        try:
            turn = RunRequest.model_validate(request.get_json(silent=False))
        except ValidationError:
            return jsonify(error="invalid_turn"), 422
        try:
            run, created = store.create_run(session_id, turn)
        except RunConflict as error:
            return jsonify(error=str(error)), 409
        if created:
            if mode == "demo":
                store.finish_run(session_id, run["id"], agent.respond(turn), None)
            else:
                def finished(future):
                    try:
                        hint = future.result()
                    except AgentError as error:
                        store.finish_run(session_id, run["id"], None, error.code)
                    except Exception:
                        store.finish_run(session_id, run["id"], None, "agent_failed")
                    else:
                        store.finish_run(session_id, run["id"], hint, None)
                try:
                    future = runtime.submit(turn, session["hints"])
                except AgentError as error:
                    store.finish_run(session_id, run["id"], None, error.code)
                else:
                    future.add_done_callback(finished)
        return jsonify(store.get_run(session_id, run["id"])), 202

    @app.get("/v1/sessions/<session_id>/runs/<run_id>")
    def get_run(session_id, run_id):
        run = store.get_run(session_id, run_id)
        if run is None:
            return jsonify(error="run_not_found"), 404
        return jsonify(run)

    return app


def main():  # pragma: no cover
    # Local scaffold only. Add identity verification before exposing this service.
    create_app().run(host="127.0.0.1", port=8000, debug=False)
