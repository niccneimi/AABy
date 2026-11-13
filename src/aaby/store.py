import json
import sqlite3
from contextlib import contextmanager
import hashlib
from pathlib import Path
from uuid import uuid4

from aaby.contracts import Hint


class RunConflict(Exception):
    pass


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'needs_context'
                );
                CREATE TABLE IF NOT EXISTS hints (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    response TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    error TEXT,
                    response TEXT,
                    UNIQUE(session_id, request_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs(session_id)
                    WHERE state = 'pending';
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    def create_session(self) -> str:
        session_id = str(uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO sessions(id) VALUES (?)", (session_id,))
        return session_id

    def get_session(self, session_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT status FROM sessions WHERE id=?", (session_id,)).fetchone()
            if row is None:
                return None
            hints = db.execute(
                "SELECT response FROM hints WHERE session_id=? ORDER BY seq", (session_id,)
            ).fetchall()
        return {"id": session_id, "status": row[0], "hints": [json.loads(h[0]) for h in hints]}

    def save_hint(self, session_id: str, hint: Hint):
        # Raw screenshots, page contents and messages are not persisted in this scaffold.
        with self.connect() as db:
            db.execute("INSERT INTO hints(session_id,response) VALUES (?,?)",
                       (session_id, hint.model_dump_json()))
            db.execute("UPDATE sessions SET status=? WHERE id=?", (hint.status, session_id))

    def create_run(self, session_id: str, request) -> tuple[dict, bool]:
        fingerprint = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id, fingerprint FROM runs WHERE session_id=? AND request_id=?",
                (session_id, request.request_id),
            ).fetchone()
            if row:
                if row[1] != fingerprint:
                    raise RunConflict("idempotency_conflict")
                run_id, created = row[0], False
            else:
                run_id, created = str(uuid4()), True
                try:
                    db.execute(
                        "INSERT INTO runs(id,session_id,request_id,fingerprint,snapshot_id) VALUES (?,?,?,?,?)",
                        (run_id, session_id, request.request_id, fingerprint, request.page.snapshot_id),
                    )
                except sqlite3.IntegrityError as error:
                    raise RunConflict("session_busy") from error
        return self.get_run(session_id, run_id), created

    def get_run(self, session_id: str, run_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT id,snapshot_id,state,error,response FROM runs WHERE session_id=? AND id=?",
                (session_id, run_id),
            ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "snapshot_id": row[1], "state": row[2], "error": row[3],
                "response": json.loads(row[4]) if row[4] else None}

    def finish_run(self, session_id: str, run_id: str, hint: Hint | None, error: str | None):
        with self.connect() as db:
            updated = db.execute(
                "UPDATE runs SET state=?,error=?,response=? WHERE id=? AND session_id=? AND state='pending'",
                ("succeeded" if hint else "failed", error, hint.model_dump_json() if hint else None,
                 run_id, session_id),
            )
            if updated.rowcount and hint:
                db.execute("INSERT INTO hints(session_id,response) VALUES (?,?)",
                           (session_id, hint.model_dump_json()))
                db.execute("UPDATE sessions SET status=? WHERE id=?", (hint.status, session_id))

    def interrupt_pending_runs(self):
        # Local single-process runtime only: call once at application startup.
        with self.connect() as db:
            db.execute("UPDATE runs SET state='failed',error='run_interrupted' WHERE state='pending'")
