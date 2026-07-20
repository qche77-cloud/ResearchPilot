"""Offline v1.2.1 regression: Research Health → Writer / ResearchResult wiring.

Does not call OpenAI, Tavily, or the network. Forces Writer offline fallback by
clearing OPENAI_API_KEY for the write call only.

Run:
  python scripts/test_v121_regression.py
"""

from __future__ import annotations

import copy
import os
import sys
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.evidence_strategy import EvidenceCoverageResult, coverage_to_dicts
from src.evidence_types import EvidenceType
from src.models import (
    EvidenceDocument,
    EvaluatedEvidence,
    GroundedFinding,
    QueryType,
    ResearchDepth,
    ResearchPlan,
    ResearchPlanStep,
    ResearchResult,
    Source,
    SupportingExcerpt,
    SynthesisBrief,
)
from src.research_health import (
    assess_research_health,
    format_research_health_summary,
)
from src.writer import Writer

def _assert_scores_in_bounds(health) -> None:
    for name in (
        "coverage_score",
        "freshness_score",
        "grounding_score",
        "diversity_score",
        "completeness_score",
        "confidence_score",
        "overall_score",
    ):
        value = getattr(health, name)
        assert 0.0 <= float(value) <= 100.0, f"{name}={value}"


def _source(
    *,
    sid: str,
    url: str,
    task: str,
    etype: str,
    title: str = "fixture",
) -> Source:
    return Source(
        title=title,
        url=url,
        snippet="fixture snippet",
        source_type="web",
        relevance=0.9,
        research_task=task,
        source_id=sid,
        evidence_type=etype,
        freshness_profile="CURRENT",
        published_at="2026-06-01T00:00:00+00:00",
        published_date="2026-06-01",
        date_confidence="medium",
    )


def _ev(source: Source, *, age_days: int | None = 20, profile: str = "CURRENT") -> EvaluatedEvidence:
    text = f"{source.research_task} evidence body for {source.title}. " * 4
    doc = EvidenceDocument(
        source=source,
        extracted_text=text,
        word_count=40,
        read_status="success",
        extraction_status="FULL_TEXT",
        snippet_fallback=False,
        extracted_char_count=len(text),
    )
    return EvaluatedEvidence(
        document=doc,
        credibility_score=80,
        relevance_score=80,
        recency_score=80,
        final_score=80,
        evaluation_reason="ok",
        keep=True,
        freshness_score=80,
        age_days=age_days,
        freshness_profile=profile,
    )


def _finding(text: str, eid: str, url: str) -> GroundedFinding:
    return GroundedFinding(
        finding=text,
        evidence_ids=[eid],
        finding_type="supported_fact",
        supporting_excerpts=[SupportingExcerpt(eid, text, "t", url)],
    )


def _build_scenario(
    *,
    topic: str,
    query_type: QueryType,
    steps: list[ResearchPlanStep],
    evidence: list[EvaluatedEvidence],
    synthesis: SynthesisBrief,
    coverage: list[EvidenceCoverageResult],
) -> dict:
    plan = ResearchPlan(
        topic=topic,
        depth=ResearchDepth.STANDARD,
        query_type=query_type,
        steps=steps,
    )
    synthesis.topic = plan.topic
    synthesis.depth = plan.depth
    # Mirror pipeline: coverage_after → dicts → assess → write → ResearchResult
    coverage_after = coverage
    coverage_for_health = coverage_to_dicts(coverage_after)
    synthesis_before = copy.deepcopy(synthesis)

    health = assess_research_health(
        plan=plan,
        evidence=evidence,
        synthesis=synthesis,
        coverage_results=coverage_for_health,
    )
    assert asdict(synthesis) == asdict(synthesis_before), "health must not mutate synthesis"
    _assert_scores_in_bounds(health)

    summary = format_research_health_summary(health)
    assert summary.strip(), "health summary must be non-empty"

    # Offline Writer path: block load_env from re-injecting OPENAI_API_KEY
    # from .env, then clear the key so write() uses deterministic fallback.
    saved_key = os.environ.pop("OPENAI_API_KEY", None)
    try:
        with patch("src.writer.load_env", lambda *args, **kwargs: None):
            writer = Writer()
            report = writer.write(plan, synthesis, research_health=health)
    finally:
        if saved_key is not None:
            os.environ["OPENAI_API_KEY"] = saved_key

    assert report is not None
    assert report.sections, "report must have sections"
    assert report.writer_source == "fallback", report.writer_source
    health_titles = [s.title for s in report.sections if "健康" in s.title]
    assert health_titles, "report should include Research Health section when health provided"

    result = ResearchResult(
        plan=plan,
        sources=[e.source for e in evidence],
        report=report,
        evidence=evidence,
        synthesis=synthesis,
        research_health=health,
        coverage_diagnostics={
            "after_followup": coverage_for_health,
        },
    )
    assert result.research_health is not None
    _assert_scores_in_bounds(result.research_health)
    return {
        "topic": topic,
        "query_type": query_type.value,
        "overall": result.research_health.overall_score,
        "sections": [s.title for s in report.sections],
        "writer_source": report.writer_source,
    }


