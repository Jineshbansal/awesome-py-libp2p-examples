"""SQLite-backed document persistence for the collaborative notepad."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

from crdt import Op, TextCRDT

logger = logging.getLogger("notepad")


class DocumentStore:
    """Persist documents and their operation history to SQLite."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                doc_id      TEXT PRIMARY KEY,
                crdt_state  TEXT NOT NULL,
                updated_at  REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS operations (
                op_key      TEXT NOT NULL,
                doc_id      TEXT NOT NULL,
                op_type     TEXT NOT NULL,
                payload     TEXT NOT NULL,
                timestamp   REAL NOT NULL,
                PRIMARY KEY (op_key, doc_id)
            );

            CREATE INDEX IF NOT EXISTS idx_ops_doc_ts
                ON operations(doc_id, timestamp);
        """)
        self.conn.commit()

    def save_state(self, doc_id: str, crdt: TextCRDT) -> None:
        """Persist the full CRDT state for a document."""
        state_json = crdt.get_state_json()
        now = time.time()
        self.conn.execute(
            """
            INSERT INTO documents (doc_id, crdt_state, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(doc_id) DO UPDATE SET
                crdt_state = excluded.crdt_state,
                updated_at = excluded.updated_at
            """,
            (doc_id, state_json, now),
        )
        self.conn.commit()

    def load_state(self, doc_id: str, peer_id: str) -> TextCRDT | None:
        """Load a CRDT from disk. Returns None if document doesn't exist."""
        row = self.conn.execute(
            "SELECT crdt_state FROM documents WHERE doc_id = ?",
            (doc_id,),
        ).fetchone()
        if row is None:
            return None
        return TextCRDT.from_state_json(row[0], peer_id)

    def has_document(self, doc_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM documents WHERE doc_id = ?",
            (doc_id,),
        ).fetchone()
        return row is not None

    def store_op(self, doc_id: str, op: Op) -> None:
        """Store a single operation for replay purposes."""
        op_key = f"{op.op_id.lamport}:{op.op_id.peer_id}:{op.op_id.seq}"
        try:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO operations (op_key, doc_id, op_type, payload, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (op_key, doc_id, op.op_type, json.dumps(op.to_dict()), op.timestamp),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def get_ops_since(self, doc_id: str, since_ts: float) -> list[Op]:
        """Retrieve all operations after a given timestamp."""
        rows = self.conn.execute(
            "SELECT payload FROM operations WHERE doc_id = ? AND timestamp > ? ORDER BY timestamp",
            (doc_id, since_ts),
        ).fetchall()
        return [Op.from_dict(json.loads(row[0])) for row in rows]

    def get_all_ops(self, doc_id: str) -> list[Op]:
        """Retrieve all operations for a document."""
        rows = self.conn.execute(
            "SELECT payload FROM operations WHERE doc_id = ? ORDER BY timestamp",
            (doc_id,),
        ).fetchall()
        return [Op.from_dict(json.loads(row[0])) for row in rows]

    def get_op_count(self, doc_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM operations WHERE doc_id = ?",
            (doc_id,),
        ).fetchone()
        return row[0] if row else 0

    def list_documents(self) -> list[dict]:
        """List all stored documents with metadata."""
        rows = self.conn.execute(
            "SELECT doc_id, updated_at FROM documents ORDER BY updated_at DESC",
        ).fetchall()
        return [{"doc_id": r[0], "updated_at": r[1]} for r in rows]

    def delete_document(self, doc_id: str) -> None:
        """Delete a document and its operation history."""
        self.conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        self.conn.execute("DELETE FROM operations WHERE doc_id = ?", (doc_id,))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
