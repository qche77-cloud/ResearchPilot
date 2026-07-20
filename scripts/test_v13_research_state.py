"""Offline v1.3 ResearchState unit tests (no network, no .env).

Run:
  D:\\python3.11\\python.exe scripts/test_v13_research_state.py
"""

from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.evidence_strategy import EvidenceCoverageResult, EvidenceStrategy, attach_evidence_strategies
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
from src.research_state import (
    ResearchState,
    research_state_from_dict,
    research_state_to_dict,
    research_state_to_json,
)


def test_default_run_ids_unique() -> None:
    a = ResearchState(topic="A")
    b = ResearchState(topic="B")
    assert a.run_id and b.run_id
    assert a.run_id != b.run_id
    print("PASS 1: default run_id non-empty and unique")


def test_default_status_and_stage() -> None:
    state = ResearchState(topic="x")
    assert state.status == "pending"
    assert state.current_stage == "initialized"
    print("PASS 2: default status/current_stage")


def test_mark_running() -> None:
    state = ResearchState(topic="x")
    before = state.updated_at
    time.sleep(0.01)
    state.mark_running("search")
    assert state.status == "running"
    assert state.current_stage == "search"
    assert state.updated_at >= before
    print("PASS 3: mark_running updates status/stage")


def test_mark_completed() -> None:
    state = ResearchState(topic="x")
    state.mark_running("write")
    state.mark_completed()
    assert state.status == "completed"
    assert state.current_stage == "completed"
    assert state.error is None
    print("PASS 4: mark_completed sets completed")


def test_mark_failed() -> None:
    state = ResearchState(topic="x")
    state.mark_running("evaluate")
    state.mark_failed("reader timeout", stage="read")
    assert state.status == "failed"
    assert state.current_stage == "read"
    assert state.error == "reader timeout"
    assert "Traceback" not in (state.error or "")
    print("PASS 5: mark_failed stores short error")


def test_updated_at_monotonic() -> None:
    state = ResearchState(topic="x")
    t0 = state.updated_at
    time.sleep(0.01)
    state.touch()
    assert state.updated_at >= t0
    t1 = state.updated_at
    time.sleep(0.01)
    state.mark_running("plan")
    assert state.updated_at >= t1
    print("PASS 6: updated_at does not go backwards")


def test_list_dict_defaults_not_shared() -> None:
    a = ResearchState(topic="a")
    b = ResearchState(topic="b")
    a.sources.append(
        Source("t", "https://example.com", "s", "web", 0.5)
    )
    a.diagnostics["k"] = "v"
    assert b.sources == []
    assert b.diagnostics == {}
    print("PASS 7: list/dict defaults not shared across instances")


def _minimal_nested_state() -> ResearchState:
    source = Source(
        title="PCB 产业报告",
        url="https://example.com/pcb",
        snippet="产业链",
        source_type="web",
        relevance=0.9,
        research_task="产业链拆解",
        source_id="S1",
    )
    doc = EvidenceDocument(
        source=source,
        extracted_text="PCB产业链包括上游材料与下游应用。",
        word_count=10,
        read_status="success",
        extraction_status="FULL_TEXT",
    )
    ev = EvaluatedEvidence(
        document=doc,
        credibility_score=80,
        relevance_score=80,
        recency_score=70,
        final_score=80,
        evaluation_reason="ok",
        keep=True,
    )
    plan = ResearchPlan(
        topic="PCB产业链",
        depth=ResearchDepth.STANDARD,
        query_type=QueryType.INDUSTRY,
        steps=[ResearchPlanStep(1, "产业链拆解", "结构")],
    )
    analyzed = AnalyzedQuery(
        raw_query="PCB产业链",
        query_type=QueryType.INDUSTRY,
        normalized_topic="PCB产业链",
        research_goal="拆解",
    )
    synthesis = SynthesisBrief(topic="PCB产业链", depth=ResearchDepth.STANDARD)
    health = ResearchHealth(overall_score=80.0, coverage_score=90.0)
    report = ResearchReport(
        topic="PCB产业链",
        depth=ResearchDepth.STANDARD,
        sections=[ReportSection("摘要", "PCB产业链概述")],
    )
    coverage = [
        EvidenceCoverageResult(
            research_task="产业链拆解",
            coverage_status="SUFFICIENT",
            retained_count=1,
            readable_count=1,
        )
    ]
    state = ResearchState(
        topic="PCB产业链",
        depth=ResearchDepth.STANDARD,
        analyzed_query=analyzed,
        plan=plan,
        sources=[source],
        documents=[doc],
        evidence=[ev],
        coverage_before=coverage,
        coverage_after=list(coverage),
        synthesis=synthesis,
        research_health=health,
        report=report,
        diagnostics={"note": "中文诊断"},
    )
    return state


