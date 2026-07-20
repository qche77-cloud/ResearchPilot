"""ResearchState — in-memory run container for a single research task (v1.3).

Holds pipeline artifacts for a run without replacing ``ResearchResult``.
Does not call LLMs, search APIs, or the database.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from src.evidence_strategy import EvidenceCoverageResult
from src.models import (
    AnalyzedQuery,
    EvidenceDocument,
    EvaluatedEvidence,
    ResearchDepth,
    ResearchHealth,
    ResearchPlan,
    ResearchReport,
    Source,
    SynthesisBrief,
)

_SENSITIVE_KEY_MARKERS = (
    "api_key",
    "apikey",
    "openai_api_key",
    "tavily_api_key",
    "authorization",
    "secret",
    "password",
    "access_token",
    "refresh_token",
    ".env",
    "dotenv",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _new_run_id() -> str:
    return str(uuid.uuid4())


@dataclass
class ResearchState:
    """Internal runtime state for one research run (not yet wired to pipeline)."""

    topic: str = ""
    depth: ResearchDepth = ResearchDepth.QUICK
    run_id: str = field(default_factory=_new_run_id)
    status: str = "pending"  # pending | running | completed | failed
    current_stage: str = "initialized"
    analyzed_query: AnalyzedQuery | None = None
    plan: ResearchPlan | None = None
    sources: list[Source] = field(default_factory=list)
    documents: list[EvidenceDocument] = field(default_factory=list)
    evidence: list[EvaluatedEvidence] = field(default_factory=list)
    coverage_before: list[EvidenceCoverageResult] = field(default_factory=list)
    coverage_after: list[EvidenceCoverageResult] = field(default_factory=list)
    synthesis: SynthesisBrief | None = None
    research_health: ResearchHealth | None = None
    report: ResearchReport | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)

    def touch(self) -> None:
        """Refresh ``updated_at`` to the current UTC time."""
        self.updated_at = _utc_now_iso()

    def mark_running(self, stage: str) -> None:
        """Mark the run as running at ``stage``."""
        self.status = "running"
        self.current_stage = str(stage or "running")
        self.touch()

    def mark_completed(self) -> None:
        """Mark the run as successfully completed."""
        self.status = "completed"
        self.current_stage = "completed"
        self.error = None
        self.touch()

    def mark_failed(self, error: str, stage: str | None = None) -> None:
        """Mark the run as failed with a short, safe error message (no traceback)."""
        self.status = "failed"
        if stage is not None:
            self.current_stage = str(stage)
        self.error = _safe_error_text(error)
        self.touch()


def _safe_error_text(error: Any, *, max_len: int = 500) -> str:
    text = str(error or "").strip().replace("\r", " ").replace("\n", " ")
    # Drop traceback-like tails if a long message is passed by mistake.
    lower = text.lower()
    for marker in ("traceback (most recent call last)", "traceback:"):
        idx = lower.find(marker)
        if idx >= 0:
            text = text[:idx].strip()
            break
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text or "unknown error"


def _is_sensitive_key(key: Any) -> bool:
    k = str(key).lower().replace("-", "_")
    if k in {"openai_api_key", "tavily_api_key", "api_key"}:
        return True
    return any(marker in k for marker in _SENSITIVE_KEY_MARKERS)


def _type_label(value: Any) -> str:
    module = getattr(type(value), "__module__", "") or ""
    name = getattr(type(value), "__name__", type(value).__name__)
    return f"{module}.{name}" if module else name


def _is_project_internal(value: Any) -> bool:
    """True when the object's type lives under the ``src`` package namespace."""
    module = getattr(type(value), "__module__", "") or ""
    return module == "src" or module.startswith("src.")


