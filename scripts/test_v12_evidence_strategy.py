"""Focused v1.2 Evidence Strategy + adaptive budget tests.

Run:
  python scripts/test_v12_evidence_strategy.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.evidence_strategy import (
    assess_evidence_coverage,
    attach_evidence_strategies,
    build_followup_queries,
    classify_task_type,
    initial_query_budget_for_depth,
    select_queries_for_strategy,
)
from src.evidence_types import EvidenceType, classify_evidence_type, preference_boost
from src.models import (
    AnalyzedQuery,
    EvidenceDocument,
    EvaluatedEvidence,
    QueryType,
    ResearchDepth,
    ResearchPlan,
    ResearchPlanStep,
    Source,
)
from src.searcher import _collect_plan_queries, _source_rank_key


def _step(title: str, queries: list[str]) -> ResearchPlanStep:
    return ResearchPlanStep(1, title, title, search_queries=queries)


def test_taxonomy_and_classifier() -> None:
    assert classify_evidence_type("https://www.cninfo.com.cn/new/disclosure") == (
        EvidenceType.EXCHANGE_ANNOUNCEMENT
    )
    assert classify_evidence_type(
        "https://www.cninfo.com.cn/x", title="2024年年度报告"
    ) == EvidenceType.COMPANY_FILING
    assert classify_evidence_type("https://www.miit.gov.cn/policy") == (
        EvidenceType.GOVERNMENT_POLICY
    )
    assert classify_evidence_type("https://www.stcn.com/article/1") == (
        EvidenceType.FINANCIAL_NEWS
    )
    boost = preference_boost(
        "https://www.stcn.com/a",
        [EvidenceType.FINANCIAL_NEWS.value],
        ["stcn.com"],
    )
    assert boost > 0
    print("PASS: taxonomy + classifier")


def test_task_strategies_and_budget() -> None:
    assert classify_task_type("卫星通信产业链拆解") == "chain"
    assert classify_task_type("近期催化因素") == "catalyst"
    assert classify_task_type("A股标的映射") == "mapping"
    assert classify_task_type("公司概况", query_type=QueryType.COMPANY) == "company"

    budgets = initial_query_budget_for_depth(ResearchDepth.STANDARD, 5)
    assert 8 <= budgets["total_initial"] <= 10

    plan = ResearchPlan(
        topic="PCB产业链",
        depth=ResearchDepth.STANDARD,
        query_type=QueryType.INDUSTRY,
        steps=[
            ResearchPlanStep(1, "产业链结构", "拆解", ["PCB 产业链", "PCB 上中下游", "PCB 格局", "PCB overview"]),
            ResearchPlanStep(2, "供需与周期", "供需", ["PCB 供需", "PCB 产能", "PCB 需求", "PCB cycle"]),
            ResearchPlanStep(3, "技术趋势", "技术", ["PCB 技术", "PCB 瓶颈"]),
            ResearchPlanStep(4, "近期催化", "催化", ["PCB 催化", "PCB 政策", "PCB 公告"]),
            ResearchPlanStep(5, "A股标的映射", "映射", ["PCB 上市公司", "PCB A股"]),
        ],
        analyzed_query=AnalyzedQuery("PCB产业链", QueryType.INDUSTRY, "PCB产业链", "goal"),
    )
    attach_evidence_strategies(plan)
    total_q = sum(len(s.search_queries) for s in plan.steps)
    assert total_q <= 10, total_q
    assert all(s.evidence_strategy is not None for s in plan.steps)
    assert plan.steps[0].evidence_strategy.task_type == "chain"
    assert plan.steps[4].evidence_strategy.task_type == "mapping"
    pairs = _collect_plan_queries(plan)
    assert len(pairs) <= 12  # allow light RECENT augment
    print(f"PASS: strategies + budget (selected={total_q}, executed_pairs={len(pairs)})")


def test_company_prioritizes_filings() -> None:
    plan = ResearchPlan(
        topic="圣泉集团",
        depth=ResearchDepth.QUICK,
        query_type=QueryType.COMPANY,
        steps=[
            ResearchPlanStep(1, "公司概况", "概况", ["圣泉集团 发展", "圣泉集团 简介"]),
            ResearchPlanStep(2, "近期公告", "公告", ["圣泉集团 新闻"]),
            ResearchPlanStep(3, "风险", "风险", ["圣泉集团 风险"]),
        ],
        analyzed_query=AnalyzedQuery("圣泉集团", QueryType.COMPANY, "圣泉集团", "goal"),
    )
    attach_evidence_strategies(plan)
    joined = " ".join(q for s in plan.steps for q in s.search_queries)
    assert any(k in joined for k in ("年报", "公告", "投资者关系")), joined
    assert "发展" not in plan.steps[0].search_queries[0] or "年报" in joined
    # Preferred types for company overview
    prefs = plan.steps[0].evidence_strategy.preferred_source_types
    assert EvidenceType.COMPANY_FILING.value in prefs
    print("PASS: company query prefers filings/IR")


def test_hot_topic_catalyst_bias() -> None:
    plan = ResearchPlan(
        topic="商业航天",
        depth=ResearchDepth.QUICK,
        time_sensitive=True,
        query_type=QueryType.TECHNOLOGY,
        steps=[
            ResearchPlanStep(1, "今日上涨催化", "为什么涨", ["商业航天 为什么涨", "商业航天 热点"]),
            ResearchPlanStep(2, "产业链背景", "结构", ["商业航天 产业链"]),
            ResearchPlanStep(3, "风险", "风险", ["商业航天 风险"]),
        ],
        analyzed_query=AnalyzedQuery(
            "今天商业航天为什么涨",
            QueryType.TECHNOLOGY,
            "商业航天",
            "goal",
            time_sensitive=True,
        ),
    )
    # Freshness would normally annotate; simulate profiles.
    plan.steps[0].freshness_profile = "BREAKING"
    plan.steps[1].freshness_profile = "STRUCTURAL"
    attach_evidence_strategies(plan)
    assert plan.steps[0].evidence_strategy.task_type == "catalyst"
    assert plan.steps[0].evidence_strategy.initial_query_budget >= 1
    assert plan.steps[1].evidence_strategy.initial_query_budget == 1
    print("PASS: hot-topic catalyst bias + limited structural")


def test_coverage_and_followup_once() -> None:
    plan = ResearchPlan(
        topic="卫星通信",
        depth=ResearchDepth.STANDARD,
        steps=[
            ResearchPlanStep(1, "A股标的映射", "映射", ["卫星通信 上市公司"]),
            ResearchPlanStep(2, "近期催化", "催化", ["卫星通信 催化"]),
        ],
    )
    attach_evidence_strategies(plan)

    # Only weak general web retained for mapping → THIN/MISSING
    weak = EvaluatedEvidence(
        document=EvidenceDocument(
            source=Source(
                title="blog",
                url="https://example.org/x",
                snippet="x",
                source_type="web",
                relevance=0.5,
                research_task="A股标的映射",
                evidence_type=EvidenceType.GENERAL_WEB.value,
            ),
            extracted_text="x",
            word_count=1,
            read_status="fallback",
            snippet_fallback=True,
            extraction_status="HTTP_403",
        ),
        credibility_score=40,
        relevance_score=40,
        recency_score=40,
        final_score=40,
        evaluation_reason="weak",
        keep=True,
    )
    coverage = assess_evidence_coverage(plan, [weak])
    assert coverage[0].followup_needed
    pairs = build_followup_queries(plan, coverage)
    assert pairs
    assert any("年报" in q or "cninfo" in q for _, q, _ in pairs)
    # Second call with SUFFICIENT should not generate more if we mark sufficient
    coverage[0].followup_needed = False
    coverage[0].coverage_status = "SUFFICIENT"
    coverage[1].followup_needed = False
    coverage[1].coverage_status = "SUFFICIENT"
    assert build_followup_queries(plan, coverage) == []
    print("PASS: coverage check + single follow-up phase")


def test_preference_ranking_not_ban() -> None:
    preferred = Source(
        title="stcn",
        url="https://www.stcn.com/article/1",
        snippet="s",
        source_type="web",
        relevance=0.70,
        research_task="t",
    )
    general = Source(
        title="random",
        url="https://random-blog.example/x",
        snippet="s",
        source_type="web",
        relevance=0.72,
        research_task="t",
    )
    ranked = sorted(
        [preferred, general],
        key=lambda s: _source_rank_key(
            s,
            preferred_types=[EvidenceType.FINANCIAL_NEWS.value],
            preferred_domains=["stcn.com"],
        ),
        reverse=True,
    )
    assert ranked[0].url == preferred.url
    print("PASS: preference ranking soft boost")


def test_unseen_topic_no_hardcode() -> None:
    plan = ResearchPlan(
        topic="液冷产业链",
        depth=ResearchDepth.QUICK,
        query_type=QueryType.INDUSTRY,
        steps=[
            ResearchPlanStep(1, "液冷产业链结构", "拆解", ["液冷 产业链", "液冷 上中下游"]),
            ResearchPlanStep(2, "液冷供需", "供需", ["液冷 供需"]),
            ResearchPlanStep(3, "液冷A股映射", "映射", ["液冷 上市公司"]),
        ],
        analyzed_query=AnalyzedQuery("液冷产业链", QueryType.INDUSTRY, "液冷产业链", "goal"),
    )
    attach_evidence_strategies(plan)
    assert plan.steps[0].evidence_strategy.task_type == "chain"
    assert plan.steps[2].evidence_strategy.task_type == "mapping"
    assert all("液冷" in q or "产业链" in q for s in plan.steps for q in s.search_queries)
    print("PASS: unseen topic (液冷) dynamic strategy")


def main() -> int:
    test_taxonomy_and_classifier()
    test_task_strategies_and_budget()
    test_company_prioritizes_filings()
    test_hot_topic_catalyst_bias()
    test_coverage_and_followup_once()
    test_preference_ranking_not_ban()
    test_unseen_topic_no_hardcode()
    print("\nAll v1.2 Evidence Strategy focused tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
