import os

from flask import Flask, jsonify, request
from pydantic import ValidationError
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from aaby.agent import DemoAgent
from aaby.contracts import Turn
from aaby.store import Store


def create_app(db_path: str | None = None) -> Flask:
    if os.environ.get("AABY_AGENT_MODE", "demo") != "demo":
        raise ValueError("Only demo mode is implemented")
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 8_000_000
    store = Store(db_path or os.environ.get("AABY_DB", "data/aaby.sqlite3"))
    agent = DemoAgent()

    @app.errorhandler(BadRequest)
    def bad_json(error):
        return jsonify(error="invalid_json"), 400

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(error):
        return jsonify(error="payload_too_large"), 413

    @app.get("/health")
    def health():
        return jsonify(status="ok", mode="demo")

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

    return app


def main():  # pragma: no cover
    # Local scaffold only. Add identity verification before exposing this service.
    create_app().run(host="127.0.0.1", port=8000, debug=False)

