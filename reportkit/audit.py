import datetime
import hashlib
import json
import os
import sqlite3
import uuid


class AuditLog:
    """
    Append-only audit log backed by SQLite.

    Append-only is enforced by database triggers:
    - UPDATE on audit_events is rejected
    - DELETE on audit_events is rejected

    This satisfies the requirement that audit rows cannot be altered
    after insertion.
    """

    def __init__(self, db_path: str):
        os.makedirs(os.path.abspath(os.path.dirname(db_path)), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                hash TEXT NOT NULL
            );

            CREATE TRIGGER IF NOT EXISTS prevent_audit_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit log is append-only: UPDATE prohibited');
            END;

            CREATE TRIGGER IF NOT EXISTS prevent_audit_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit log is append-only: DELETE prohibited');
            END;
            """
        )
        self.conn.commit()

    def _last(self):
        row = self.conn.execute(
            "SELECT seq, hash FROM audit_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return 0, "GENESIS"
        return row["seq"], row["hash"]

    def record(self, event_type: str, actor: str, payload: dict) -> str:
        seq, prev_hash = self._last()
        seq += 1

        occurred_at = (
            os.environ.get("AUDIT_TIMESTAMP")
            or datetime.datetime.now(datetime.timezone.utc).isoformat()
        )

        payload_json = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            default=str
        )

        event_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{seq}:{event_type}:{payload_json}"
            )
        )

        h = hashlib.sha256(
            f"{prev_hash}|{seq}|{event_type}|{actor}|{occurred_at}|{payload_json}".encode("utf-8")
        ).hexdigest()

        self.conn.execute(
            """
            INSERT INTO audit_events
            (event_id, seq, event_type, actor, occurred_at, payload, prev_hash, hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, seq, event_type, actor, occurred_at, payload_json, prev_hash, h)
        )
        self.conn.commit()
        return event_id