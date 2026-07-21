"""Offline v1.3 History Query API tests (temp DB only).

Run:
  D:\\python3.11\\python.exe scripts/test_v13_history_queries.py
"""

from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.evidence_strategy import EvidenceCoverageResult
from src.models import (
    EvidenceDocument,
    EvaluatedEvidence,
    ReportSection,
    ResearchDepth,
    ResearchHealth,
    ResearchReport,
    Source,
    SynthesisBrief,
)
from src.research_state import ResearchState
from src.storage import MAX_HISTORY_LIMIT, ResearchRunRepository, ResearchRunSummary

PROJECT_DB = _ROOT / "data" / "researchpilot.db"


def _repo(tmp: Path, name: str = "history.db") -> ResearchRunRepository:
    repo = ResearchRunRepository(tmp / name)
    repo.initialize()
    return repo


def _state(
    *,
    topic: str,
    run_id: str,
    status: str = "pending",
    stage: str = "initialized",
    created_at: str = "2026-01-01T00:00:00Z",
    updated_at: str = "2026-01-01T00:00:00Z",
    depth: ResearchDepth = ResearchDepth.QUICK,
    error: str | None = None,
) -> ResearchState:
    return ResearchState(
        topic=topic,
        depth=depth,
        run_id=run_id,
        status=status,
        current_stage=stage,
        created_at=created_at,
        updated_at=updated_at,
        error=error,
    )


def test_1_empty_database(tmp: Path) -> None:
    repo = _repo(tmp, "empty.db")
    assert repo.list_runs() == []
    assert repo.count_runs() == 0
    assert repo.get_state("missing") is None
    print("PASS 1: empty database")


def test_2_default_sort(tmp: Path) -> None:
    repo = _repo(tmp, "sort.db")
    # Insert order intentionally scrambled relative to expected sort.
    specs = [
        ("r-c", "2026-01-01T00:00:00Z", "2026-06-01T12:00:00Z", "c"),
        ("r-a", "2026-01-01T00:00:00Z", "2026-06-01T12:00:00Z", "a"),
        ("r-e", "2026-03-01T00:00:00Z", "2026-05-01T00:00:00Z", "e"),
        ("r-d", "2026-02-01T00:00:00Z", "2026-07-01T00:00:00Z", "d"),
        ("r-b", "2026-04-01T00:00:00Z", "2026-06-01T12:00:00Z", "b"),
    ]
    for run_id, created, updated, topic in specs:
        repo.save_state(
            _state(
                topic=topic,
                run_id=run_id,
                created_at=created,
                updated_at=updated,
                status="completed",
                stage="completed",
            )
        )
    rows = repo.list_runs(limit=20)
    # updated_at DESC, then created_at DESC, then run_id DESC
    assert [r.run_id for r in rows] == ["r-d", "r-b", "r-c", "r-a", "r-e"]
    print("PASS 2: default sort updated_at/created_at/run_id DESC")


def test_3_limit_offset_pagination(tmp: Path) -> None:
    repo = _repo(tmp, "page.db")
    for i in range(8):
        rid = f"run-{i:02d}"
        repo.save_state(
            _state(
                topic=f"t{i}",
                run_id=rid,
                created_at=f"2026-01-{i + 1:02d}T00:00:00Z",
                updated_at=f"2026-02-{i + 1:02d}T00:00:00Z",
                status="completed",
                stage="completed",
            )
        )
    expected = [f"run-{i:02d}" for i in range(7, -1, -1)]
    page1 = repo.list_runs(limit=3, offset=0)
    page2 = repo.list_runs(limit=3, offset=3)
    assert [r.run_id for r in page1] == expected[:3]
    assert [r.run_id for r in page2] == expected[3:6]
    assert {r.run_id for r in page1}.isdisjoint({r.run_id for r in page2})
    merged = page1 + page2 + repo.list_runs(limit=3, offset=6)
    assert [r.run_id for r in merged] == expected
    assert repo.list_runs(limit=3, offset=100) == []
    assert repo.count_runs() == 8
    print("PASS 3: limit/offset pagination")


