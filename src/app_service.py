"""Thin UI-facing helpers for Streamlit → persisted research wiring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.models import ResearchDepth
from src.research_service import PersistedResearchResult, run_persisted_research
from src.research_state import ResearchState
from src.storage import ResearchRunRepository, ResearchRunSummary

HISTORY_PAGE_SIZE = 10
HISTORY_STATUS_OPTIONS = ("All", "completed", "failed", "running")


class HistoryStateLoadError(Exception):
    """Raised when a history row exists but ``get_state`` cannot hydrate it."""

    def __init__(self, run_id: str, message: str = "unable to load research state") -> None:
        self.run_id = run_id
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class HistoryPagination:
    """Resolved page window for history list queries."""

    page: int
    total_pages: int
    offset: int
    page_size: int
    total: int


def execute_research_request(
    topic: str,
    depth: ResearchDepth,
) -> PersistedResearchResult:
    """Run research via the persisted service using the default SQLite path.

    Does not accept ``repository`` / ``db_path`` — callers rely on
    ``data/researchpilot.db`` from the service layer.
    """
    return run_persisted_research(topic, depth)


def short_run_id(run_id: str | None, *, length: int = 8) -> str:
    """Display-friendly run id prefix (default 8 chars)."""
    if not run_id:
        return ""
    text = str(run_id).strip()
    n = max(1, int(length))
    return text[:n] if len(text) > n else text


def get_default_research_repository() -> ResearchRunRepository:
    """Return a repository for the default DB path (initializes schema if needed).

    Importing this module does not create the database; calling this function does.
    """
    repo = ResearchRunRepository()
    repo.initialize()
    return repo


def list_research_history(
    *,
    limit: int = HISTORY_PAGE_SIZE,
    offset: int = 0,
    status: str | None = None,
    topic_query: str | None = None,
    repository: ResearchRunRepository | None = None,
) -> list[ResearchRunSummary]:
    """List history summaries via ``ResearchRunRepository.list_runs``."""
    repo = repository if repository is not None else get_default_research_repository()
    return repo.list_runs(
        limit=limit,
        offset=offset,
        status=status,
        topic_query=topic_query,
    )


def count_research_history(
    *,
    status: str | None = None,
    topic_query: str | None = None,
    repository: ResearchRunRepository | None = None,
) -> int:
    """Count history rows via ``ResearchRunRepository.count_runs``."""
    repo = repository if repository is not None else get_default_research_repository()
    return repo.count_runs(status=status, topic_query=topic_query)


def load_research_history_state(
    run_id: str,
    *,
    repository: ResearchRunRepository | None = None,
) -> ResearchState | None:
    """Load a full ``ResearchState`` for history detail.

    Returns ``None`` when the run is missing. Raises ``HistoryStateLoadError``
    when the row cannot be hydrated (corrupt / incompatible snapshot).
    """
    repo = repository if repository is not None else get_default_research_repository()
    try:
        return repo.get_state(run_id)
    except Exception as exc:  # noqa: BLE001 — isolate bad snapshots from list UI
        raise HistoryStateLoadError(str(run_id), "unable to load research state") from exc


def normalize_history_status_filter(status_label: str | None) -> str | None:
    """Map UI status label to repository ``status`` argument (``All`` → None)."""
    if status_label is None:
        return None
    text = str(status_label).strip()
    if not text or text.lower() == "all":
        return None
    return text


def calculate_history_pagination(
    total: int,
    page: int,
    page_size: int = HISTORY_PAGE_SIZE,
) -> HistoryPagination:
    """Clamp page into a valid window and compute SQL offset."""
    if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size <= 0:
        raise ValueError("page_size must be a positive integer")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ValueError("total must be an int >= 0")
    if not isinstance(page, int) or isinstance(page, bool):
        raise TypeError("page must be an int")

    total_pages = 0 if total == 0 else (total + page_size - 1) // page_size
    if total_pages == 0:
        safe_page = 1
        offset = 0
    else:
        safe_page = min(max(page, 1), total_pages)
        offset = (safe_page - 1) * page_size
    return HistoryPagination(
        page=safe_page,
        total_pages=total_pages,
        offset=offset,
        page_size=page_size,
        total=total,
    )


def should_reset_history_page(
    previous_topic: str | None,
    previous_status: str | None,
    topic_query: str | None,
    status_label: str | None,
) -> bool:
    """Return True when topic/status filters changed (page should reset to 1)."""
    prev_t = (previous_topic or "").strip()
    next_t = (topic_query or "").strip()
    prev_s = (previous_status or "All").strip() or "All"
    next_s = (status_label or "All").strip() or "All"
    return prev_t != next_t or prev_s != next_s


def format_history_timestamp(value: str | None) -> str:
    """Format an ISO-ish timestamp for display; fall back to the raw string."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return text


def format_history_error_summary(error_message: str | None, *, max_len: int = 120) -> str:
    """Short one-line error for history list cards."""
    if not error_message:
        return ""
    text = str(error_message).strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def history_status_note(status: str | None) -> str | None:
    """Optional user-facing note for non-completed runs."""
    if status == "running":
        return "This run may have been interrupted."
    if status == "failed":
        return "This research run failed before completion."
    return None


def history_summary_display(summary: ResearchRunSummary) -> dict[str, Any]:
    """Pure display model for one history list row (no Streamlit imports)."""
    return {
        "run_id": summary.run_id,
        "short_run_id": short_run_id(summary.run_id),
        "topic": summary.topic,
        "status": summary.status,
        "depth": summary.depth,
        "current_stage": summary.current_stage,
        "updated_at": format_history_timestamp(summary.updated_at),
        "updated_at_raw": summary.updated_at,
        "error_summary": format_history_error_summary(summary.error_message),
        "status_note": history_status_note(summary.status),
    }
