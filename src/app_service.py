"""Thin UI-facing helpers for Streamlit → persisted research wiring."""

from __future__ import annotations

from src.models import ResearchDepth
from src.research_service import PersistedResearchResult, run_persisted_research


def execute_research_request(
    topic: str,
    depth: ResearchDepth,
) -> PersistedResearchResult:
    """Run research via the persisted service using the default SQLite path.

    Does not accept ``repository`` / ``db_path`` — callers rely on
    ``data/researchpilot.db`` from the service layer.
    """
    return run_persisted_research(topic, depth)


def short_run_id(run_id: str | None) -> str:
    """Display-friendly run id prefix (8 chars)."""
    if not run_id:
        return ""
    text = str(run_id).strip()
    return text[:8] if len(text) > 8 else text
