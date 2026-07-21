"""Offline v1.3 persisted research service integration tests.

Uses TemporaryDirectory SQLite DBs and mocked pipeline components.
No OpenAI, Tavily, network, or real .env.

Run:
  D:\\python3.11\\python.exe scripts/test_v13_persisted_research.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.models import (
    AnalyzedQuery,
    EvidenceDocument,
    EvaluatedEvidence,
    QueryType,
    ResearchDepth,
    ResearchPlan,
    ResearchPlanStep,
    ResearchReport,
    ReportSection,
    ResearchResult,
    Source,
    SynthesisBrief,
)
from src.pipeline import run_research
from src.research_service import (
    PersistedResearchResult,
    ResearchPersistenceError,
    run_persisted_research,
)
from src.research_state import ResearchState
from src.storage import DEFAULT_DB_PATH, ResearchRunRepository

PROJECT_DB = _ROOT / "data" / "researchpilot.db"


def _source(sid: str, task: str = "产业链拆解") -> Source:
    return Source(
        title=f"t-{sid}",
        url=f"https://example.com/{sid}",
        snippet="snippet " * 10,
        source_type="web",
        relevance=0.9,
        research_task=task,
        source_id=sid,
    )


def _doc(source: Source) -> EvidenceDocument:
    text = "offline content " * 20
    return EvidenceDocument(
        source=source,
        extracted_text=text,
        word_count=40,
        read_status="success",
        extraction_status="FULL_TEXT",
        snippet_fallback=False,
        extracted_char_count=len(text),
    )


def _ev(doc: EvidenceDocument) -> EvaluatedEvidence:
    return EvaluatedEvidence(
        document=doc,
        credibility_score=80,
        relevance_score=80,
        recency_score=80,
        final_score=80,
        evaluation_reason="ok",
        keep=True,
        freshness_score=80,
        age_days=10,
    )


def _plan(topic: str) -> ResearchPlan:
    return ResearchPlan(
        topic=topic,
        depth=ResearchDepth.QUICK,
        query_type=QueryType.INDUSTRY,
        steps=[ResearchPlanStep(1, "产业链拆解", "结构", ["q1"])],
        planner_source="rules",
    )


def _offline_components(*, topic: str = "PCB产业链", fail_at: str | None = None):
    plan = _plan(topic)
    analyzed = AnalyzedQuery(
        raw_query=topic,
        query_type=QueryType.INDUSTRY,
        normalized_topic=topic,
        research_goal="g",
    )
    sources = [_source("S1"), _source("S2", "近期催化")]

    analyzer = MagicMock()
    analyzer.analyze.side_effect = (
        RuntimeError("analyze boom")
        if fail_at == "analyzing"
        else (lambda q: analyzed)
    )

    planner = MagicMock()
    planner.last_warning = None
    if fail_at == "planning":
        planner.plan.side_effect = RuntimeError("planning boom")
    else:
        planner.plan.return_value = plan

    searcher = MagicMock()
    searcher.last_warning = None
    searcher.last_diagnostics = {"mode": "mock", "queries_executed": 1}
    searcher.search.return_value = list(sources)
    searcher.followup_search.return_value = []
    searcher.find_replacement_source.return_value = (None, None)

    reader = MagicMock()
    reader.last_diagnostics = {"funnel": {}}
    reader._pdf_attempts = 0
    reader._pdf_successes = 0
    reader._domain_extract_used = 0
    reader.read.side_effect = lambda srcs: [_doc(s) for s in srcs]
    reader._read_one.side_effect = lambda s: _doc(s)

    evaluator = MagicMock()
    evaluator.last_diagnostics = {}
    evaluator.evaluate.side_effect = lambda docs, _p: [_ev(d) for d in docs]

    synthesizer = MagicMock()
    synthesizer.last_warning = None
    synthesizer.last_diagnostics = {"synthesizer_source": "fallback"}
    synthesizer.synthesize.side_effect = lambda p, ev: SynthesisBrief(
        topic=p.topic,
        depth=p.depth,
        synthesizer_source="fallback",
        evidence_index={f"E{i+1}": e for i, e in enumerate(ev)},
    )

    writer = MagicMock()
    writer.last_warning = None
    writer.last_diagnostics = {"writer_source": "fallback"}

    def _write(p, synthesis, research_health=None):
        if fail_at == "writing":
            raise RuntimeError("writing boom")
        return ResearchReport(
            topic=p.topic,
            depth=p.depth,
            sections=[ReportSection("摘要", f"{p.topic} ok")],
            writer_source="fallback",
        )

    writer.write.side_effect = _write

    return {
        "QueryAnalyzer": MagicMock(return_value=analyzer),
        "Planner": MagicMock(return_value=planner),
        "Searcher": MagicMock(return_value=searcher),
        "Reader": MagicMock(return_value=reader),
        "EvidenceEvaluator": MagicMock(return_value=evaluator),
        "Synthesizer": MagicMock(return_value=synthesizer),
        "Writer": MagicMock(return_value=writer),
    }


def _patch_pipeline(comps: dict):
    return patch.multiple(
        "src.pipeline",
        QueryAnalyzer=comps["QueryAnalyzer"],
        Planner=comps["Planner"],
        Searcher=comps["Searcher"],
        Reader=comps["Reader"],
        EvidenceEvaluator=comps["EvidenceEvaluator"],
        Synthesizer=comps["Synthesizer"],
        Writer=comps["Writer"],
    )


class FlakyRepository(ResearchRunRepository):
    """Allows the first save (initialized), then fails the next ``fail_times`` saves."""

    def __init__(self, db_path: Path, *, fail_times: int = 2) -> None:
        super().__init__(db_path)
        self.fail_times = fail_times
        self.save_calls = 0

    def save_state(self, state: ResearchState) -> None:
        self.save_calls += 1
        # Call 1 = service pre-pipeline initialized snapshot (must succeed).
        if 2 <= self.save_calls <= 1 + self.fail_times:
            raise RuntimeError(f"transient save failure #{self.save_calls}")
        super().save_state(state)


class FailAfterInitRepository(ResearchRunRepository):
    """First save succeeds; every later save_state fails (including final)."""

    def __init__(self, db_path: Path) -> None:
        super().__init__(db_path)
        self.save_calls = 0

    def save_state(self, state: ResearchState) -> None:
        self.save_calls += 1
        if self.save_calls == 1:
            super().save_state(state)
            return
        raise RuntimeError("disk full: cannot save state")


def test_success_persisted(tmp: Path) -> None:
    db = tmp / "ok.db"
    comps = _offline_components()
    with _patch_pipeline(comps):
        out = run_persisted_research(
            "PCB产业链",
            ResearchDepth.QUICK,
            db_path=db,
        )
    assert isinstance(out, PersistedResearchResult)
    assert out.run_id
    assert isinstance(out.result, ResearchResult)
    assert out.state.status == "completed"
    assert out.state.current_stage == "completed"
    assert out.state.report is not None
    assert db.is_file()

    repo = ResearchRunRepository(db)
    row = repo.get_run(out.run_id)
    assert row is not None
    assert row["status"] == "completed"
    assert row["current_stage"] == "completed"
    snap = row["state_snapshot"]
    assert isinstance(snap, dict)
    assert snap.get("report") is not None
    assert "diagnostics" in snap
    print("PASS 1: success run persisted as completed")


def test_custom_run_id(tmp: Path) -> None:
    db = tmp / "custom.db"
    rid = "fixedrunid001abc"
    comps = _offline_components()
    with _patch_pipeline(comps):
        out = run_persisted_research(
            "PCB产业链",
            ResearchDepth.QUICK,
            db_path=db,
            run_id=rid,
        )
    assert out.run_id == rid
    assert out.state.run_id == rid
    row = ResearchRunRepository(db).get_run(rid)
    assert row is not None
    assert row["run_id"] == rid
    print("PASS 2: custom run_id persisted")


def test_external_repository(tmp: Path) -> None:
    db = tmp / "ext.db"
    repo = ResearchRunRepository(db)
    repo.initialize()
    comps = _offline_components()
    with _patch_pipeline(comps):
        out = run_persisted_research(
            "圣泉集团",
            ResearchDepth.STANDARD,
            repository=repo,
        )
    assert ResearchRunRepository(db).exists(out.run_id)
    assert out.state.topic == "圣泉集团"
    print("PASS 3: external repository used")


def test_repository_and_db_path_conflict(tmp: Path) -> None:
    db = tmp / "conflict.db"
    repo = ResearchRunRepository(db)
    try:
        run_persisted_research(
            "x",
            ResearchDepth.QUICK,
            repository=repo,
            db_path=db,
        )
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "not both" in str(exc).lower() or "either" in str(exc).lower()
    print("PASS 4: repository + db_path conflict raises ValueError")


def test_duplicate_run_id_rejected(tmp: Path) -> None:
    db = tmp / "dup.db"
    rid = "duprunidabcdef12"
    comps = _offline_components()
    with _patch_pipeline(comps):
        first = run_persisted_research(
            "PCB产业链",
            ResearchDepth.QUICK,
            db_path=db,
            run_id=rid,
        )
    assert first.state.status == "completed"
    before = ResearchRunRepository(db).get_run(rid)
    assert before is not None
    before_updated = before["updated_at"]

    comps2 = _offline_components(topic="卫星通信")
    with _patch_pipeline(comps2):
        try:
            run_persisted_research(
                "卫星通信",
                ResearchDepth.QUICK,
                db_path=db,
                run_id=rid,
            )
            raise AssertionError("expected duplicate ValueError")
        except ValueError as exc:
            assert "already exists" in str(exc)

    after = ResearchRunRepository(db).get_run(rid)
    assert after is not None
    assert after["topic"] == "PCB产业链"
    assert after["status"] == "completed"
    assert after["updated_at"] == before_updated
    print("PASS 5: duplicate run_id rejected; old row intact")


def test_workflow_failure_persists_failed(tmp: Path) -> None:
    db = tmp / "fail.db"
    rid = "failrunidabcdef1"
    comps = _offline_components(fail_at="planning")
    raised = None
    with _patch_pipeline(comps):
        try:
            run_persisted_research(
                "PCB产业链",
                ResearchDepth.QUICK,
                db_path=db,
                run_id=rid,
            )
        except RuntimeError as exc:
            raised = exc
    assert raised is not None
    assert "planning boom" in str(raised)
    row = ResearchRunRepository(db).get_run(rid)
    assert row is not None
    assert row["status"] == "failed"
    assert row["error_message"]
    assert "Traceback" not in (row["error_message"] or "")
    assert row["current_stage"] == "planning"
    print("PASS 6: workflow failure persists failed status and re-raises")


def test_mid_callback_failure_recovers(tmp: Path) -> None:
    db = tmp / "flaky.db"
    repo = FlakyRepository(db, fail_times=2)
    repo.initialize()
    comps = _offline_components()
    with _patch_pipeline(comps):
        out = run_persisted_research(
            "PCB产业链",
            ResearchDepth.QUICK,
            repository=repo,
        )
    assert out.state.status == "completed"
    row = ResearchRunRepository(db).get_run(out.run_id)
    assert row is not None
    assert row["status"] == "completed"
    persist = out.state.diagnostics.get("state_persistence") or {}
    assert int(persist.get("failure_count") or 0) > 0
    print("PASS 7: mid-run save failures recovered; final completed")


def test_final_persistence_failure(tmp: Path) -> None:
    db = tmp / "nosave.db"
    repo = FailAfterInitRepository(db)
    repo.initialize()
    comps = _offline_components()
    with _patch_pipeline(comps):
        try:
            out = run_persisted_research(
                "PCB产业链",
                ResearchDepth.QUICK,
                repository=repo,
            )
            raise AssertionError(f"expected ResearchPersistenceError, got {out!r}")
        except ResearchPersistenceError:
            pass
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(f"wrong exception type: {type(exc)}: {exc}") from exc
    # Initial row may exist, but must not be a successful completed persistence return.
    rows = ResearchRunRepository(db).list_runs(limit=5)
    assert all(r.get("status") != "completed" for r in rows)
    print("PASS 8: final persistence failure raises ResearchPersistenceError")


def test_run_research_compat(tmp: Path) -> None:
    comps = _offline_components()
    with _patch_pipeline(comps):
        result = run_research("PCB产业链", ResearchDepth.QUICK)
    assert isinstance(result, ResearchResult)
    assert result.report is not None
    assert result.report.sections
    if not PROJECT_DB.exists():
        assert not PROJECT_DB.exists()
    print("PASS 9: plain run_research remains compatible")


def test_input_validation(tmp: Path) -> None:
    db = tmp / "val.db"
    try:
        run_persisted_research("   ", ResearchDepth.QUICK, db_path=db)
        raise AssertionError("empty topic")
    except ValueError:
        pass
    try:
        run_persisted_research("x", "Quick", db_path=db)  # type: ignore[arg-type]
        raise AssertionError("bad depth")
    except TypeError:
        pass
    try:
        run_persisted_research("x", ResearchDepth.QUICK, db_path=db, run_id="  ")
        raise AssertionError("empty run_id")
    except ValueError:
        pass
    print("PASS 10: input validation")


def main() -> int:
    project_db_existed = PROJECT_DB.exists()
    with TemporaryDirectory(prefix="rp_v13_persist_", ignore_cleanup_errors=True) as td:
        tmp = Path(td)
        test_success_persisted(tmp)
        test_custom_run_id(tmp)
        test_external_repository(tmp)
        test_repository_and_db_path_conflict(tmp)
        test_duplicate_run_id_rejected(tmp)
        test_workflow_failure_persists_failed(tmp)
        test_mid_callback_failure_recovers(tmp)
        test_final_persistence_failure(tmp)
        test_run_research_compat(tmp)
        test_input_validation(tmp)
        assert str(DEFAULT_DB_PATH).replace("\\", "/").endswith("data/researchpilot.db")
        assert PROJECT_DB.resolve() != (tmp / "ok.db").resolve()
    if not project_db_existed:
        assert not PROJECT_DB.exists(), "tests must not create project DB"
    print("\nAll v1.3 persisted research tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