def test_4_pagination_validation(tmp: Path) -> None:
    repo = _repo(tmp, "val.db")
    value_error_cases = [
        {"limit": 0},
        {"limit": -1},
        {"limit": MAX_HISTORY_LIMIT + 1},
        {"offset": -1},
    ]
    type_error_cases = [
        {"limit": "20"},
        {"offset": "0"},
        {"limit": True},
        {"offset": False},
        {"limit": None},
        {"offset": None},
    ]
    for kwargs in value_error_cases:
        try:
            repo.list_runs(**kwargs)  # type: ignore[arg-type]
            raise AssertionError(f"expected ValueError for {kwargs}")
        except ValueError:
            pass
    for kwargs in type_error_cases:
        try:
            repo.list_runs(**kwargs)  # type: ignore[arg-type]
            raise AssertionError(f"expected TypeError for {kwargs}")
        except TypeError:
            pass
    print("PASS 4: pagination validation")


def test_5_status_filter(tmp: Path) -> None:
    repo = _repo(tmp, "status.db")
    specs = [
        ("s1", "completed", "completed"),
        ("s2", "failed", "reading"),
        ("s3", "running", "searching"),
        ("s4", "completed", "completed"),
    ]
    for i, (rid, status, stage) in enumerate(specs):
        repo.save_state(
            _state(
                topic=f"topic-{rid}",
                run_id=rid,
                status=status,
                stage=stage,
                updated_at=f"2026-03-{i + 1:02d}T00:00:00Z",
                error=("boom" if status == "failed" else None),
            )
        )
    completed = repo.list_runs(status="completed")
    assert len(completed) == 2
    assert {r.run_id for r in completed} == {"s1", "s4"}
    assert len(repo.list_runs(status="failed")) == 1
    assert repo.list_runs(status="unknown") == []
    assert len(repo.list_runs(status=None)) == 4
    assert len(repo.list_runs(status="")) == 4
    assert len(repo.list_runs(status="   ")) == 4
    assert len(repo.list_runs(status=" completed ")) == 2
    assert repo.count_runs(status="completed") == 2
    assert repo.count_runs(status="failed") == 1
    assert repo.count_runs(status="unknown") == 0
    assert repo.count_runs() == 4
    print("PASS 5: status filter")


def test_6_topic_fuzzy_search(tmp: Path) -> None:
    repo = _repo(tmp, "topic.db")
    topics = [
        ("t1", "PCB产业链研究"),
        ("t2", "A股液冷产业链"),
        ("t3", "pcb company analysis"),
        ("t4", "黄金价格周期"),
        ("t5", "AI服务器PCB机会"),
    ]
    for i, (rid, topic) in enumerate(topics):
        repo.save_state(
            _state(
                topic=topic,
                run_id=rid,
                updated_at=f"2026-04-{i + 1:02d}T00:00:00Z",
                status="completed",
                stage="completed",
            )
        )
    pcb = repo.list_runs(topic_query="PCB")
    assert {r.run_id for r in pcb} == {"t1", "t3", "t5"}
    assert {r.run_id for r in repo.list_runs(topic_query="pcb")} == {"t1", "t3", "t5"}
    assert {r.run_id for r in repo.list_runs(topic_query="产业链")} == {"t1", "t2"}
    gold = repo.list_runs(topic_query="黄金")
    assert [r.run_id for r in gold] == ["t4"]
    assert {r.run_id for r in repo.list_runs(topic_query="  PCB  ")} == {"t1", "t3", "t5"}
    assert len(repo.list_runs(topic_query="")) == 5
    assert len(repo.list_runs(topic_query="   ")) == 5
    assert repo.count_runs(topic_query="PCB") == 3
    print("PASS 6: topic fuzzy search")


def test_7_like_special_chars(tmp: Path) -> None:
    repo = _repo(tmp, "like.db")
    topics = [
        ("l1", "利润率100%测试"),
        ("l2", "code_name_test"),
        ("l3", r"Windows\Path Research"),
        ("l4", "普通研究"),
        ("l5", "100 percent"),
    ]
    for i, (rid, topic) in enumerate(topics):
        repo.save_state(
            _state(
                topic=topic,
                run_id=rid,
                updated_at=f"2026-05-{i + 1:02d}T00:00:00Z",
                status="completed",
                stage="completed",
            )
        )
    pct = repo.list_runs(topic_query="%")
    assert [r.run_id for r in pct] == ["l1"]
    assert repo.count_runs(topic_query="%") == 1
    under = repo.list_runs(topic_query="_")
    assert [r.run_id for r in under] == ["l2"]
    assert repo.count_runs(topic_query="_") == 1
    slash = repo.list_runs(topic_query="\\")
    assert [r.run_id for r in slash] == ["l3"]
    assert repo.count_runs(topic_query="\\") == 1
    print("PASS 7: LIKE special character escaping")


