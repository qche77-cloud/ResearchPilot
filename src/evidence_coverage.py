"""Shared coverage targets for Searcher candidate pools and Evaluator retention."""

from __future__ import annotations

from src.models import ResearchDepth


def coverage_limits(depth: ResearchDepth) -> tuple[int, int]:
    """Return ``(per_task_target, max_total)`` for coverage-aware retention.

    v1.1 targets (approximate, not hard quotas):
    - Quick: ~2/task, 8–12 total
    - Standard: ~3–4/task, 15–20 total
    - Deep: ~4–6/task, 25–35 total
    """
    if depth == ResearchDepth.QUICK:
        return 2, 12
    if depth == ResearchDepth.STANDARD:
        return 3, 18
    return 5, 30


def search_candidate_limit(depth: ResearchDepth, task_count: int) -> int:
    """How many unique sources Searcher should pass to Reader.

    Larger than final retention so failed reads still leave task coverage.
    """
    per_task, max_total = coverage_limits(depth)
    tasks = max(1, task_count)
    # Aim for per-task * tasks, within the documented band.
    if depth == ResearchDepth.QUICK:
        pool = max(8, min(12, per_task * tasks + 2))
    elif depth == ResearchDepth.STANDARD:
        pool = max(15, min(20, per_task * tasks + 2))
    else:
        pool = max(25, min(35, per_task * tasks + 4))
    # Never go below retention max_total.
    return max(pool, max_total)
