"""Offline v1.3 SQLite ResearchRunRepository tests (temp DB only).

Run:
  D:\\python3.11\\python.exe scripts/test_v13_sqlite_storage.py
"""

from __future__ import annotations

import copy
import json
import sqlite3
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.evidence_strategy import EvidenceStrategy, attach_evidence_strategies
from src.models import AnalyzedQuery, QueryType, ResearchDepth, ResearchPlan, ResearchPlanStep
from src.research_state import ResearchState
from src.storage import ResearchRunRepository

PROJECT_DB = _ROOT / "data" / "researchpilot.db"


def _assert_no_project_db_created() -> None:
    # Tests must not create/use the project default DB path.
    assert not str(PROJECT_DB).endswith("TemporaryDirectory")  # sanity
    # If it existed before tests we don't delete it; we just never write to it.
    # Ensure our repository paths stay under tempfile roots (checked per test).


def test_initialize_and_idempotent(tmp: Path) -> None:
    db = tmp / "t.db"
    repo = ResearchRunRepository(db)
    repo.initialize()
    assert db.is_file()
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='research_runs'"
        ).fetchone()
    assert row is not None
    repo.initialize()  # must not raise
    print("PASS 1-2: initialize creates table; repeat is safe")


def test_save_insert_and_upsert(tmp: Path) -> None:
    db = tmp / "upsert.db"
    with ResearchRunRepository(db) as repo:
        state = ResearchState(topic="PCB产业链", depth=ResearchDepth.QUICK)
        run_id = state.run_id
        repo.save_state(state)
        again = ResearchState(
            topic="PCB产业链-更新",
            depth=ResearchDepth.STANDARD,
            run_id=run_id,
            created_at=state.created_at,
        )
        again.mark_running("search")
        repo.save_state(again)
        with sqlite3.connect(str(db)) as conn:
            count = conn.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0]
            topic = conn.execute(
                "SELECT topic FROM research_runs WHERE run_id=?", (run_id,)
            ).fetchone()[0]
        assert count == 1
        assert topic == "PCB产业链-更新"
    print("PASS 3-4: save insert + upsert same run_id")


def test_get_run_snapshot_and_chinese(tmp: Path) -> None:
    db = tmp / "get.db"
    with ResearchRunRepository(db) as repo:
        state = ResearchState(topic="圣泉集团", depth=ResearchDepth.STANDARD)
        state.diagnostics["note"] = "中文内容"
        repo.save_state(state)
        row = repo.get_run(state.run_id)
        assert row is not None
        assert row["topic"] == "圣泉集团"
        assert isinstance(row["state_snapshot"], dict)
        assert row["state_snapshot"]["topic"] == "圣泉集团"
        assert row["state_snapshot"]["diagnostics"]["note"] == "中文内容"
        assert json.loads(row["state_json"])["topic"] == "圣泉集团"
    print("PASS 5-6: get_run snapshot + Chinese topic")


def test_status_transitions_persisted(tmp: Path) -> None:
    db = tmp / "status.db"
    with ResearchRunRepository(db) as repo:
        state = ResearchState(topic="卫星通信", depth=ResearchDepth.QUICK)
        state.mark_running("synthesize")
        repo.save_state(state)
        row = repo.get_run(state.run_id)
        assert row is not None
        assert row["status"] == "running"
        assert row["current_stage"] == "synthesize"

        state.mark_completed()
        repo.save_state(state)
        row = repo.get_run(state.run_id)
        assert row is not None
        assert row["status"] == "completed"

        state.mark_failed("network blip", stage="search")
        repo.save_state(state)
        row = repo.get_run(state.run_id)
        assert row is not None
        assert row["status"] == "failed"
        assert row["error_message"] == "network blip"
        assert row["current_stage"] == "search"
    print("PASS 7-9: running/completed/failed persistence")


def test_list_runs_order_and_limit(tmp: Path) -> None:
    db = tmp / "list.db"
    with ResearchRunRepository(db) as repo:
        s1 = ResearchState(topic="first", depth=ResearchDepth.QUICK)
        s1.updated_at = "2026-01-01T00:00:00Z"
        repo.save_state(s1)
        time.sleep(0.01)
        s2 = ResearchState(topic="second", depth=ResearchDepth.QUICK)
        s2.updated_at = "2026-06-01T00:00:00Z"
        repo.save_state(s2)
        time.sleep(0.01)
        s3 = ResearchState(topic="third", depth=ResearchDepth.QUICK)
        s3.updated_at = "2026-07-01T00:00:00Z"
        repo.save_state(s3)

        rows = repo.list_runs(limit=2)
        assert len(rows) == 2
        assert rows[0]["topic"] == "third"
        assert rows[1]["topic"] == "second"
        assert "state_json" not in rows[0]
        assert "state_snapshot" not in rows[0]
        for key in (
            "run_id",
            "topic",
            "depth",
            "status",
            "current_stage",
            "created_at",
            "updated_at",
            "error_message",
        ):
            assert key in rows[0]

        try:
            repo.list_runs(limit=0)
            raise AssertionError("limit=0 should raise")
        except ValueError:
            pass
        try:
            repo.list_runs(limit=-1)
            raise AssertionError("limit=-1 should raise")
        except ValueError:
            pass
        try:
            repo.list_runs(limit=True)  # type: ignore[arg-type]
            raise AssertionError("limit=True should raise")
        except ValueError:
            pass
    print("PASS 10-11: list_runs order + limit validation")


