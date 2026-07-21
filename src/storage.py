"""SQLite persistence for ResearchState snapshots (v1.3 phase 1).

Uses the stdlib ``sqlite3`` module only. Does not integrate with the pipeline.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from src.models import ResearchDepth
from src.research_state import ResearchState, research_state_to_json

DEFAULT_DB_PATH = Path("data") / "researchpilot.db"
SCHEMA_VERSION = 1

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS research_runs (
    run_id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    depth TEXT NOT NULL,
    status TEXT NOT NULL,
    current_stage TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state_json TEXT NOT NULL,
    error_message TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
)
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_research_runs_updated_at
ON research_runs (updated_at DESC)
"""

_UPSERT_SQL = """
INSERT INTO research_runs (
    run_id, topic, depth, status, current_stage,
    created_at, updated_at, state_json, error_message, schema_version
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(run_id) DO UPDATE SET
    topic = excluded.topic,
    depth = excluded.depth,
    status = excluded.status,
    current_stage = excluded.current_stage,
    created_at = excluded.created_at,
    updated_at = excluded.updated_at,
    state_json = excluded.state_json,
    error_message = excluded.error_message,
    schema_version = excluded.schema_version
"""


def _depth_value(depth: Any) -> str:
    if isinstance(depth, ResearchDepth):
        return depth.value
    if hasattr(depth, "value"):
        return str(getattr(depth, "value"))
    return str(depth)


class ResearchRunRepository:
    """Lightweight SQLite repository for research run snapshots."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def __enter__(self) -> "ResearchRunRepository":
        self.initialize()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.close()

    def close(self) -> None:
        """No persistent connection is held; provided for API symmetry."""
        return None

    def initialize(self) -> None:
        """Create parent directory and ``research_runs`` table if needed."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE_SQL)
            conn.execute(_CREATE_INDEX_SQL)
            conn.commit()

    def save_state(self, state: ResearchState) -> None:
        """Insert or update a full JSON snapshot for ``state.run_id``.

        Does not mutate ``state``.
        """
        if not isinstance(state, ResearchState):
            raise TypeError("save_state expects a ResearchState")
        state_json = research_state_to_json(state)
        params = (
            state.run_id,
            state.topic,
            _depth_value(state.depth),
            state.status,
            state.current_stage,
            state.created_at,
            state.updated_at,
            state_json,
            state.error,
            SCHEMA_VERSION,
        )
        with self._connect() as conn:
            conn.execute(_UPSERT_SQL, params)
            conn.commit()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Return a row dict with ``state_snapshot`` parsed from ``state_json``."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT run_id, topic, depth, status, current_stage,
                       created_at, updated_at, state_json, error_message,
                       schema_version
                FROM research_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_run_dict(row, include_snapshot=True)

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return lightweight run summaries ordered by ``updated_at`` DESC."""
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, topic, depth, status, current_stage,
                       created_at, updated_at, error_message, schema_version
                FROM research_runs
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_run_dict(row, include_snapshot=False) for row in rows]

    def delete_run(self, run_id: str) -> bool:
        """Delete a run by id. Returns True if a row was removed."""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM research_runs WHERE run_id = ?",
                (run_id,),
            )
            conn.commit()
            return cur.rowcount > 0

    def exists(self, run_id: str) -> bool:
        """Return True if ``run_id`` already has a row."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM research_runs WHERE run_id = ? LIMIT 1",
                (run_id,),
            ).fetchone()
        return row is not None

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn


def _row_to_run_dict(row: sqlite3.Row, *, include_snapshot: bool) -> dict[str, Any]:
    data = {
        "run_id": row["run_id"],
        "topic": row["topic"],
        "depth": row["depth"],
        "status": row["status"],
        "current_stage": row["current_stage"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "error_message": row["error_message"],
        "schema_version": row["schema_version"],
    }
    if include_snapshot:
        raw = row["state_json"]
        try:
            snapshot = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid state_json for run_id={row['run_id']}") from exc
        data["state_json"] = raw
        data["state_snapshot"] = snapshot
    return data