def test_to_dict_with_nested() -> None:
    state = _minimal_nested_state()
    data = research_state_to_dict(state)
    assert isinstance(data, dict)
    assert data["topic"] == "PCB产业链"
    assert data["depth"] == ResearchDepth.STANDARD.value
    assert isinstance(data["plan"], dict)
    assert data["plan"]["query_type"] == QueryType.INDUSTRY.value
    assert isinstance(data["sources"], list) and data["sources"][0]["title"]
    print("PASS 8: research_state_to_dict with nested dataclasses")


def test_to_json_roundtrip_loads() -> None:
    state = _minimal_nested_state()
    raw = research_state_to_json(state)
    loaded = json.loads(raw)
    assert loaded["topic"] == "PCB产业链"
    assert loaded["status"] == "pending"
    print("PASS 9: research_state_to_json loads via json.loads")


def test_enum_and_nested_dataclass() -> None:
    state = _minimal_nested_state()
    data = research_state_to_dict(state)
    assert data["depth"] == "Standard"
    assert data["analyzed_query"]["query_type"] == "industry"
    assert data["coverage_after"][0]["coverage_status"] == "SUFFICIENT"
    print("PASS 10: Enum and nested dataclass conversion")


def test_chinese_not_ascii_escaped() -> None:
    state = _minimal_nested_state()
    raw = research_state_to_json(state)
    assert "PCB产业链" in raw
    assert "\\u" not in raw or "产业链" in raw  # Chinese present unescaped
    assert "产业链" in raw
    print("PASS 11: Chinese topic preserved without ASCII escape")


def test_serialize_does_not_mutate() -> None:
    state = _minimal_nested_state()
    snap = copy.deepcopy(state)
    _ = research_state_to_dict(state)
    _ = research_state_to_json(state)
    assert state.topic == snap.topic
    assert state.status == snap.status
    assert len(state.sources) == len(snap.sources)
    assert state.diagnostics == snap.diagnostics
    assert state.plan is not None and snap.plan is not None
    assert state.plan.topic == snap.plan.topic
    print("PASS 12: serialization does not mutate ResearchState")


def test_no_secrets_in_serialization() -> None:
    state = ResearchState(topic="安全测试")
    state.diagnostics = {
        "OPENAI_API_KEY": "should-not-appear-as-value",
        "TAVILY_API_KEY": "should-not-appear-as-value",
        "note": "ok",
        ".env": "fake",
    }
    raw = research_state_to_json(state)
    data = json.loads(raw)
    assert "should-not-appear-as-value" not in raw
    assert data["diagnostics"]["OPENAI_API_KEY"] == "<redacted>"
    assert data["diagnostics"]["TAVILY_API_KEY"] == "<redacted>"
    assert data["diagnostics"][".env"] == "<redacted>"
    assert "OPENAI_API_KEY=" not in raw
    assert "TAVILY_API_KEY=" not in raw
    # from_dict shell restore still works
    shell = research_state_from_dict(data)
    assert shell.topic == "安全测试"
    print("PASS 13: secrets redacted from serialization")


def _plan_with_real_evidence_strategy() -> ResearchPlan:
    """Build a production-shaped plan via ``attach_evidence_strategies``."""
    analyzed = AnalyzedQuery(
        raw_query="PCB产业链",
        query_type=QueryType.INDUSTRY,
        normalized_topic="PCB产业链",
        research_goal="拆解产业链",
    )
    plan = ResearchPlan(
        topic="PCB产业链",
        depth=ResearchDepth.STANDARD,
        query_type=QueryType.INDUSTRY,
        steps=[
            ResearchPlanStep(
                1,
                "产业链拆解",
                "结构",
                search_queries=["PCB 产业链", "PCB 上中下游", "PCB 格局"],
            ),
            ResearchPlanStep(
                2,
                "近期催化",
                "催化",
                search_queries=["PCB 催化", "PCB 政策"],
            ),
        ],
        analyzed_query=analyzed,
    )
    return attach_evidence_strategies(plan, analyzed)