def test_get_missing_and_delete(tmp: Path) -> None:
    db = tmp / "del.db"
    with ResearchRunRepository(db) as repo:
        assert repo.get_run("does-not-exist") is None
        state = ResearchState(topic="to-delete")
        repo.save_state(state)
        assert repo.delete_run(state.run_id) is True
        assert repo.get_run(state.run_id) is None
        assert repo.delete_run(state.run_id) is False
    print("PASS 12-13: get missing None; delete_run bool")


def test_sql_injection_treated_as_data(tmp: Path) -> None:
    db = tmp / "inj.db"
    evil_topic = "x'; DROP TABLE research_runs;--"
    evil_id = "id'); DELETE FROM research_runs;--"
    with ResearchRunRepository(db) as repo:
        state = ResearchState(topic=evil_topic, run_id=evil_id)
        repo.save_state(state)
        row = repo.get_run(evil_id)
        assert row is not None
        assert row["topic"] == evil_topic
        with sqlite3.connect(str(db)) as conn:
            name = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='research_runs'"
            ).fetchone()
            count = conn.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0]
        assert name is not None
        assert count == 1
    print("PASS 14: SQL injection strings stored as plain data")


def test_save_does_not_mutate_state(tmp: Path) -> None:
    db = tmp / "pure.db"
    with ResearchRunRepository(db) as repo:
        state = ResearchState(topic="不可变", depth=ResearchDepth.DEEP)
        state.diagnostics["a"] = 1
        before = copy.deepcopy(state)
        repo.save_state(state)
        assert state.topic == before.topic
        assert state.status == before.status
        assert state.diagnostics == before.diagnostics
        assert state.run_id == before.run_id
        assert state.updated_at == before.updated_at
    print("PASS 15: save_state does not mutate ResearchState")


def test_db_only_in_temp(tmp: Path) -> None:
    db = tmp / "only_temp.db"
    assert PROJECT_DB.resolve() != db.resolve()
    with ResearchRunRepository(db) as repo:
        repo.save_state(ResearchState(topic="temp-only"))
    assert db.is_file()
    # Project default path must not be created by this test run.
    # (If a leftover exists from manual use, that is outside this test.)
    print("PASS 16: database lives under TemporaryDirectory")
    return db


def test_nested_evidence_strategy_snapshot(tmp: Path) -> None:
    db = tmp / "nested_strategy.db"
    analyzed = AnalyzedQuery(
        raw_query="卫星通信产业链",
        query_type=QueryType.TECHNOLOGY,
        normalized_topic="卫星通信产业链",
        research_goal="技术与链条",
    )
    plan = ResearchPlan(
        topic="卫星通信产业链",
        depth=ResearchDepth.STANDARD,
        query_type=QueryType.TECHNOLOGY,
        steps=[
            ResearchPlanStep(
                1,
                "产业链拆解",
                "结构",
                search_queries=["卫星通信 产业链", "卫星通信 上中下游"],
            ),
            ResearchPlanStep(
                2,
                "技术趋势",
                "技术",
                search_queries=["卫星通信 技术", "低轨 星座"],
            ),
        ],
        analyzed_query=analyzed,
    )
    plan = attach_evidence_strategies(plan, analyzed)
    assert isinstance(plan.steps[0].evidence_strategy, EvidenceStrategy)

    with ResearchRunRepository(db) as repo:
        state = ResearchState(
            topic=plan.topic,
            depth=plan.depth,
            plan=plan,
            analyzed_query=analyzed,
        )
        repo.save_state(state)
        row = repo.get_run(state.run_id)
        assert row is not None
        snap = row["state_snapshot"]
        assert isinstance(snap["plan"], dict)
        steps = snap["plan"]["steps"]
        assert isinstance(steps, list) and len(steps) >= 1
        strat = steps[0]["evidence_strategy"]
        assert isinstance(strat, dict), strat
        assert "research_task" in strat and strat["research_task"]
        assert "task_type" in strat and strat["task_type"]
        assert "evidence_targets" in strat
        assert "preferred_domains" in strat
        # Must not be a type-placeholder string
        assert not (isinstance(strat, str) and strat.startswith("<src."))

        state.mark_running("search")
        state.diagnostics["phase"] = "followup"
        repo.save_state(state)
        row2 = repo.get_run(state.run_id)
        assert row2 is not None
        assert row2["status"] == "running"
        assert row2["current_stage"] == "search"
        strat2 = row2["state_snapshot"]["plan"]["steps"][0]["evidence_strategy"]
        assert isinstance(strat2, dict)
        assert strat2["research_task"] == strat["research_task"]
        assert strat2["task_type"] == strat["task_type"]

    assert db.is_file()
    assert PROJECT_DB.resolve() != db.resolve()
    print("PASS 17: nested EvidenceStrategy persists as full dict in SQLite snapshot")


def main() -> int:
    _assert_no_project_db_created()
    project_db_existed = PROJECT_DB.exists()
    with TemporaryDirectory(prefix="rp_v13_sqlite_", ignore_cleanup_errors=True) as td:
        tmp = Path(td)
        test_initialize_and_idempotent(tmp)
        test_save_insert_and_upsert(tmp)
        test_get_run_snapshot_and_chinese(tmp)
        test_status_transitions_persisted(tmp)
        test_list_runs_order_and_limit(tmp)
        test_get_missing_and_delete(tmp)
        test_sql_injection_treated_as_data(tmp)
        test_save_does_not_mutate_state(tmp)
        test_db_only_in_temp(tmp)
        test_nested_evidence_strategy_snapshot(tmp)
        # While temp dir still exists, confirm files are under it
        assert any(tmp.glob("*.db"))
    # After context exits, temp files are gone
    if not project_db_existed:
        assert not PROJECT_DB.exists(), "tests must not create data/researchpilot.db"
    print("\nAll v1.3 SQLite storage tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