def test_8_combined_filters(tmp: Path) -> None:
    repo = _repo(tmp, "combo.db")
    specs = [
        ("c1", "PCB完成", "completed", "2026-06-05T00:00:00Z"),
        ("c2", "PCB失败", "failed", "2026-06-04T00:00:00Z"),
        ("c3", "液冷产业链完成", "completed", "2026-06-03T00:00:00Z"),
        ("c4", "PCB完成2", "completed", "2026-06-02T00:00:00Z"),
        ("c5", "产业链失败", "failed", "2026-06-01T00:00:00Z"),
        ("c6", "无关", "completed", "2026-05-01T00:00:00Z"),
    ]
    for rid, topic, status, updated in specs:
        repo.save_state(
            _state(
                topic=topic,
                run_id=rid,
                status=status,
                stage=("completed" if status == "completed" else "evaluating"),
                updated_at=updated,
                error=("err" if status == "failed" else None),
            )
        )
    page = repo.list_runs(status="completed", topic_query="PCB", limit=1, offset=0)
    assert [r.run_id for r in page] == ["c1"]
    page2 = repo.list_runs(status="completed", topic_query="PCB", limit=1, offset=1)
    assert [r.run_id for r in page2] == ["c4"]
    assert repo.count_runs(status="completed", topic_query="PCB") == 2
    failed_chain = repo.list_runs(status="failed", topic_query="产业链")
    assert [r.run_id for r in failed_chain] == ["c5"]
    assert repo.count_runs(status="failed", topic_query="产业链") == 1
    print("PASS 8: combined filters + pagination")


def test_9_summary_does_not_load_full_state(tmp: Path) -> None:
    repo = _repo(tmp, "heavy.db")
    source = Source(
        title="Heavy Source",
        url="https://example.com/a",
        snippet="snippet",
        source_type="web",
        relevance=0.9,
    )
    document = EvidenceDocument(
        source=source,
        extracted_text="x" * 5000,
        word_count=5000,
        read_status="success",
    )
    evidence = EvaluatedEvidence(
        document=document,
        credibility_score=80,
        relevance_score=80,
        recency_score=70,
        final_score=78,
        evaluation_reason="ok",
    )
    state = _state(
        topic="heavy-topic",
        run_id="heavy-1",
        status="completed",
        stage="completed",
        updated_at="2026-07-01T00:00:00Z",
    )
    state.documents = [document]
    state.evidence = [evidence]
    state.sources = [source]
    state.coverage_before = [
        EvidenceCoverageResult(
            research_task="chain",
            coverage_status="THIN",
            retained_count=1,
        )
    ]
    state.coverage_after = [
        EvidenceCoverageResult(
            research_task="chain",
            coverage_status="SUFFICIENT",
            retained_count=1,
        )
    ]
    state.synthesis = SynthesisBrief(
        topic="heavy-topic",
        depth=ResearchDepth.QUICK,
        findings={"概览": "大量合成内容" * 50},
        cited_evidence=[evidence],
        evidence_index={"E1": evidence},
    )
    state.research_health = ResearchHealth(
        overall_score=70.0,
        coverage_score=60.0,
        freshness_score=80.0,
        grounding_score=75.0,
        diversity_score=65.0,
        warnings=["w"],
        suggestions=["s"],
        details={"k": "v"},
    )
    state.report = ResearchReport(
        topic="heavy-topic",
        depth=ResearchDepth.QUICK,
        sections=[ReportSection(title="一", content="body " * 300)],
        writer_source="fallback",
    )
    # Keep a large text payload on the report section for round-trip checks.
    state.report.sections[0].content = ("summary " * 200) + state.report.sections[0].content
    state.diagnostics = {"big": {"blob": "y" * 2000}}
    repo.save_state(state)

    rows = repo.list_runs()
    assert len(rows) == 1
    summary = rows[0]
    assert isinstance(summary, ResearchRunSummary)
    summary_names = {f.name for f in fields(ResearchRunSummary)}
    assert summary_names == {
        "run_id",
        "topic",
        "depth",
        "status",
        "current_stage",
        "created_at",
        "updated_at",
        "error_message",
    }
    for banned in (
        "state_json",
        "report",
        "evidence",
        "documents",
        "synthesis",
        "diagnostics",
        "coverage_before",
        "coverage_after",
    ):
        assert banned not in summary_names
        assert not hasattr(summary, banned)
    assert summary.topic == "heavy-topic"
    assert summary.status == "completed"

    loaded = repo.get_state("heavy-1")
    assert loaded is not None
    assert loaded.report is not None
    assert loaded.report.sections[0].content.startswith("summary ")
    assert loaded.evidence and loaded.evidence[0].final_score == 78
    assert loaded.documents and len(loaded.documents[0].extracted_text) == 5000
    assert loaded.synthesis is not None
    assert loaded.diagnostics["big"]["blob"].startswith("y")
    assert loaded.coverage_after[0].coverage_status == "SUFFICIENT"
    print("PASS 9: summary excludes full state; get_state restores")


