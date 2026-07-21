"""Offline tests for Streamlit History helpers (no browser).

Run:
  D:\\python3.11\\python.exe scripts/test_v13_history_ui.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app_service import (
    HISTORY_PAGE_SIZE,
    HistoryStateLoadError,
    calculate_history_pagination,
    count_research_history,
    format_history_error_summary,
    format_history_timestamp,
    get_default_research_repository,
    history_status_note,
    history_summary_display,
    list_research_history,
    load_research_history_state,
    normalize_history_status_filter,
    short_run_id,
    should_reset_history_page,
)
from src.models import ResearchDepth, ResearchReport, ReportSection
from src.research_state import ResearchState
from src.storage import ResearchRunRepository, ResearchRunSummary

PROJECT_DB = _ROOT / "data" / "researchpilot.db"


def test_1_helpers_delegate_to_repository() -> None:
    repo = MagicMock()
    repo.list_runs.return_value = []
    repo.count_runs.return_value = 0
    repo.get_state.return_value = None

    list_research_history(
        limit=10,
        offset=20,
        status="completed",
        topic_query="PCB",
        repository=repo,
    )
    count_research_history(status="failed", topic_query="链", repository=repo)
    load_research_history_state("run-1", repository=repo)

    repo.list_runs.assert_called_once_with(
        limit=10,
        offset=20,
        status="completed",
        topic_query="PCB",
    )
    repo.count_runs.assert_called_once_with(status="failed", topic_query="链")
    repo.get_state.assert_called_once_with("run-1")
    print("PASS 1: history helpers use repository API")


def test_2_import_does_not_create_project_db() -> None:
    existed = PROJECT_DB.exists()
    # Fresh import of helpers must not create the project default DB.
    import src.app_service as app_service

    _ = app_service.list_research_history  # touch module
    if not existed:
        assert not PROJECT_DB.exists()
    with patch.object(app_service, "ResearchRunRepository") as cls:
        instance = MagicMock()
        cls.return_value = instance
        app_service.get_default_research_repository()
        cls.assert_called_once_with()
        instance.initialize.assert_called_once()
    if not existed:
        assert not PROJECT_DB.exists()
    print("PASS 2: import/lazy init does not require project DB")


def test_3_pagination_math() -> None:
    empty = calculate_history_pagination(0, 1, 10)
    assert empty.total_pages == 0
    assert empty.page == 1
    assert empty.offset == 0

    first = calculate_history_pagination(25, 1, 10)
    assert first.page == 1 and first.offset == 0 and first.total_pages == 3

    mid = calculate_history_pagination(25, 2, 10)
    assert mid.page == 2 and mid.offset == 10

    last = calculate_history_pagination(25, 3, 10)
    assert last.page == 3 and last.offset == 20

    clamped = calculate_history_pagination(25, 99, 10)
    assert clamped.page == 3 and clamped.offset == 20

    try:
        calculate_history_pagination(10, 1, 0)
        raise AssertionError("page_size=0 should raise")
    except ValueError:
        pass
    try:
        calculate_history_pagination(10, True, 10)  # type: ignore[arg-type]
        raise AssertionError("page=True should raise")
    except TypeError:
        pass
    print("PASS 3: pagination calculation")


def test_4_filter_change_resets_page() -> None:
    assert should_reset_history_page("", "All", "PCB", "All") is True
    assert should_reset_history_page("PCB", "All", "PCB", "failed") is True
    assert should_reset_history_page("PCB", "failed", "PCB", "failed") is False
    assert should_reset_history_page("  ", "All", "", "All") is False
    print("PASS 4: filter change reset detection")


def test_5_summary_display_helpers() -> None:
    assert short_run_id("abcdef0123456789") == "abcdef01"
    assert format_history_timestamp("2026-07-01T12:30:00Z") == "2026-07-01 12:30 UTC"
    assert format_history_timestamp("not-a-date") == "not-a-date"
    assert format_history_error_summary("x" * 200).endswith("…")
    assert history_status_note("running") == "This run may have been interrupted."
    assert history_status_note("failed")
    assert history_status_note("completed") is None

    summary = ResearchRunSummary(
        run_id="deadbeef-cafebabe",
        topic="PCB",
        depth="quick",
        status="failed",
        current_stage="reading",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        error_message="boom",
    )
    display = history_summary_display(summary)
    assert display["short_run_id"] == "deadbeef"
    assert display["error_summary"] == "boom"
    assert display["status_note"]
    assert normalize_history_status_filter("All") is None
    assert normalize_history_status_filter(" completed ") == "completed"
    assert HISTORY_PAGE_SIZE == 10
    print("PASS 5: summary display helpers")


def test_6_detail_load_from_temp_db() -> None:
    with TemporaryDirectory(prefix="rp_hist_detail_", ignore_cleanup_errors=True) as td:
        db = Path(td) / "h.db"
        repo = ResearchRunRepository(db)
        repo.initialize()

        completed = ResearchState(
            topic="完成主题",
            depth=ResearchDepth.QUICK,
            run_id="done-1",
            status="completed",
            current_stage="completed",
        )
        completed.report = ResearchReport(
            topic="完成主题",
            depth=ResearchDepth.QUICK,
            sections=[ReportSection(title="摘要", content="ok")],
        )
        failed = ResearchState(
            topic="失败主题",
            depth=ResearchDepth.QUICK,
            run_id="fail-1",
            status="failed",
            current_stage="reading",
            error="reader timeout",
        )
        running = ResearchState(
            topic="中断主题",
            depth=ResearchDepth.STANDARD,
            run_id="run-1",
            status="running",
            current_stage="searching",
        )
        for state in (completed, failed, running):
            repo.save_state(state)

        loaded = load_research_history_state("done-1", repository=repo)
        assert loaded is not None
        assert loaded.report is not None
        assert loaded.report.sections[0].title == "摘要"

        failed_loaded = load_research_history_state("fail-1", repository=repo)
        assert failed_loaded is not None
        assert failed_loaded.error == "reader timeout"
        assert failed_loaded.current_stage == "reading"

        running_loaded = load_research_history_state("run-1", repository=repo)
        assert running_loaded is not None
        assert running_loaded.status == "running"
    print("PASS 6: detail load completed/failed/running")


def test_7_empty_database() -> None:
    with TemporaryDirectory(prefix="rp_hist_empty_", ignore_cleanup_errors=True) as td:
        repo = ResearchRunRepository(Path(td) / "empty.db")
        repo.initialize()
        assert list_research_history(repository=repo) == []
        assert count_research_history(repository=repo) == 0
        assert load_research_history_state("missing", repository=repo) is None
    print("PASS 7: empty database helpers")


def test_8_corrupt_detail_isolated() -> None:
    repo = MagicMock()
    repo.get_state.side_effect = ValueError("bad snapshot")
    repo.list_runs.return_value = [
        ResearchRunSummary(
            run_id="bad-1",
            topic="x",
            depth="quick",
            status="completed",
            current_stage="completed",
            created_at="t",
            updated_at="t",
            error_message=None,
        )
    ]
    rows = list_research_history(repository=repo)
    assert len(rows) == 1
    try:
        load_research_history_state("bad-1", repository=repo)
        raise AssertionError("expected HistoryStateLoadError")
    except HistoryStateLoadError as exc:
        assert exc.run_id == "bad-1"
    print("PASS 8: corrupt detail isolated from list")


def main() -> int:
    test_1_helpers_delegate_to_repository()
    test_2_import_does_not_create_project_db()
    test_3_pagination_math()
    test_4_filter_change_resets_page()
    test_5_summary_display_helpers()
    test_6_detail_load_from_temp_db()
    test_7_empty_database()
    test_8_corrupt_detail_isolated()
    print("ALL HISTORY UI HELPER TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