def _to_jsonable(value: Any, *, _seen: set[int] | None = None) -> Any:
    """Convert nested values to JSON-safe structures.

    Priority: scalars → Enum → datetime/date → dataclass → dict →
    list/tuple/set → ``to_dict()`` → project-internal public ``__dict__`` →
    stable type placeholder (no memory addresses).
    """
    # 1. Scalars (and None)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    # 2. Enum
    if isinstance(value, Enum):
        return value.value

    # 3. datetime / date
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, bytes):
        return f"<bytes len={len(value)}>"

    # Complex objects — cycle protection (path-based; scalars already returned).
    seen = _seen if _seen is not None else set()
    oid = id(value)
    if oid in seen:
        return "<circular-reference>"

    # 4. dataclass
    if is_dataclass(value) and not isinstance(value, type):
        seen.add(oid)
        try:
            out: dict[str, Any] = {}
            for f in fields(value):
                if _is_sensitive_key(f.name):
                    out[f.name] = "<redacted>"
                    continue
                out[f.name] = _to_jsonable(getattr(value, f.name), _seen=seen)
            return out
        finally:
            seen.discard(oid)

    # 5. dict
    if isinstance(value, dict):
        seen.add(oid)
        try:
            out_dict: dict[str, Any] = {}
            for k, v in value.items():
                key = str(k)
                if _is_sensitive_key(key):
                    out_dict[key] = "<redacted>"
                else:
                    out_dict[key] = _to_jsonable(v, _seen=seen)
            return out_dict
        finally:
            seen.discard(oid)

    # 6. list / tuple / set
    if isinstance(value, (list, tuple)):
        seen.add(oid)
        try:
            return [_to_jsonable(item, _seen=seen) for item in value]
        finally:
            seen.discard(oid)
    if isinstance(value, set):
        seen.add(oid)
        try:
            items = [_to_jsonable(item, _seen=seen) for item in value]
            try:
                return sorted(
                    items,
                    key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True),
                )
            except TypeError:
                return items
        finally:
            seen.discard(oid)

    # 7. Explicit to_dict() (project or otherwise — caller opts in)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        seen.add(oid)
        try:
            return _to_jsonable(to_dict(), _seen=seen)
        except Exception:
            # Fall through to safer handlers rather than leaking exception text.
            pass
        finally:
            seen.discard(oid)

    # 8. Project-internal plain objects via public instance fields only
    if _is_project_internal(value) and hasattr(value, "__dict__"):
        seen.add(oid)
        try:
            out_plain: dict[str, Any] = {}
            for k, v in vars(value).items():
                if k.startswith("_"):
                    continue
                if callable(v):
                    continue
                if _is_sensitive_key(k):
                    out_plain[k] = "<redacted>"
                else:
                    out_plain[k] = _to_jsonable(v, _seen=seen)
            return out_plain
        finally:
            seen.discard(oid)

    # 9. Safe type placeholder (no repr / memory address)
    return f"<{_type_label(value)}>"


def research_state_to_dict(state: ResearchState) -> dict[str, Any]:
    """Serialize ``ResearchState`` to a plain JSON-compatible dict."""
    result = _to_jsonable(state)
    if not isinstance(result, dict):
        raise TypeError("research_state_to_dict expected a dict snapshot")
    return result


def research_state_to_json(state: ResearchState) -> str:
    """Serialize ``ResearchState`` to a UTF-8 JSON string (``ensure_ascii=False``)."""
    return json.dumps(
        research_state_to_dict(state),
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
    )


def research_state_from_dict(data: dict[str, Any]) -> ResearchState:
    """Best-effort restore of scalar shell fields from a snapshot dict.

    Nested artifacts are not reconstructed into full dataclasses in v1.3
    phase 1 — callers that need the nested payload should use the SQLite
    ``state_snapshot`` dict from ``ResearchRunRepository.get_run``.
    """
    if not isinstance(data, dict):
        raise TypeError("research_state_from_dict expects a dict")

    depth_raw = data.get("depth", ResearchDepth.QUICK)
    if isinstance(depth_raw, ResearchDepth):
        depth = depth_raw
    else:
        try:
            depth = ResearchDepth(str(depth_raw))
        except ValueError:
            depth = ResearchDepth.QUICK

    return ResearchState(
        run_id=str(data.get("run_id") or _new_run_id()),
        topic=str(data.get("topic") or ""),
        depth=depth,
        status=str(data.get("status") or "pending"),
        current_stage=str(data.get("current_stage") or "initialized"),
        diagnostics=dict(data.get("diagnostics") or {})
        if isinstance(data.get("diagnostics"), dict)
        else {},
        error=(str(data["error"]) if data.get("error") is not None else None),
        created_at=str(data.get("created_at") or _utc_now_iso()),
        updated_at=str(data.get("updated_at") or _utc_now_iso()),
    )
