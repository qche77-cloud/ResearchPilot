"""Focused Research Health tests (deterministic, no network).

Run:
  python scripts/test_research_health.py
"""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import asdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.evidence_types import EvidenceType
from src.models import (
    EvidenceDocument,
    EvaluatedEvidence,
    GroundedFinding,
    QueryType,
    ResearchDepth,
    ResearchPlan,
    ResearchPlanStep,
    Source,
    SupportingExcerpt,
    SynthesisBrief,
)
from src.research_health import (
    _clamp_score,
    assess_research_health,
    format_research_health_summary,
)


def _assert_scores_in_bounds(health) -> None:
    fields = (
        "coverage_score",
        "freshness_score",
        "grounding_score",
        "diversity_score",
        "completeness_score",
        "confidence_score",
        "overall_score",
    )
    for name in fields:
        value = getattr(health, name)
        assert 0.0 <= value <= 100.0, f"{name}={value} out of bounds"


def _source(
    *,
    sid: str,
    url: str,
    task: str,
    etype: str,
    title: str = "t",
) -> Source:
    return Source(
        title=title,
        url=url,
        snippet="snippet",
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


def _doc(source: Source, *, success: bool = True) -> EvidenceDocument:
    text = "卫星通信产业链包括上游制造与下游运营。" * 3
    return EvidenceDocument(
        source=source,
        extracted_text=text,
        word_count=40,
        read_status="success" if success else "fallback",
        extraction_status="FULL_TEXT" if success else "HTTP_403",
        snippet_fallback=not success,
        extracted_char_count=len(text),
    )


def _ev(
    source: Source,
    *,
    age_days: int | None = 30,
    profile: str = "CURRENT",
    keep: bool = True,
) -> EvaluatedEvidence:
    return EvaluatedEvidence(
        document=_doc(source),
        credibility_score=80,
        relevance_score=80,
        recency_score=80,
        final_score=80,
        evaluation_reason="ok",
        keep=keep,
        freshness_score=80,
        age_days=age_days,
        freshness_profile=profile,
    )


def _plan() -> ResearchPlan:
    return ResearchPlan(
        topic="卫星通信",
        depth=ResearchDepth.STANDARD,
        query_type=QueryType.INDUSTRY,
        steps=[
            ResearchPlanStep(1, "产业链拆解", "结构", freshness_profile="STRUCTURAL"),
            ResearchPlanStep(2, "近期催化", "催化", freshness_profile="BREAKING"),
            ResearchPlanStep(3, "A股标的映射", "映射", freshness_profile="CURRENT"),
        ],
    )


def test_rich_evidence_high_health() -> None:
    plan = _plan()
    evidence = [
        _ev(
            _source(
                sid="S1",
                url="https://www.chyxx.com/industry/1.html",
                task="产业链拆解",
                etype=EvidenceType.INDUSTRY_MEDIA.value,
            ),
            age_days=200,
            profile="STRUCTURAL",
        ),
        _ev(
            _source(
                sid="S2",
                url="https://www.cls.cn/detail/1",
                task="近期催化",
                etype=EvidenceType.FINANCIAL_NEWS.value,
            ),
            age_days=3,
            profile="BREAKING",
        ),
        _ev(
            _source(
                sid="S3",
                url="https://www.cninfo.com.cn/new/disclosure",
                task="A股标的映射",
                etype=EvidenceType.COMPANY_FILING.value,
                title="年报",
            ),
            age_days=60,
            profile="CURRENT",
        ),
        _ev(
            _source(
                sid="S4",
                url="https://www.stcn.com/article/1",
                task="近期催化",
                etype=EvidenceType.FINANCIAL_NEWS.value,
            ),
            age_days=5,
            profile="BREAKING",
        ),
    ]
    excerpt = "卫星通信产业链包括上游制造与下游运营。"
    synthesis = SynthesisBrief(
        topic=plan.topic,
        depth=plan.depth,
        key_findings=[
            GroundedFinding(
                finding="产业链完整",
                evidence_ids=["E1"],
                finding_type="supported_fact",
                supporting_excerpts=[
                    SupportingExcerpt("E1", excerpt, "t", evidence[0].source.url)
                ],
            )
        ],
        industry_chain_findings=[
            GroundedFinding(
                finding="上游制造",
                evidence_ids=["E1"],
                finding_type="supported_fact",
                supporting_excerpts=[
                    SupportingExcerpt("E1", excerpt, "t", evidence[0].source.url)
                ],
            )
        ],
        catalysts=[
            GroundedFinding(
                finding="近期催化",
                evidence_ids=["E2"],
                finding_type="supported_fact",
                supporting_excerpts=[
                    SupportingExcerpt("E2", excerpt, "t", evidence[1].source.url)
                ],
            )
        ],
        company_findings=[
            GroundedFinding(
                finding="公司映射",
                evidence_ids=["E3"],
                finding_type="supported_fact",
                supporting_excerpts=[
                    SupportingExcerpt("E3", excerpt, "t", evidence[2].source.url)
                ],
            )
        ],
        risks=[
            GroundedFinding(
                finding="风险存在",
                evidence_ids=["E1"],
                finding_type="inference",
                supporting_excerpts=[
                    SupportingExcerpt("E1", excerpt, "t", evidence[0].source.url)
                ],
            )
        ],
    )
    coverage = [
        {
            "research_task": "产业链拆解",
            "coverage_status": "SUFFICIENT",
            "retained_count": 1,
            "readable_count": 1,
            "evidence_types_present": [EvidenceType.INDUSTRY_MEDIA.value],
            "missing_evidence_targets": [],
            "followup_needed": False,
        },
        {
            "research_task": "近期催化",
            "coverage_status": "SUFFICIENT",
            "retained_count": 2,
            "readable_count": 2,
            "evidence_types_present": [EvidenceType.FINANCIAL_NEWS.value],
            "missing_evidence_targets": [],
            "followup_needed": False,
        },
        {
            "research_task": "A股标的映射",
            "coverage_status": "SUFFICIENT",
            "retained_count": 1,
            "readable_count": 1,
            "evidence_types_present": [EvidenceType.COMPANY_FILING.value],
            "missing_evidence_targets": [],
            "followup_needed": False,
        },
    ]
    health = assess_research_health(
        plan=plan,
        evidence=evidence,
        synthesis=synthesis,
        coverage_results=coverage,
    )
    assert health.overall_score >= 75, health
    assert health.grounding_score >= 85
    assert len(health.warnings) <= 3
    print("PASS 1: rich evidence → high health")
    print(format_research_health_summary(health))
    return health


def test_missing_company_filings() -> None:
    plan = _plan()
    evidence = [
        _ev(
            _source(
                sid="S1",
                url="https://random.example/blog",
                task="A股标的映射",
                etype=EvidenceType.GENERAL_WEB.value,
            )
        )
    ]
    synthesis = SynthesisBrief(
        topic=plan.topic,
        depth=plan.depth,
        company_findings=[],
        evidence_gaps=[
            GroundedFinding("缺少公司年报", [], "gap", []),
        ],
    )
    coverage = [
        {
            "research_task": "产业链拆解",
            "coverage_status": "MISSING",
            "retained_count": 0,
            "readable_count": 0,
            "evidence_types_present": [],
            "missing_evidence_targets": [EvidenceType.BROKER_RESEARCH.value],
            "followup_needed": True,
        },
        {
            "research_task": "近期催化",
            "coverage_status": "MISSING",
            "retained_count": 0,
            "readable_count": 0,
            "evidence_types_present": [],
            "missing_evidence_targets": [],
            "followup_needed": True,
        },
        {
            "research_task": "A股标的映射",
            "coverage_status": "THIN",
            "retained_count": 1,
            "readable_count": 0,
            "evidence_types_present": [EvidenceType.GENERAL_WEB.value],
            "missing_evidence_targets": [EvidenceType.COMPANY_FILING.value],
            "followup_needed": True,
        },
    ]
    health = assess_research_health(
        plan=plan,
        evidence=evidence,
        synthesis=synthesis,
        coverage_results=coverage,
    )
    assert health.coverage_score < 60
    assert any("COMPANY_FILING" in w or "覆盖" in w for w in health.warnings)
    assert any("年报" in s or "公告" in s for s in health.suggestions)
    print("PASS 2: missing filings → coverage warning + suggestion")


def test_old_breaking_evidence() -> None:
    plan = _plan()
    evidence = [
        _ev(
            _source(
                sid="S1",
                url="https://www.cls.cn/detail/old",
                task="近期催化",
                etype=EvidenceType.FINANCIAL_NEWS.value,
            ),
            age_days=400,
            profile="BREAKING",
        )
    ]
    synthesis = SynthesisBrief(
        topic=plan.topic,
        depth=plan.depth,
        catalysts=[
            GroundedFinding(
                finding="旧催化",
                evidence_ids=["E1"],
                finding_type="supported_fact",
                supporting_excerpts=[
                    SupportingExcerpt(
                        "E1",
                        "卫星通信产业链包括上游制造与下游运营。",
                        "t",
                        evidence[0].source.url,
                    )
                ],
            )
        ],
    )
    health = assess_research_health(
        plan=plan,
        evidence=evidence,
        synthesis=synthesis,
        coverage_results=[
            {
                "research_task": "近期催化",
                "coverage_status": "SUFFICIENT",
                "retained_count": 1,
                "readable_count": 1,
                "evidence_types_present": [EvidenceType.FINANCIAL_NEWS.value],
                "missing_evidence_targets": [],
                "followup_needed": False,
            }
        ],
    )
    assert health.freshness_score < 70, health.freshness_score
    assert any("偏旧" in w or "时效" in w for w in health.warnings)
    print("PASS 3: old BREAKING evidence → freshness reduced")


def test_low_diversity() -> None:
    plan = _plan()
    evidence = [
        _ev(
            _source(
                sid=f"S{i}",
                url=f"https://blog.example/{i}",
                task="产业链拆解",
                etype=EvidenceType.GENERAL_WEB.value,
            )
        )
        for i in range(3)
    ]
    health = assess_research_health(
        plan=plan,
        evidence=evidence,
        synthesis=SynthesisBrief(topic=plan.topic, depth=plan.depth),
        coverage_results=[
            {
                "research_task": "产业链拆解",
                "coverage_status": "THIN",
                "retained_count": 3,
                "readable_count": 3,
                "evidence_types_present": [EvidenceType.GENERAL_WEB.value],
                "missing_evidence_targets": [],
                "followup_needed": True,
            }
        ],
    )
    assert health.diversity_score <= 40
    assert any("多样" in w or "GENERAL_WEB" in w for w in health.warnings)
    print("PASS 4: low diversity warning")


def test_good_grounding() -> None:
    plan = _plan()
    source = _source(
        sid="S1",
        url="https://www.stcn.com/a",
        task="产业链拆解",
        etype=EvidenceType.FINANCIAL_NEWS.value,
    )
    evidence = [_ev(source)]
    excerpt = "卫星通信产业链包括上游制造与下游运营。"
    synthesis = SynthesisBrief(
        topic=plan.topic,
        depth=plan.depth,
        key_findings=[
            GroundedFinding(
                finding="结论",
                evidence_ids=["E1"],
                finding_type="supported_fact",
                supporting_excerpts=[
                    SupportingExcerpt("E1", excerpt, "t", source.url)
                ],
            )
        ],
        industry_chain_findings=[
            GroundedFinding(
                finding="链条",
                evidence_ids=["E1"],
                finding_type="supported_fact",
                supporting_excerpts=[
                    SupportingExcerpt("E1", excerpt, "t", source.url)
                ],
            )
        ],
        risks=[
            GroundedFinding(
                finding="风险",
                evidence_ids=["E1"],
                finding_type="supported_fact",
                supporting_excerpts=[
                    SupportingExcerpt("E1", excerpt, "t", source.url)
                ],
            )
        ],
    )
    health = assess_research_health(
        plan=plan, evidence=evidence, synthesis=synthesis, coverage_results=[]
    )
    assert health.grounding_score >= 95
    print("PASS 5: good grounding near full")


def test_empty_inputs_no_error() -> None:
    plan = _plan()
    health = assess_research_health(
        plan=plan,
        evidence=[],
        synthesis=None,
        coverage_results=[],
    )
    _assert_scores_in_bounds(health)
    summary = format_research_health_summary(health)
    assert summary.strip()
    print("PASS 6: empty evidence/coverage does not error")


def test_all_scores_bounded() -> None:
    plan = _plan()
    cases = [
        assess_research_health(
            plan=plan, evidence=[], synthesis=None, coverage_results=[]
        ),
        assess_research_health(
            plan=plan,
            evidence=[
                _ev(
                    _source(
                        sid="S1",
                        url="https://www.stcn.com/a",
                        task="近期催化",
                        etype=EvidenceType.FINANCIAL_NEWS.value,
                    ),
                    age_days=-5,
                    profile="BREAKING",
                )
            ],
            synthesis=SynthesisBrief(topic=plan.topic, depth=plan.depth),
            coverage_results=[
                {
                    "research_task": "近期催化",
                    "coverage_status": "MISSING",
                    "retained_count": 0,
                    "readable_count": 0,
                    "evidence_types_present": [],
                    "missing_evidence_targets": ["news"],
                    "followup_needed": True,
                }
            ],
        ),
    ]
    for health in cases:
        _assert_scores_in_bounds(health)
    # Clamp helper itself
    assert _clamp_score(-1) == 0.0
    assert _clamp_score(101) == 100.0
    assert _clamp_score(50.06) == 50.1
    print("PASS 7: all dimension/overall scores in [0, 100]")


def test_extreme_inputs_stay_bounded() -> None:
    plan = _plan()
    evidence = [
        _ev(
            _source(
                sid="Sx",
                url="https://example.com/x",
                task="产业链拆解",
                etype=EvidenceType.INDUSTRY_MEDIA.value,
            ),
            age_days=10**9,
            profile="STRUCTURAL",
            keep=True,
        ),
        _ev(
            _source(
                sid="Sy",
                url="https://example.com/y",
                task="近期催化",
                etype=EvidenceType.FINANCIAL_NEWS.value,
            ),
            age_days=None,
            profile="BREAKING",
            keep=False,
        ),
    ]
    coverage = [
        {
            "research_task": "产业链拆解",
            "coverage_status": "UNKNOWN_STATUS",
            "retained_count": -1,
            "readable_count": 999,
            "evidence_types_present": ["not-a-type"],
            "missing_evidence_targets": ["a"] * 50,
            "followup_needed": True,
        }
    ]
    health = assess_research_health(
        plan=plan,
        evidence=evidence,
        synthesis=SynthesisBrief(topic=plan.topic, depth=plan.depth),
        coverage_results=coverage,
    )
    _assert_scores_in_bounds(health)
    print("PASS 8: extreme/abnormal inputs stay in bounds")


def test_future_date_age_days() -> None:
    plan = _plan()
    evidence = [
        _ev(
            _source(
                sid="Sf",
                url="https://www.cls.cn/detail/future",
                task="近期催化",
                etype=EvidenceType.FINANCIAL_NEWS.value,
            ),
            age_days=-30,
            profile="BREAKING",
        )
    ]
    health = assess_research_health(
        plan=plan,
        evidence=evidence,
        synthesis=SynthesisBrief(topic=plan.topic, depth=plan.depth),
        coverage_results=[],
    )
    _assert_scores_in_bounds(health)
    assert evidence[0].age_days == -30  # input not mutated
    # Future date scored as age 0 → freshness should not collapse.
    assert health.freshness_score >= 50
    print("PASS 9: future dates do not raise or exceed 100")


def test_assess_does_not_mutate_inputs() -> None:
    plan = _plan()
    evidence = [
        _ev(
            _source(
                sid="S1",
                url="https://www.chyxx.com/industry/1.html",
                task="产业链拆解",
                etype=EvidenceType.INDUSTRY_MEDIA.value,
            ),
            age_days=10,
            profile="STRUCTURAL",
        )
    ]
    synthesis = SynthesisBrief(
        topic=plan.topic,
        depth=plan.depth,
        key_findings=[
            GroundedFinding(
                finding="结论",
                evidence_ids=["E1"],
                finding_type="supported_fact",
            )
        ],
    )
    coverage = [
        {
            "research_task": "产业链拆解",
            "coverage_status": "SUFFICIENT",
            "retained_count": 1,
            "readable_count": 1,
            "evidence_types_present": [EvidenceType.INDUSTRY_MEDIA.value],
            "missing_evidence_targets": [],
            "followup_needed": False,
        }
    ]
    plan_snap = copy.deepcopy(plan)
    evidence_snap = copy.deepcopy(evidence)
    synthesis_snap = copy.deepcopy(synthesis)
    coverage_snap = copy.deepcopy(coverage)
    assess_research_health(
        plan=plan,
        evidence=evidence,
        synthesis=synthesis,
        coverage_results=coverage,
    )
    assert asdict(plan) == asdict(plan_snap)
    assert asdict(evidence[0]) == asdict(evidence_snap[0])
    assert asdict(synthesis) == asdict(synthesis_snap)
    assert coverage == coverage_snap
    print("PASS 10: assess_research_health does not mutate inputs")


def test_rich_beats_poor_overall() -> None:
    rich_health = test_rich_evidence_high_health()
    plan = _plan()
    poor_health = assess_research_health(
        plan=plan,
        evidence=[],
        synthesis=SynthesisBrief(topic=plan.topic, depth=plan.depth),
        coverage_results=[
            {
                "research_task": step.title,
                "coverage_status": "MISSING",
                "retained_count": 0,
                "readable_count": 0,
                "evidence_types_present": [],
                "missing_evidence_targets": ["any"],
                "followup_needed": True,
            }
            for step in plan.steps
        ],
    )
    _assert_scores_in_bounds(rich_health)
    _assert_scores_in_bounds(poor_health)
    assert rich_health.overall_score > poor_health.overall_score, (
        rich_health.overall_score,
        poor_health.overall_score,
    )
    print(
        f"PASS 11: rich overall ({rich_health.overall_score}) "
        f"> poor overall ({poor_health.overall_score})"
    )
    return rich_health


def main() -> int:
    rich = test_rich_beats_poor_overall()
    test_missing_company_filings()
    test_old_breaking_evidence()
    test_low_diversity()
    test_good_grounding()
    test_empty_inputs_no_error()
    test_all_scores_bounded()
    test_extreme_inputs_stay_bounded()
    test_future_date_age_days()
    test_assess_does_not_mutate_inputs()
    out = Path(__file__).with_name("_research_health_example.json")
    out.write_text(
        json.dumps(
            {
                "overall_score": rich.overall_score,
                "coverage_score": rich.coverage_score,
                "freshness_score": rich.freshness_score,
                "grounding_score": rich.grounding_score,
                "diversity_score": rich.diversity_score,
                "completeness_score": rich.completeness_score,
                "confidence_score": rich.confidence_score,
                "warnings": rich.warnings,
                "suggestions": rich.suggestions,
                "summary": format_research_health_summary(rich),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\nAll Research Health tests passed.")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