def scenario_industry_pcb() -> dict:
    steps = [
        ResearchPlanStep(1, "产业链拆解", "结构", freshness_profile="STRUCTURAL"),
        ResearchPlanStep(2, "供需与周期", "供需", freshness_profile="CURRENT"),
        ResearchPlanStep(3, "A股标的映射", "映射", freshness_profile="CURRENT"),
    ]
    e1 = _ev(
        _source(
            sid="S1",
            url="https://www.chyxx.com/industry/pcb.html",
            task="产业链拆解",
            etype=EvidenceType.INDUSTRY_MEDIA.value,
            title="PCB产业链",
        ),
        age_days=120,
        profile="STRUCTURAL",
    )
    e2 = _ev(
        _source(
            sid="S2",
            url="https://www.stcn.com/pcb-supply",
            task="供需与周期",
            etype=EvidenceType.FINANCIAL_NEWS.value,
            title="PCB供需",
        ),
        age_days=15,
        profile="CURRENT",
    )
    e3 = _ev(
        _source(
            sid="S3",
            url="https://www.cninfo.com.cn/new/disclosure",
            task="A股标的映射",
            etype=EvidenceType.COMPANY_FILING.value,
            title="相关公司披露",
        ),
        age_days=40,
        profile="CURRENT",
    )
    evidence = [e1, e2, e3]
    excerpt = "PCB产业链涵盖覆铜板、加工与下游应用。"
    synthesis = SynthesisBrief(
        topic="PCB产业链",
        depth=ResearchDepth.STANDARD,
        key_findings=[_finding(excerpt, "E1", e1.source.url)],
        industry_chain_findings=[_finding(excerpt, "E1", e1.source.url)],
        demand_supply_drivers=[_finding("PCB供需偏紧。", "E2", e2.source.url)],
        company_findings=[_finding("相关A股标的可跟踪。", "E3", e3.source.url)],
        risks=[_finding("周期波动风险。", "E2", e2.source.url)],
        evidence_index={"E1": e1, "E2": e2, "E3": e3},
    )
    coverage = [
        EvidenceCoverageResult(
            research_task="产业链拆解",
            coverage_status="SUFFICIENT",
            retained_count=1,
            readable_count=1,
            evidence_types_present=[EvidenceType.INDUSTRY_MEDIA.value],
        ),
        EvidenceCoverageResult(
            research_task="供需与周期",
            coverage_status="SUFFICIENT",
            retained_count=1,
            readable_count=1,
            evidence_types_present=[EvidenceType.FINANCIAL_NEWS.value],
        ),
        EvidenceCoverageResult(
            research_task="A股标的映射",
            coverage_status="SUFFICIENT",
            retained_count=1,
            readable_count=1,
            evidence_types_present=[EvidenceType.COMPANY_FILING.value],
        ),
    ]
    return _build_scenario(
        topic="PCB产业链",
        query_type=QueryType.INDUSTRY,
        steps=steps,
        evidence=evidence,
        synthesis=synthesis,
        coverage=coverage,
    )


def scenario_company_shengquan() -> dict:
    steps = [
        ResearchPlanStep(1, "公司概况", "主营", freshness_profile="STRUCTURAL"),
        ResearchPlanStep(2, "近期催化", "催化", freshness_profile="BREAKING"),
        ResearchPlanStep(3, "风险提示", "风险", freshness_profile="CURRENT"),
    ]
    e1 = _ev(
        _source(
            sid="C1",
            url="https://www.cninfo.com.cn/new/disclosure",
            task="公司概况",
            etype=EvidenceType.COMPANY_FILING.value,
            title="圣泉集团年报",
        ),
        age_days=90,
        profile="STRUCTURAL",
    )
    e2 = _ev(
        _source(
            sid="C2",
            url="https://www.cls.cn/detail/shengquan",
            task="近期催化",
            etype=EvidenceType.FINANCIAL_NEWS.value,
            title="圣泉催化",
        ),
        age_days=4,
        profile="BREAKING",
    )
    e3 = _ev(
        _source(
            sid="C3",
            url="https://www.stcn.com/shengquan-risk",
            task="风险提示",
            etype=EvidenceType.FINANCIAL_NEWS.value,
            title="风险",
        ),
        age_days=20,
        profile="CURRENT",
    )
    evidence = [e1, e2, e3]
    synthesis = SynthesisBrief(
        topic="圣泉集团",
        depth=ResearchDepth.STANDARD,
        key_findings=[_finding("圣泉集团主营新材料相关业务。", "E1", e1.source.url)],
        company_findings=[_finding("公司概况来自披露文件。", "E1", e1.source.url)],
        catalysts=[_finding("近期存在订单或产能催化。", "E2", e2.source.url)],
        risks=[_finding("原料与需求波动是主要风险。", "E3", e3.source.url)],
        evidence_index={"E1": e1, "E2": e2, "E3": e3},
    )
    coverage = [
        EvidenceCoverageResult(
            research_task="公司概况",
            coverage_status="SUFFICIENT",
            retained_count=1,
            readable_count=1,
            evidence_types_present=[EvidenceType.COMPANY_FILING.value],
        ),
        EvidenceCoverageResult(
            research_task="近期催化",
            coverage_status="SUFFICIENT",
            retained_count=1,
            readable_count=1,
            evidence_types_present=[EvidenceType.FINANCIAL_NEWS.value],
        ),
        EvidenceCoverageResult(
            research_task="风险提示",
            coverage_status="THIN",
            retained_count=1,
            readable_count=1,
            evidence_types_present=[EvidenceType.FINANCIAL_NEWS.value],
            followup_needed=False,
        ),
    ]
    return _build_scenario(
        topic="圣泉集团",
        query_type=QueryType.COMPANY,
        steps=steps,
        evidence=evidence,
        synthesis=synthesis,
        coverage=coverage,
    )