def test_10_failed_summary(tmp: Path) -> None:
    repo = _repo(tmp, "failed.db")
    state = _state(
        topic="fail-topic",
        run_id="fail-1",
        status="failed",
        stage="reading",
        updated_at="2026-07-02T00:00:00Z",
        error="reader timeout",
    )
    repo.save_state(state)
    rows = repo.list_runs()
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert rows[0].current_stage == "reading"
    assert rows[0].error_message == "reader timeout"
    loaded = repo.get_state("fail-1")
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.current_stage == "reading"
    assert loaded.error == "reader timeout"
    print("PASS 10: failed summary preserves stage/error")


def test_11_upsert_same_run_id(tmp: Path) -> None:
    repo = _repo(tmp, "upsert.db")
    first = _state(
        topic="upsert-topic",
        run_id="same-id",
        status="running",
        stage="searching",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T01:00:00Z",
    )
    repo.save_state(first)
    second = _state(
        topic="upsert-topic",
        run_id="same-id",
        status="completed",
        stage="completed",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T02:00:00Z",
    )
    second.report = ResearchReport(
        topic="upsert-topic",
        depth=ResearchDepth.QUICK,
        sections=[ReportSection(title="Final", content="done")],
        writer_source="fallback",
    )
    repo.save_state(second)
    assert repo.count_runs() == 1
    rows = repo.list_runs()
    assert len(rows) == 1
    assert rows[0].status == "completed"
    assert rows[0].current_stage == "completed"
    assert rows[0].updated_at == "2026-01-01T02:00:00Z"
    loaded = repo.get_state("same-id")
    assert loaded is not None
    assert loaded.report is not None
    assert loaded.report.sections[0].title == "Final"
    print("PASS 11: upsert keeps single row with latest fields")


def test_12_persisted_service_compat(tmp: Path) -> None:
    # Import and run a minimal offline check against repository exists/save path
    # used by persistence service; full service suites run separately.
    from src.research_service import ResearchPersistenceError

    repo = _repo(tmp, "compat.db")
    state = _state(
        topic="compat",
        run_id="compat-1",
        status="completed",
        stage="completed",
    )
    repo.save_state(state)
    assert repo.exists("compat-1") is True
    assert repo.exists("missing") is False
    assert isinstance(ResearchPersistenceError("x"), Exception)
    # Re-run focused sqlite-style roundtrip via get_run still available.
    row = repo.get_run("compat-1")
    assert row is not None
    assert row["status"] == "completed"
    assert isinstance(row["state_snapshot"], dict)
    print("PASS 12: repository compatibility helpers intact")


def main() -> int:
    with TemporaryDirectory(prefix="rp_v13_history_", ignore_cleanup_errors=True) as td:
        tmp = Path(td)
        assert not str(tmp).startswith(str(PROJECT_DB.parent))
        test_1_empty_database(tmp)
        test_2_default_sort(tmp)
        test_3_limit_offset_pagination(tmp)
        test_4_pagination_validation(tmp)
        test_5_status_filter(tmp)
        test_6_topic_fuzzy_search(tmp)
        test_7_like_special_chars(tmp)
        test_8_combined_filters(tmp)
        test_9_summary_does_not_load_full_state(tmp)
        test_10_failed_summary(tmp)
        test_11_upsert_same_run_id(tmp)
        test_12_persisted_service_compat(tmp)
    print("ALL HISTORY QUERY TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
