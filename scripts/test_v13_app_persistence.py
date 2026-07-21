"""Offline tests for Streamlit MVP → persisted research wiring.

Does not start a browser. Tests ``src.app_service`` (UI entry helper).

Run:
  D:\\python3.11\\python.exe scripts/test_v13_app_persistence.py
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app_service import execute_research_request, short_run_id
from src.models import (
    ResearchDepth,
    ResearchPlan,
    ResearchReport,
    ReportSection,
    ResearchResult,
)
from src.research_service import PersistedResearchResult, ResearchPersistenceError
from src.research_state import ResearchState


def _fake_result(topic: str = "PCB产业链") -> ResearchResult:
    plan = ResearchPlan(topic=topic, depth=ResearchDepth.QUICK)
    report = ResearchReport(
        topic=topic,
        depth=ResearchDepth.QUICK,
        sections=[ReportSection("摘要", "ok")],
    )
    return ResearchResult(plan=plan, sources=[], report=report)


def test_ui_calls_persisted_service_not_run_research() -> None:
    calls: list[tuple] = []

    def fake_persisted(topic, depth, **kwargs):
        calls.append((topic, depth, kwargs))
        state = ResearchState(topic=topic, depth=depth, run_id="abc123deadbeef")
        return PersistedResearchResult(
            run_id=state.run_id,
            result=_fake_result(topic),
            state=state,
        )

    with patch("src.app_service.run_persisted_research", side_effect=fake_persisted):
        with patch("src.pipeline.run_research") as rr:
            out = execute_research_request("PCB产业链", ResearchDepth.QUICK)
            assert rr.call_count == 0

    assert len(calls) == 1
    assert calls[0][0] == "PCB产业链"
    assert calls[0][1] == ResearchDepth.QUICK
    assert calls[0][2] == {}
    assert isinstance(out, PersistedResearchResult)
    assert out.result.report.sections
    print("PASS 1: UI helper calls run_persisted_research without db_path/repository")


def test_returned_result_compatible() -> None:
    state = ResearchState(topic="x", depth=ResearchDepth.STANDARD, run_id="deadbeefcafebabe")
    result = _fake_result("x")
    persisted = PersistedResearchResult(run_id=state.run_id, result=result, state=state)

    with patch("src.app_service.run_persisted_research", return_value=persisted):
        out = execute_research_request("x", ResearchDepth.STANDARD)

    assert out.result is result
    assert isinstance(out.result, ResearchResult)
    assert out.result.report.sections[0].title == "摘要"
    assert out.run_id == "deadbeefcafebabe"
    assert short_run_id(out.run_id) == "deadbeef"
    print("PASS 2: PersistedResearchResult.result is ResearchResult-compatible")


def test_persistence_error_not_swallowed() -> None:
    result = _fake_result()
    state = ResearchState(topic="PCB产业链", depth=ResearchDepth.QUICK, run_id="ff" * 16)

    def boom(*_a, **_k):
        raise ResearchPersistenceError(
            "failed to persist",
            run_id=state.run_id,
            result=result,
            state=state,
        )

    with patch("src.app_service.run_persisted_research", side_effect=boom):
        try:
            execute_research_request("PCB产业链", ResearchDepth.QUICK)
            raise AssertionError("expected ResearchPersistenceError")
        except ResearchPersistenceError as exc:
            assert exc.result is result
            assert exc.run_id == state.run_id
    print("PASS 3: ResearchPersistenceError propagates from helper")


def test_default_db_path_not_passed() -> None:
    seen: dict = {}

    def capture(topic, depth, **kwargs):
        seen["kwargs"] = dict(kwargs)
        seen["topic"] = topic
        seen["depth"] = depth
        state = ResearchState(topic=topic, depth=depth)
        return PersistedResearchResult(
            run_id=state.run_id,
            result=_fake_result(topic),
            state=state,
        )

    with patch("src.app_service.run_persisted_research", side_effect=capture):
        execute_research_request("卫星通信", ResearchDepth.DEEP)

    assert "repository" not in seen["kwargs"]
    assert "db_path" not in seen["kwargs"]
    assert "run_id" not in seen["kwargs"]
    assert seen["depth"] == ResearchDepth.DEEP
    # Helper signature itself has no repository/db_path
    params = inspect.signature(execute_research_request).parameters
    assert "repository" not in params
    assert "db_path" not in params
    print("PASS 4: default database path left to service layer")


def test_mvp_result_structure() -> None:
    result = _fake_result("圣泉集团")
    assert result.report.sections
    assert result.plan.topic == "圣泉集团"
    print("PASS 5: MVP ResearchResult structure unchanged for display")


def main() -> int:
    test_ui_calls_persisted_service_not_run_research()
    test_returned_result_compatible()
    test_persistence_error_not_swallowed()
    test_default_db_path_not_passed()
    test_mvp_result_structure()
    print("\nAll v1.3 app persistence tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
