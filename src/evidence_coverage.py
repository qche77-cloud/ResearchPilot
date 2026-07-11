"""Shared coverage targets for Searcher candidate pools and Evaluator retention."""

from __future__ import annotations

from src.models import ResearchDepth


def coverage_limits(depth: ResearchDepth) -> tuple[int, int]:
    """Return ``(per_task_target, max_total)`` for coverage-aware retention.

    Standard depth targets ~2 sources per major task and 10–12 total.
    """
    if depth == ResearchDepth.QUICK:
        return 2, 8
    if depth == ResearchDepth.STANDARD:
        return 2, 12
    return 2, 14


def search_candidate_limit(depth: ResearchDepth, task_count: int) -> int:
    """How many unique sources Searcher should pass to Reader.

    Larger than final retention so failed reads still leave task coverage.
    """
    per_task, max_total = coverage_limits(depth)
    tasks = max(1, task_count)
    pool = max(max_total, per_task * tasks)
    pool = min(pool + max(2, tasks), 24)
    return pool
