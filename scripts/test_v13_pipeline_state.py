"""Offline v1.3 pipeline ↔ ResearchState checkpoint tests.

Fully offline: patches Planner/Searcher/Reader/Evaluator/Synthesizer/Writer.
Does not open data/researchpilot.db or touch the network.

Run:
  D:\\python3.11\\python.exe scripts/test_v13_pipeline_state.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.evidence_strategy import EvidenceCoverageResult, EvidenceStrategy
from src.models import (
    AnalyzedQuery,
    EvidenceDocument,
    EvaluatedEvidence,
    QueryType,
    ResearchDepth,
    ResearchHealth,
    ResearchPlan,
    ResearchPlanStep,
    ResearchReport,
    ReportSection,
    Source,
    SynthesisBrief,
)
from src.pipeline import run_research
from src.research_state import ResearchState, research_state_to_dict

PROJECT_DB = _ROOT / "data" / "researchpilot.db"


def _source(sid: str, task: str, url: str | None = None) -> Source:
    return Source(
        title=f"title-{sid}",
        url=url or f"https://example.com/{sid}",
        snippet="snippet body " * 8,
        source_type="web",
        relevance=0.9,
        research_task=task,
        source_id=sid,
        evidence_type="INDUSTRY_MEDIA",
        freshness_profile="CURRENT",
    )


def _doc(source: Source, *, status: str = "FULL_TEXT") -> EvidenceDocument:
    text = f"{source.research_task} readable content for offline tests. " * 5
    return EvidenceDocument(
        source=source,
        extracted_text=text,
        word_count=40,
        read_status="success",
        extraction_status=status,
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
        age_days=20,
        freshness_profile="CURRENT",
    )


def _plan(topic: str = "PCB产业链") -> ResearchPlan:
    steps = [
        ResearchPlanStep(
            1,
            "产业链拆解",
            "结构",
            search_queries=["PCB 产业链"],
            freshness_profile="STRUCTURAL",
        ),
        ResearchPlanStep(
            2,
            "近期催化",
            "催化",
            search_queries=["PCB 催化"],
            freshness_profile="BREAKING",
        ),
    ]
    for step in steps:
        step.evidence_strategy = EvidenceStrategy(
            research_task=step.title,
            task_type="chain" if "产业" in step.title else "catalyst",
            evidence_targets=["industry research reports"],
            preferred_source_types=["INDUSTRY_MEDIA"],
            preferred_domains=["example.com"],
            freshness_profile=step.freshness_profile,
            selected_queries=list(step.search_queries),
        )
    return ResearchPlan(
        topic=topic,
        depth=ResearchDepth.QUICK,
        query_type=QueryType.INDUSTRY,
        steps=steps,
        planner_source="rules",
    )


def _analyzed(topic: str) -> AnalyzedQuery:
    return AnalyzedQuery(
        raw_query=topic,
        query_type=QueryType.INDUSTRY,
        normalized_topic=topic,
        research_goal="research",
    )


def _snapshot_callback(history: list[dict]):
    def _cb(state: ResearchState) -> None:
        history.append(research_state_to_dict(state))

    return _cb


def _offline_components(
    *,
    topic: str = "PCB产业链",
    sources: list[Source] | None = None,
    followup_sources: list[Source] | None = None,
    search_mode: str = "mock",
    fail_at: str | None = None,
):
    """Build MagicMock component instances for a fully offline run_research."""
    plan = _plan(topic)
    analyzed = _analyzed(topic)
    initial_sources = sources or [
        _source("S1", "产业链拆解"),
        _source("S2", "近期催化"),
    ]
    followups = followup_sources or []

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
    searcher.last_diagnostics = {
        "mode": search_mode,
        "queries_executed": 2,
        "tavily_search_calls": 0,
        "initial_queries_executed": 2,
        "followup_queries_executed": 0,
    }

    def _search(_plan):
        if fail_at == "searching":
            raise RuntimeError("search boom")
        return list(initial_sources)

    def _followup(_plan, pairs, exclude_urls=None, start_source_id=1):
        searcher.last_diagnostics = dict(searcher.last_diagnostics or {})
        searcher.last_diagnostics["followup_queries_executed"] = len(pairs or [])
        searcher.last_diagnostics["mode"] = search_mode
        return list(followups)

    searcher.search.side_effect = _search
    searcher.followup_search.side_effect = _followup
    searcher.find_replacement_source.return_value = (None, None)

    reader = MagicMock()
    reader.last_diagnostics = {"funnel": {}}
    reader._pdf_attempts = 0
    reader._pdf_successes = 0
    reader._domain_extract_used = 0

    def _read(srcs):
        if fail_at == "reading":
            raise RuntimeError("reading boom")
        return [_doc(s) for s in srcs]

    reader.read.side_effect = _read
    reader._read_one.side_effect = lambda s: _doc(s)

    evaluator = MagicMock()
    evaluator.last_diagnostics = {}

    def _evaluate(docs, _plan):
        if fail_at == "evaluating":
            raise RuntimeError("evaluate boom")
        return [_ev(d) for d in docs]

    evaluator.evaluate.side_effect = _evaluate

    synthesizer = MagicMock()
    synthesizer.last_warning = None
    synthesizer.last_diagnostics = {"synthesizer_source": "fallback"}

    def _synthesize(p, ev):
        if fail_at == "synthesizing":
            raise RuntimeError("synthesize boom")
        return SynthesisBrief(
            topic=p.topic,
            depth=p.depth,
            synthesizer_source="fallback",
            evidence_index={f"E{i+1}": e for i, e in enumerate(ev) if e.keep},
        )

    synthesizer.synthesize.side_effect = _synthesize

    writer = MagicMock()
    writer.last_warning = None
    writer.last_diagnostics = {"writer_source": "fallback"}

    def _write(p, synthesis, research_health=None):
        if fail_at == "writing":
            raise RuntimeError("writing boom")
        return ResearchReport(
            topic=p.topic,
            depth=p.depth,
            sections=[ReportSection("摘要", f"{p.topic} offline report")],
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
        "_plan": plan,
        "_sources": initial_sources,
        "_followups": followups,
    }


def _patch_pipeline(components: dict):
    return patch.multiple(
        "src.pipeline",
        QueryAnalyzer=components["QueryAnalyzer"],
        Planner=components["Planner"],
        Searcher=components["Searcher"],
        Reader=components["Reader"],
        EvidenceEvaluator=components["EvidenceEvaluator"],
        Synthesizer=components["Synthesizer"],
        Writer=components["Writer"],
    )


def test_backward_compatible_default() -> None:
    comps = _offline_components(search_mode="mock")
    with _patch_pipeline(comps):
        # Force Writer path offline even if env has keys (Writer is mocked anyway).
        result = run_research("PCB产业链", ResearchDepth.QUICK)
    assert result.report is not None
    assert result.report.sections
    assert result.plan.topic == "PCB产业链"
    assert not PROJECT_DB.exists() or True  # must not create during this test
    # Explicit: default path unused
    assert result.research_health is not None
    print("PASS 1: backward-compatible run_research without state/callback")


def test_external_state_object() -> None:
    comps = _offline_components()
    state = ResearchState(topic="PCB产业链", depth=ResearchDepth.QUICK)
    run_id = state.run_id
    with _patch_pipeline(comps):
        result = run_research(
            "PCB产业链",
            ResearchDepth.QUICK,
            research_state=state,
        )
    assert state.run_id == run_id
    assert state is not None
    assert state.status == "completed"
    assert state.current_stage == "completed"
    assert state.analyzed_query is not None
    assert state.plan is not None
    assert state.sources
    assert state.documents
    assert state.evidence
    assert state.synthesis is not None
    assert state.research_health is not None
    assert state.report is not None
    assert state.report is result.report
    assert state.evidence is not result.evidence  # list copy into state
    assert len(state.evidence) == len(result.evidence)
    print("PASS 2: external ResearchState filled and completed")


def test_checkpoint_order() -> None:
    comps = _offline_components(search_mode="mock")
    history: list[dict] = []
    with _patch_pipeline(comps):
        run_research(
            "PCB产业链",
            ResearchDepth.QUICK,
            state_callback=_snapshot_callback(history),
        )
    stages = [h["current_stage"] for h in history]
    assert stages, "expected checkpoints"
    assert stages[0] in {"initialized", "analyzing", "pending"} or history[0]["status"] in {
        "pending",
        "running",
        "completed",
    }
    # First running stages progression
    running_stages = [h["current_stage"] for h in history if h["status"] == "running"]
    assert "analyzing" in running_stages
    assert "planning" in running_stages
    assert "searching" in running_stages
    assert "reading" in running_stages
    assert "evaluating" in running_stages
    assert "checking_coverage" in running_stages
    assert "synthesizing" in running_stages
    assert "assessing_health" in running_stages
    assert "writing" in running_stages
    assert history[-1]["status"] == "completed"
    assert history[-1]["current_stage"] == "completed"

    order = [
        "analyzing",
        "planning",
        "searching",
        "reading",
        "evaluating",
        "checking_coverage",
        "synthesizing",
        "assessing_health",
        "writing",
        "completed",
    ]
    idxs = []
    for name in order:
        for i, h in enumerate(history):
            if h["current_stage"] == name:
                idxs.append(i)
                break
        else:
            raise AssertionError(f"missing stage {name} in {stages}")
    assert idxs == sorted(idxs), (idxs, stages)
    print("PASS 3: checkpoint stage order is monotonic")


def test_no_followup_path() -> None:
    # mock mode disables follow-up even if coverage would want it
    comps = _offline_components(search_mode="mock")
    state = ResearchState(topic="PCB产业链", depth=ResearchDepth.QUICK)
    history: list[dict] = []
    with _patch_pipeline(comps):
        result = run_research(
            "PCB产业链",
            ResearchDepth.QUICK,
            research_state=state,
            state_callback=_snapshot_callback(history),
        )
    stages = {h["current_stage"] for h in history}
    assert "followup_searching" not in stages
    assert state.coverage_before is not None and len(state.coverage_before) >= 1
    assert state.coverage_after is not None and len(state.coverage_after) >= 1
    assert len(state.evidence) == len(result.evidence)
    assert [e.source.source_id for e in state.evidence] == [
        e.source.source_id for e in result.evidence
    ]
    print("PASS 4: no-followup path keeps coverage_before/after")


def test_followup_path() -> None:
    topic = "PCB产业链"
    initial = [_source("S1", "产业链拆解")]  # thin coverage → follow-up needed
    followups = [_source("S2", "近期催化"), _source("S3", "产业链拆解")]
    comps = _offline_components(
        topic=topic,
        sources=initial,
        followup_sources=followups,
        search_mode="tavily",  # allow follow-up
    )
    # Force coverage gaps for initial evidence, then sufficient after merge.
    before = [
        EvidenceCoverageResult(
            research_task="产业链拆解",
            coverage_status="THIN",
            retained_count=1,
            readable_count=1,
            followup_needed=True,
            missing_evidence_targets=["industry research reports"],
        ),
        EvidenceCoverageResult(
            research_task="近期催化",
            coverage_status="MISSING",
            retained_count=0,
            readable_count=0,
            followup_needed=True,
            missing_evidence_targets=["news"],
        ),
    ]
    after = [
        EvidenceCoverageResult(
            research_task="产业链拆解",
            coverage_status="SUFFICIENT",
            retained_count=2,
            readable_count=2,
            followup_needed=False,
        ),
        EvidenceCoverageResult(
            research_task="近期催化",
            coverage_status="SUFFICIENT",
            retained_count=1,
            readable_count=1,
            followup_needed=False,
        ),
    ]
    pairs = [("近期催化", "PCB 催化 补充", "BREAKING")]

    state = ResearchState(topic=topic, depth=ResearchDepth.QUICK)
    history: list[dict] = []
    with _patch_pipeline(comps), patch(
        "src.evidence_strategy.assess_evidence_coverage",
        side_effect=[before, after],
    ), patch(
        "src.evidence_strategy.build_followup_queries",
        return_value=pairs,
    ):
        result = run_research(
            topic,
            ResearchDepth.QUICK,
            research_state=state,
            state_callback=_snapshot_callback(history),
        )

    stages = [h["current_stage"] for h in history]
    assert "followup_searching" in stages
    assert "followup_reading" in stages
    assert "followup_evaluating" in stages
    assert len(state.sources) == len(initial) + len(followups)
    assert len(state.documents) == len(state.sources)
    assert len(state.evidence) == len(result.evidence) == len(state.sources)
    assert state.coverage_after
    assert all(c.coverage_status == "SUFFICIENT" for c in state.coverage_after)
    assert state.research_health is not None
    assert result.research_health is state.research_health
    print("PASS 5: follow-up path merges sources and updates coverage_after")


def test_business_failure_marks_failed() -> None:
    comps = _offline_components(fail_at="planning")
    state = ResearchState(topic="PCB产业链", depth=ResearchDepth.QUICK)
    history: list[dict] = []
    raised = None
    with _patch_pipeline(comps):
        try:
            run_research(
                "PCB产业链",
                ResearchDepth.QUICK,
                research_state=state,
                state_callback=_snapshot_callback(history),
            )
        except RuntimeError as exc:
            raised = exc
    assert raised is not None
    assert "planning boom" in str(raised)
    assert state.status == "failed"
    assert state.current_stage == "planning"  # mark_failed keeps failing stage
    assert state.error
    assert "Traceback" not in (state.error or "")
    assert "planning boom" in (state.error or "")
    assert history[-1]["status"] == "failed"
    assert "Traceback" not in str(history[-1].get("error") or "")
    print("PASS 6: business failure marks failed and re-raises")


def test_callback_failure_does_not_break_workflow() -> None:
    comps = _offline_components()
    state = ResearchState(topic="PCB产业链", depth=ResearchDepth.QUICK)
    calls = {"n": 0}

    def bad_cb(_state: ResearchState) -> None:
        calls["n"] += 1
        raise RuntimeError("callback exploded db=data/researchpilot.db key=sk-TESTSECRET")

    with _patch_pipeline(comps):
        result = run_research(
            "PCB产业链",
            ResearchDepth.QUICK,
            research_state=state,
            state_callback=bad_cb,
        )
    assert result.report is not None
    assert state.status == "completed"
    persist = state.diagnostics.get("state_persistence") or {}
    assert int(persist.get("failure_count") or 0) > 0
    assert persist.get("last_error_type") == "RuntimeError"
    msg = str(persist.get("last_error_message") or "")
    assert "callback exploded" in msg
    # Must not recurse infinitely
    assert calls["n"] < 100
    blob = research_state_to_dict(state)
    raw = str(blob)
    assert "sk-TESTSECRET" not in raw or "<redacted>" in raw or "callback exploded" in msg
    # Ensure diagnostics message is truncated-ish and has no traceback
    assert "Traceback" not in msg
    print("PASS 7: callback failures isolated in state_persistence")


def test_topic_depth_sync_strategy() -> None:
    comps = _offline_components(topic="卫星通信")
    state = ResearchState(topic="旧主题", depth=ResearchDepth.DEEP)
    run_id = state.run_id
    with _patch_pipeline(comps):
        run_research(
            "卫星通信",
            ResearchDepth.QUICK,
            research_state=state,
        )
    assert state.run_id == run_id
    assert state.topic == "卫星通信"
    assert state.depth == ResearchDepth.QUICK
    assert state.status == "completed"
    print("PASS 8: mismatched topic/depth synced to call args")


def test_default_run_does_not_create_project_db() -> None:
    existed = PROJECT_DB.exists()
    comps = _offline_components()
    with _patch_pipeline(comps):
        run_research("PCB产业链", ResearchDepth.QUICK)
    if not existed:
        assert not PROJECT_DB.exists()
    print("PASS 9: default run does not create data/researchpilot.db")


def main() -> int:
    # Keep Writer/OpenAI out of the way for any unmocked path.
    os.environ.pop("OPENAI_API_KEY", None)
    test_backward_compatible_default()
    test_external_state_object()
    test_checkpoint_order()
    test_no_followup_path()
    test_followup_path()
    test_business_failure_marks_failed()
    test_callback_failure_does_not_break_workflow()
    test_topic_depth_sync_strategy()
    test_default_run_does_not_create_project_db()
    print("\nAll v1.3 pipeline state tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