def scenario_technology_satellite() -> dict:
    steps = [
        ResearchPlanStep(1, "技术趋势", "技术", freshness_profile="CURRENT"),
        ResearchPlanStep(2, "产业链拆解", "结构", freshness_profile="STRUCTURAL"),
        ResearchPlanStep(3, "近期催化", "催化", freshness_profile="BREAKING"),
    ]
    e1 = _ev(
        _source(
            sid="T1",
            url="https://www.ofweek.com/satcom-tech",
            task="技术趋势",
            etype=EvidenceType.INDUSTRY_MEDIA.value,
            title="卫星通信技术",
        ),
        age_days=45,
        profile="CURRENT",
    )
    e2 = _ev(
        _source(
            sid="T2",
            url="https://www.chyxx.com/industry/satcom.html",
            task="产业链拆解",
            etype=EvidenceType.INDUSTRY_MEDIA.value,
            title="卫星通信产业链",
        ),
        age_days=150,
        profile="STRUCTURAL",
    )
    e3 = _ev(
        _source(
            sid="T3",
            url="https://www.cls.cn/detail/satcom",
            task="近期催化",
            etype=EvidenceType.FINANCIAL_NEWS.value,
            title="卫星催化",
        ),
        age_days=2,
        profile="BREAKING",
    )
    evidence = [e1, e2, e3]
    synthesis = SynthesisBrief(
        topic="卫星通信产业链",
        depth=ResearchDepth.STANDARD,
        key_findings=[_finding("卫星通信技术持续迭代。", "E1", e1.source.url)],
        technology_findings=[_finding("低轨星座推动终端需求。", "E1", e1.source.url)],
        industry_chain_findings=[
            _finding("产业链含制造、发射与运营。", "E2", e2.source.url)
        ],
        catalysts=[_finding("政策与订单催化活跃。", "E3", e3.source.url)],
        risks=[_finding("技术与资本开支风险仍在。", "E1", e1.source.url)],
        evidence_index={"E1": e1, "E2": e2, "E3": e3},
    )
    coverage = [
        EvidenceCoverageResult(
            research_task="技术趋势",
            coverage_status="SUFFICIENT",
            retained_count=1,
            readable_count=1,
            evidence_types_present=[EvidenceType.INDUSTRY_MEDIA.value],
        ),
        EvidenceCoverageResult(
            research_task="产业链拆解",
            coverage_status="SUFFICIENT",
            retained_count=1,
            readable_count=1,
            evidence_types_present=[EvidenceType.INDUSTRY_MEDIA.value],
        ),
        EvidenceCoverageResult(
            research_task="近期催化",
            coverage_status="SUFFICIENT",
            retained_count=1,
            readable_count=1,
            evidence_types_present=[EvidenceType.FINANCIAL_NEWS.value],
        ),
    ]
    return _build_scenario(
        topic="卫星通信产业链",
        query_type=QueryType.TECHNOLOGY,
        steps=steps,
        evidence=evidence,
        synthesis=synthesis,
        coverage=coverage,
    )


def main() -> int:
    results = [
        scenario_industry_pcb(),
        scenario_company_shengquan(),
        scenario_technology_satellite(),
    ]
    for row in results:
        print(
            f"PASS: {row['query_type']} / {row['topic']} "
            f"overall={row['overall']} writer={row['writer_source']}"
        )
    print("\nAll v1.2.1 offline regression checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
