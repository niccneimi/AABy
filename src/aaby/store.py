import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from aaby.contracts import Hint


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