def test_real_evidence_strategy_serializes_as_dict() -> None:
    plan = _plan_with_real_evidence_strategy()
    assert isinstance(plan.steps[0].evidence_strategy, EvidenceStrategy)
    state = ResearchState(
        topic=plan.topic,
        depth=plan.depth,
        plan=plan,
        analyzed_query=plan.analyzed_query,
    )
    before_strategy = copy.deepcopy(plan.steps[0].evidence_strategy)
    snapshot = research_state_to_dict(state)
    assert isinstance(snapshot["plan"], dict)
    assert isinstance(snapshot["plan"]["steps"], list)
    step0 = snapshot["plan"]["steps"][0]
    assert isinstance(step0, dict)
    strat = step0["evidence_strategy"]
    assert isinstance(strat, dict), strat
    assert not (isinstance(strat, str) and strat.startswith("<"))
    # Real business fields from EvidenceStrategy dataclass
    assert "research_task" in strat and strat["research_task"]
    assert "task_type" in strat and strat["task_type"]
    assert "evidence_targets" in strat
    assert "preferred_source_types" in strat
    assert "freshness_profile" in strat
    assert snapshot["plan"]["depth"] == ResearchDepth.STANDARD.value
    assert snapshot["plan"]["query_type"] == QueryType.INDUSTRY.value
    # Original strategy unchanged
    assert plan.steps[0].evidence_strategy.research_task == before_strategy.research_task
    assert plan.steps[0].evidence_strategy.task_type == before_strategy.task_type
    assert plan.steps[0].evidence_strategy.evidence_targets == before_strategy.evidence_targets
    print("PASS 14: real EvidenceStrategy snapshot is dict with business fields")


def test_project_internal_plain_object_fields() -> None:
    class Probe:
        def __init__(self) -> None:
            self.public_field = "keep-me"
            self.task_type = "chain"
            self._private = "hidden"
            self.fn = lambda: 99
            self.OPENAI_API_KEY = "secret-value"

    Probe.__module__ = "src._serialize_probe"
    probe = Probe()

    class Foreign:
        def __init__(self) -> None:
            self.leak = "nope"

    Foreign.__module__ = "requests.sessions"
    foreign = Foreign()

    state = ResearchState(topic="probe")
    state.diagnostics["probe"] = probe
    state.diagnostics["foreign"] = foreign
    snap = copy.deepcopy(
        {
            "public_field": probe.public_field,
            "task_type": probe.task_type,
            "_private": probe._private,
        }
    )
    data = research_state_to_dict(state)
    probe_out = data["diagnostics"]["probe"]
    assert isinstance(probe_out, dict)
    assert probe_out["public_field"] == "keep-me"
    assert probe_out["task_type"] == "chain"
    assert "_private" not in probe_out
    assert "fn" not in probe_out
    assert probe_out["OPENAI_API_KEY"] == "<redacted>"
    foreign_out = data["diagnostics"]["foreign"]
    assert isinstance(foreign_out, str)
    assert foreign_out.startswith("<")
    assert "requests.sessions" in foreign_out
    assert "nope" not in json.dumps(data, ensure_ascii=False)
    assert probe.public_field == snap["public_field"]
    assert probe._private == snap["_private"]
    print("PASS 15: project-internal plain fields; private/callable skipped; foreign placeholder")


def test_circular_reference_safe() -> None:
    class Node:
        def __init__(self, name: str) -> None:
            self.name = name
            self.other: Node | None = None

    Node.__module__ = "src._serialize_probe"
    a = Node("a")
    b = Node("b")
    a.other = b
    b.other = a
    state = ResearchState(topic="cycle")
    state.diagnostics["node"] = a
    raw = research_state_to_json(state)
    data = json.loads(raw)
    node = data["diagnostics"]["node"]
    assert isinstance(node, dict)
    assert node["name"] == "a"
    assert isinstance(node["other"], dict)
    assert node["other"]["name"] == "b"
    assert node["other"]["other"] == "<circular-reference>"
    assert "0x" not in raw.lower()
    assert "RecursionError" not in raw
    print("PASS 16: circular reference yields <circular-reference>, no 0x address")


def test_no_memory_address_in_output() -> None:
    state = _minimal_nested_state()
    state.plan = _plan_with_real_evidence_strategy()
    raw = research_state_to_json(state)
    assert "0x" not in raw.lower()
    print("PASS 17: serialized output has no 0x memory addresses")


def main() -> int:
    test_default_run_ids_unique()
    test_default_status_and_stage()
    test_mark_running()
    test_mark_completed()
    test_mark_failed()
    test_updated_at_monotonic()
    test_list_dict_defaults_not_shared()
    test_to_dict_with_nested()
    test_to_json_roundtrip_loads()
    test_enum_and_nested_dataclass()
    test_chinese_not_ascii_escaped()
    test_serialize_does_not_mutate()
    test_no_secrets_in_serialization()
    test_real_evidence_strategy_serializes_as_dict()
    test_project_internal_plain_object_fields()
    test_circular_reference_safe()
    test_no_memory_address_in_output()
    print("\nAll v1.3 ResearchState tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
