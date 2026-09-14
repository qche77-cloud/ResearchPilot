"""SQLite persistence for ResearchState snapshots (v1.3).

Uses the stdlib ``sqlite3`` module only. Does not integrate with the pipeline.
Provides history list/count queries and full-state reload for UI layers.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any

from src.evidence_strategy import EvidenceCoverageResult, EvidenceStrategy
from src.models import (
    AnalyzedQuery,
    EvidenceDocument,
    EvaluatedEvidence,
    GroundedFinding,
    QueryType,
    ReportSection,
    ResearchDepth,
    ResearchHealth,
    ResearchPlan,
    ResearchPlanStep,
    ResearchReport,
    Source,
    SupportingExcerpt,
    SynthesisBrief,
)
from src.research_state import ResearchState, research_state_to_json

DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "researchpilot.db"
SCHEMA_VERSION = 1
MAX_HISTORY_LIMIT = 100

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

_SUMMARY_COLUMNS = (
    "run_id, topic, depth, status, current_stage, "
    "created_at, updated_at, error_message"
)


@dataclass(frozen=True, slots=True)
class ResearchRunSummary:
    """Lightweight history-list row (no ``state_json`` / nested artifacts)."""

    run_id: str
    topic: str
    depth: str
    status: str
    current_stage: str
    created_at: str
    updated_at: str
    error_message: str | None


def _depth_value(depth: Any) -> str:
    if isinstance(depth, ResearchDepth):
        return depth.value
    if hasattr(depth, "value"):
        return str(getattr(depth, "value"))
    return str(depth)


def _escape_like(value: str) -> str:
    """Escape ``\\``, ``%``, and ``_`` for SQLite ``LIKE ... ESCAPE '\\'``."""
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _normalize_status(status: str | None) -> str | None:
    if status is None:
        return None
    text = str(status).strip()
    return text or None


def _normalize_topic_query(topic_query: str | None) -> str | None:
    if topic_query is None:
        return None
    text = str(topic_query).strip()
    return text or None


def _build_run_filters(
    *,
    status: str | None,
    topic_query: str | None,
) -> tuple[str, list[Any]]:
    """Build ``WHERE`` clause fragments and bound params (no user SQL concat)."""
    clauses: list[str] = []
    params: list[Any] = []
    status_n = _normalize_status(status)
    if status_n is not None:
        clauses.append("status = ?")
        params.append(status_n)
    topic_n = _normalize_topic_query(topic_query)
    if topic_n is not None:
        clauses.append("topic LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(topic_n)}%")
    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def _require_int(name: str, value: Any, *, allow_zero: bool = False) -> int:
    # Reject bool explicitly (bool is a subclass of int).
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int (got {type(value).__name__})")
    if allow_zero:
        if value < 0:
            raise ValueError(f"{name} must be >= 0")
    elif value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _validate_limit_offset(limit: Any, offset: Any) -> tuple[int, int]:
    limit_i = _require_int("limit", limit, allow_zero=False)
    if limit_i > MAX_HISTORY_LIMIT:
        raise ValueError(f"limit must be <= {MAX_HISTORY_LIMIT}")
    offset_i = _require_int("offset", offset, allow_zero=True)
    return limit_i, offset_i


class ResearchRunRepository:
    """Lightweight SQLite repository for research run snapshots and history."""

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

    def get_state(self, run_id: str) -> ResearchState | None:
        """Load and hydrate a full ``ResearchState`` for ``run_id``, or None."""
        row = self.get_run(run_id)
        if row is None:
            return None
        snapshot = row.get("state_snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError(f"invalid state_snapshot for run_id={run_id}")
        return _hydrate_research_state(snapshot)

    def list_runs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        topic_query: str | None = None,
    ) -> list[ResearchRunSummary]:
        """Return history summaries (no ``state_json``), newest first."""
        limit_i, offset_i = _validate_limit_offset(limit, offset)
        where_sql, params = _build_run_filters(status=status, topic_query=topic_query)
        sql = (
            f"SELECT {_SUMMARY_COLUMNS} FROM research_runs"
            f"{where_sql}"
            " ORDER BY updated_at DESC, created_at DESC, run_id DESC"
            " LIMIT ? OFFSET ?"
        )
        bind = list(params) + [limit_i, offset_i]
        with self._connect() as conn:
            rows = conn.execute(sql, bind).fetchall()
        return [_row_to_summary(row) for row in rows]

    def count_runs(
        self,
        *,
        status: str | None = None,
        topic_query: str | None = None,
    ) -> int:
        """Count runs matching the same filters as ``list_runs`` (no pagination)."""
        where_sql, params = _build_run_filters(status=status, topic_query=topic_query)
        sql = f"SELECT COUNT(*) FROM research_runs{where_sql}"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return int(row[0] if row is not None else 0)

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

    @contextmanager
    def _connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            with conn:
                yield conn
        finally:
            conn.close()


def _row_to_summary(row: sqlite3.Row) -> ResearchRunSummary:
    return ResearchRunSummary(
        run_id=str(row["run_id"]),
        topic=str(row["topic"]),
        depth=str(row["depth"]),
        status=str(row["status"]),
        current_stage=str(row["current_stage"] or ""),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        error_message=(
            None if row["error_message"] is None else str(row["error_message"])
        ),
    )


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


# --- Snapshot hydration (history detail) ------------------------------------


def _coerce_enum(enum_cls: Any, value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(value)
    except (TypeError, ValueError):
        return default


def _dataclass_from_dict(cls: type, data: Any) -> Any:
    if data is None:
        return None
    if is_dataclass(data) and not isinstance(data, type):
        return data
    if not isinstance(data, dict):
        return None
    valid = {f.name for f in fields(cls)}
    kwargs = {k: v for k, v in data.items() if k in valid}
    return cls(**kwargs)


def _source_from_dict(data: Any) -> Source | None:
    obj = _dataclass_from_dict(Source, data)
    return obj if isinstance(obj, Source) else None


def _document_from_dict(data: Any) -> EvidenceDocument | None:
    if not isinstance(data, dict):
        return None
    source = _source_from_dict(data.get("source"))
    if source is None:
        return None
    payload = dict(data)
    payload["source"] = source
    obj = _dataclass_from_dict(EvidenceDocument, payload)
    return obj if isinstance(obj, EvidenceDocument) else None


def _evidence_from_dict(data: Any) -> EvaluatedEvidence | None:
    if not isinstance(data, dict):
        return None
    document = _document_from_dict(data.get("document"))
    if document is None:
        return None
    payload = dict(data)
    payload["document"] = document
    obj = _dataclass_from_dict(EvaluatedEvidence, payload)
    return obj if isinstance(obj, EvaluatedEvidence) else None


def _excerpt_from_dict(data: Any) -> SupportingExcerpt | None:
    obj = _dataclass_from_dict(SupportingExcerpt, data)
    return obj if isinstance(obj, SupportingExcerpt) else None


def _finding_from_dict(data: Any) -> GroundedFinding | None:
    if not isinstance(data, dict):
        return None
    excerpts: list[SupportingExcerpt] = []
    for item in data.get("supporting_excerpts") or []:
        ex = _excerpt_from_dict(item)
        if ex is not None:
            excerpts.append(ex)
    payload = dict(data)
    payload["supporting_excerpts"] = excerpts
    payload["evidence_ids"] = list(data.get("evidence_ids") or [])
    obj = _dataclass_from_dict(GroundedFinding, payload)
    return obj if isinstance(obj, GroundedFinding) else None


def _strategy_from_dict(data: Any) -> EvidenceStrategy | None:
    if data is None:
        return None
    if isinstance(data, str) and data.startswith("<"):
        return None
    obj = _dataclass_from_dict(EvidenceStrategy, data)
    return obj if isinstance(obj, EvidenceStrategy) else None


def _plan_step_from_dict(data: Any) -> ResearchPlanStep | None:
    if not isinstance(data, dict):
        return None
    payload = dict(data)
    payload["evidence_strategy"] = _strategy_from_dict(data.get("evidence_strategy"))
    payload["search_queries"] = list(data.get("search_queries") or [])
    obj = _dataclass_from_dict(ResearchPlanStep, payload)
    return obj if isinstance(obj, ResearchPlanStep) else None


def _analyzed_from_dict(data: Any) -> AnalyzedQuery | None:
    if not isinstance(data, dict):
        return None
    payload = dict(data)
    payload["query_type"] = _coerce_enum(
        QueryType, data.get("query_type"), QueryType.INDUSTRY
    )
    obj = _dataclass_from_dict(AnalyzedQuery, payload)
    return obj if isinstance(obj, AnalyzedQuery) else None


def _plan_from_dict(data: Any) -> ResearchPlan | None:
    if not isinstance(data, dict):
        return None
    steps: list[ResearchPlanStep] = []
    for item in data.get("steps") or []:
        step = _plan_step_from_dict(item)
        if step is not None:
            steps.append(step)
    payload = dict(data)
    payload["steps"] = steps
    payload["depth"] = _coerce_enum(ResearchDepth, data.get("depth"), ResearchDepth.QUICK)
    payload["query_type"] = _coerce_enum(
        QueryType, data.get("query_type"), QueryType.INDUSTRY
    )
    payload["analyzed_query"] = _analyzed_from_dict(data.get("analyzed_query"))
    obj = _dataclass_from_dict(ResearchPlan, payload)
    return obj if isinstance(obj, ResearchPlan) else None


def _coverage_from_dict(data: Any) -> EvidenceCoverageResult | None:
    if not isinstance(data, dict):
        return None
    payload = dict(data)
    payload["evidence_types_present"] = list(data.get("evidence_types_present") or [])
    payload["missing_evidence_targets"] = list(data.get("missing_evidence_targets") or [])
    obj = _dataclass_from_dict(EvidenceCoverageResult, payload)
    return obj if isinstance(obj, EvidenceCoverageResult) else None


def _health_from_dict(data: Any) -> ResearchHealth | None:
    if not isinstance(data, dict):
        return None
    payload = dict(data)
    payload["warnings"] = list(data.get("warnings") or [])
    payload["suggestions"] = list(data.get("suggestions") or [])
    payload["details"] = dict(data.get("details") or {})
    obj = _dataclass_from_dict(ResearchHealth, payload)
    return obj if isinstance(obj, ResearchHealth) else None


def _report_from_dict(data: Any) -> ResearchReport | None:
    if not isinstance(data, dict):
        return None
    sections: list[ReportSection] = []
    for item in data.get("sections") or []:
        sec = _dataclass_from_dict(ReportSection, item)
        if isinstance(sec, ReportSection):
            sections.append(sec)
    payload = dict(data)
    payload["sections"] = sections
    payload["depth"] = _coerce_enum(ResearchDepth, data.get("depth"), ResearchDepth.QUICK)
    obj = _dataclass_from_dict(ResearchReport, payload)
    return obj if isinstance(obj, ResearchReport) else None


def _synthesis_from_dict(data: Any) -> SynthesisBrief | None:
    if not isinstance(data, dict):
        return None
    finding_lists = (
        "key_findings",
        "industry_chain_findings",
        "demand_supply_drivers",
        "technology_findings",
        "catalysts",
        "company_findings",
        "risks",
        "evidence_gaps",
    )
    payload = dict(data)
    payload["depth"] = _coerce_enum(ResearchDepth, data.get("depth"), ResearchDepth.QUICK)
    payload["findings"] = dict(data.get("findings") or {})
    for key in finding_lists:
        items: list[GroundedFinding] = []
        for raw in data.get(key) or []:
            finding = _finding_from_dict(raw)
            if finding is not None:
                items.append(finding)
        payload[key] = items
    index: dict[str, EvaluatedEvidence] = {}
    raw_index = data.get("evidence_index") or {}
    if isinstance(raw_index, dict):
        for eid, raw_ev in raw_index.items():
            ev = _evidence_from_dict(raw_ev)
            if ev is not None:
                index[str(eid)] = ev
    payload["evidence_index"] = index
    cited: list[EvaluatedEvidence] = []
    for raw in data.get("cited_evidence") or []:
        ev = _evidence_from_dict(raw)
        if ev is not None:
            cited.append(ev)
    payload["cited_evidence"] = cited
    obj = _dataclass_from_dict(SynthesisBrief, payload)
    return obj if isinstance(obj, SynthesisBrief) else None


def _hydrate_research_state(data: dict[str, Any]) -> ResearchState:
    """Rebuild ``ResearchState`` from a JSON snapshot dict."""
    depth = _coerce_enum(ResearchDepth, data.get("depth"), ResearchDepth.QUICK)
    sources: list[Source] = []
    for item in data.get("sources") or []:
        src = _source_from_dict(item)
        if src is not None:
            sources.append(src)
    documents: list[EvidenceDocument] = []
    for item in data.get("documents") or []:
        doc = _document_from_dict(item)
        if doc is not None:
            documents.append(doc)
    evidence: list[EvaluatedEvidence] = []
    for item in data.get("evidence") or []:
        ev = _evidence_from_dict(item)
        if ev is not None:
            evidence.append(ev)
    coverage_before: list[EvidenceCoverageResult] = []
    for item in data.get("coverage_before") or []:
        cov = _coverage_from_dict(item)
        if cov is not None:
            coverage_before.append(cov)
    coverage_after: list[EvidenceCoverageResult] = []
    for item in data.get("coverage_after") or []:
        cov = _coverage_from_dict(item)
        if cov is not None:
            coverage_after.append(cov)

    return ResearchState(
        run_id=str(data.get("run_id") or ""),
        topic=str(data.get("topic") or ""),
        depth=depth,
        status=str(data.get("status") or "pending"),
        current_stage=str(data.get("current_stage") or "initialized"),
        analyzed_query=_analyzed_from_dict(data.get("analyzed_query")),
        plan=_plan_from_dict(data.get("plan")),
        sources=sources,
        documents=documents,
        evidence=evidence,
        coverage_before=coverage_before,
        coverage_after=coverage_after,
        synthesis=_synthesis_from_dict(data.get("synthesis")),
        research_health=_health_from_dict(data.get("research_health")),
        report=_report_from_dict(data.get("report")),
        diagnostics=dict(data.get("diagnostics") or {})
        if isinstance(data.get("diagnostics"), dict)
        else {},
        error=(str(data["error"]) if data.get("error") is not None else None),
        created_at=str(data.get("created_at") or ""),
        updated_at=str(data.get("updated_at") or ""),
    )
