"""Persisted research runtime — thin SQLite integration over ``run_research``.

Assembles ResearchState + ResearchRunRepository + pipeline checkpoints.
Does not reimplement Planner/Searcher/Reader/Evaluator logic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from src.models import ResearchDepth, ResearchResult
from src.pipeline import run_research
from src.research_state import ResearchState
from src.storage import DEFAULT_DB_PATH, ResearchRunRepository


class ResearchPersistenceError(RuntimeError):
    """Raised when the final ResearchState snapshot could not be persisted."""


@dataclass
class PersistedResearchResult:
    """Result of a persisted research run (pipeline + SQLite snapshot)."""

    run_id: str
    result: ResearchResult
    state: ResearchState


def run_persisted_research(
    topic: str,
    depth: ResearchDepth,
    *,
    repository: ResearchRunRepository | None = None,
    db_path: str | Path | None = None,
    run_id: str | None = None,
) -> PersistedResearchResult:
    """Run research with automatic ResearchState checkpoints to SQLite.

    Args:
        topic: Research topic (non-empty).
        depth: Research depth enum.
        repository: Existing repository (mutually exclusive with ``db_path``).
        db_path: SQLite path; creates a repository if ``repository`` is omitted.
            When both ``repository`` and ``db_path`` are omitted, uses
            ``data/researchpilot.db``.
        run_id: Optional stable id (``uuid4().hex`` when omitted). Rejected if
            the id already exists in the repository (no overwrite / no resume).

    Returns:
        ``PersistedResearchResult`` with the pipeline ``ResearchResult`` and
        the final in-memory ``ResearchState``.

    Raises:
        ValueError: Invalid inputs, repository/db_path conflict, or duplicate
            ``run_id``.
        TypeError: ``depth`` is not a ``ResearchDepth``.
        ResearchPersistenceError: Workflow succeeded but the final snapshot
            could not be saved.
        Exception: Any business exception from ``run_research`` is re-raised
            unchanged after a best-effort final save.
    """
    topic_clean = (topic or "").strip()
    if not topic_clean:
        raise ValueError("Research topic cannot be empty.")
    if not isinstance(depth, ResearchDepth):
        raise TypeError("depth must be a ResearchDepth enum value")
    if run_id is not None and not str(run_id).strip():
        raise ValueError("run_id cannot be empty")

    repo = _resolve_repository(repository=repository, db_path=db_path)
    repo.initialize()

    resolved_id = str(run_id).strip() if run_id is not None else uuid.uuid4().hex
    if repo.exists(resolved_id):
        raise ValueError(f"run_id already exists: {resolved_id}")

    state = ResearchState(topic=topic_clean, depth=depth, run_id=resolved_id)
    # Persist initialized snapshot before pipeline (may be upserted again).
    repo.save_state(state)

    try:
        result = run_research(
            topic_clean,
            depth,
            research_state=state,
            state_callback=repo.save_state,
        )
    except Exception:
        # Pipeline already mark_failed + callback; best-effort final snapshot.
        _best_effort_save(repo, state)
        raise

    try:
        repo.save_state(state)
    except Exception as exc:  # noqa: BLE001
        raise ResearchPersistenceError(
            f"failed to persist completed research run {state.run_id}"
        ) from exc

    return PersistedResearchResult(run_id=state.run_id, result=result, state=state)


def _resolve_repository(
    *,
    repository: ResearchRunRepository | None,
    db_path: str | Path | None,
) -> ResearchRunRepository:
    if repository is not None and db_path is not None:
        raise ValueError("Pass either repository or db_path, not both")
    if repository is not None:
        return repository
    path = Path(db_path) if db_path is not None else Path(DEFAULT_DB_PATH)
    return ResearchRunRepository(path)


def _best_effort_save(repo: ResearchRunRepository, state: ResearchState) -> None:
    try:
        repo.save_state(state)
    except Exception as exc:  # noqa: BLE001
        bucket = state.diagnostics.setdefault("state_persistence", {})
        if not isinstance(bucket, dict):
            bucket = {}
            state.diagnostics["state_persistence"] = bucket
        bucket["final_save_failed"] = True
        bucket["final_save_error_type"] = type(exc).__name__
        msg = f"{type(exc).__name__}: {exc}".replace("\n", " ").strip()
        if len(msg) > 240:
            msg = msg[:239].rstrip() + "…"
        bucket["final_save_error_message"] = msg
