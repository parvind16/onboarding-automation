# app/change_store.py
"""Durable idempotency keys, results and audit trail for change propagation."""

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ChangeStore:
    """SQLite-backed record of every change event the service has seen.

    * ``changes``    - one row per change_id: payload, status, final result.
    * ``audit_log``  - append-only event trail per change_id.

    A row with status ``in_progress`` that is found again means a previous
    run died mid-flight; the service re-runs it (writes are idempotent).
    """

    def __init__(self, db_path: str = "changes.db") -> None:
        self.db_path = db_path
        self._memory_connection: sqlite3.Connection | None = None
        self._lock = threading.Lock()

        if db_path == ":memory:":
            self._memory_connection = sqlite3.connect(
                ":memory:", check_same_thread=False
            )
            self._memory_connection.row_factory = sqlite3.Row
        else:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        with self._session() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS changes (
                    change_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    change_id TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    event TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_change "
                "ON audit_log (change_id)"
            )

    def _connect(self) -> sqlite3.Connection:
        if self._memory_connection is not None:
            return self._memory_connection
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if self._memory_connection is None:
                connection.close()

    # ---- idempotency records ---------------------------------------------

    def get(self, change_id: str) -> dict[str, Any] | None:
        with self._lock, self._session() as connection:
            row = connection.execute(
                "SELECT * FROM changes WHERE change_id = ?", (change_id,)
            ).fetchone()

        if row is None:
            return None

        record = dict(row)
        record["payload"] = json.loads(record["payload"])
        record["result"] = (
            json.loads(record["result"]) if record["result"] else None
        )
        return record

    def begin(self, change_id: str, payload: dict[str, Any]) -> None:
        now = _now().isoformat()
        with self._lock, self._session() as connection:
            connection.execute(
                """
                INSERT INTO changes
                    (change_id, payload, status, result, created_at, updated_at)
                VALUES (?, ?, 'in_progress', NULL, ?, ?)
                """,
                (change_id, json.dumps(payload, sort_keys=True), now, now),
            )

    def complete(self, change_id: str, result: dict[str, Any]) -> None:
        with self._lock, self._session() as connection:
            cursor = connection.execute(
                """
                UPDATE changes
                SET status = 'done', result = ?, updated_at = ?
                WHERE change_id = ?
                """,
                (json.dumps(result, sort_keys=True), _now().isoformat(), change_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Change not found: {change_id}")

    def purge_older_than(self, days: int) -> int:
        """Retention: drop finished idempotency keys older than ``days``.

        Unfinished (``in_progress``) rows are never purged - they still need
        to be recovered. Returns the number of rows removed.
        """
        cutoff = (_now() - timedelta(days=days)).isoformat()
        with self._lock, self._session() as connection:
            cursor = connection.execute(
                "DELETE FROM changes WHERE status = 'done' AND updated_at < ?",
                (cutoff,),
            )
            return cursor.rowcount

    # ---- audit trail -------------------------------------------------------

    def audit(
        self, change_id: str, event: str, detail: dict[str, Any] | None = None
    ) -> None:
        with self._lock, self._session() as connection:
            connection.execute(
                "INSERT INTO audit_log (change_id, ts, event, detail) "
                "VALUES (?, ?, ?, ?)",
                (
                    change_id,
                    _now().isoformat(),
                    event,
                    json.dumps(detail or {}, sort_keys=True),
                ),
            )

    def audit_trail(self, change_id: str) -> list[dict[str, Any]]:
        with self._lock, self._session() as connection:
            rows = connection.execute(
                "SELECT ts, event, detail FROM audit_log "
                "WHERE change_id = ? ORDER BY id",
                (change_id,),
            ).fetchall()

        return [
            {"ts": r["ts"], "event": r["event"], "detail": json.loads(r["detail"])}
            for r in rows
        ]
