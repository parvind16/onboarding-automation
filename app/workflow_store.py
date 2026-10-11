
# app/workflow_store.py

import json
import sqlite3
from pathlib import Path
from typing import Any


class WorkflowStore:
    """Persist onboarding progress using SQLite."""

    def __init__(self, db_path: str = "onboarding.db") -> None:
        self.db_path = db_path
        self._memory_connection: sqlite3.Connection | None = None

        if db_path == ":memory:":
            self._memory_connection = sqlite3.connect(":memory:")
            self._memory_connection.row_factory = sqlite3.Row
        else:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS workflows (
                    employee_id TEXT PRIMARY KEY,
                    employee_data TEXT NOT NULL,
                    status TEXT NOT NULL,
                    completed_steps TEXT NOT NULL DEFAULT '[]',
                    failed_step TEXT,
                    message TEXT
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        if self._memory_connection is not None:
            return self._memory_connection

        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def get(self, employee_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM workflows WHERE employee_id = ?",
                (employee_id,),
            ).fetchone()

        if row is None:
            return None

        result = dict(row)
        result["employee_data"] = json.loads(result["employee_data"])
        result["completed_steps"] = json.loads(result["completed_steps"])
        return result

    def create(
        self,
        employee_id: str,
        employee_data: dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflows (
                    employee_id, employee_data, status,
                    completed_steps, failed_step, message
                )
                VALUES (?, ?, 'running', '[]', NULL, NULL)
                """,
                (
                    employee_id,
                    json.dumps(employee_data, sort_keys=True),
                ),
            )

    def update(
        self,
        employee_id: str,
        *,
        status: str,
        completed_steps: list[str],
        failed_step: str | None = None,
        message: str | None = None,
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE workflows
                SET status = ?,
                    completed_steps = ?,
                    failed_step = ?,
                    message = ?
                WHERE employee_id = ?
                """,
                (
                    status,
                    json.dumps(completed_steps),
                    failed_step,
                    message,
                    employee_id,
                ),
            )

            if cursor.rowcount == 0:
                raise KeyError(f"Workflow not found: {employee_id}")