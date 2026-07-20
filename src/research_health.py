"""Research Health — deterministic post-synthesis research quality snapshot.

Evaluates coverage, freshness, grounding, diversity, and completeness using
pipeline artifacts only. Does not call LLMs or modify findings.

Intended to become persistent session health (ResearchState) in later versions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.evidence_types import EvidenceType, classify_evidence_type
from src.models import (
    EvaluatedEvidence,
    ResearchHealth,
    ResearchPlan,
    SynthesisBrief,
)
from src.synthesizer import CONTENT_SECTIONS


@dataclass
class _DimDetail:
    score: float
    notes: list[str] = field(default_factory=list)


def _clamp_score(value: float, *, digits: int = 1) -> float:
    """Defensive bound for Research Health scores to ``[0, 100]``."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0
    if v != v:  # NaN
        v = 0.0
    return round(max(0.0, min(100.0, v)), digits)


def assess_research_health(
    *,
    plan: ResearchPlan,
    evidence: list[EvaluatedEvidence],
    synthesis: SynthesisBrief | None,
    coverage_results: list[dict[str, Any]] | None = None,
) -> ResearchHealth:
    """Build a lightweight ResearchHealth snapshot (0–100 scores)."""
    retained = [e for e in evidence if e.keep]
    coverage_rows = list(coverage_results or [])

    cov = _score_coverage(plan, coverage_rows, retained)
    fresh = _score_freshness(plan, retained)
    ground = _score_grounding(synthesis)
    diversity = _score_diversity(retained)
    complete = _score_completeness(plan, synthesis)

    # Confidence: reliability of the scores themselves (data sufficiency).
    confidence = _score_confidence(
        retained_count=len(retained),
        coverage=cov.score,
        grounding=ground.score,
        completeness=complete.score,
    )

    overall = (
        0.25 * cov.score
        + 0.20 * fresh.score
        + 0.25 * ground.score
        + 0.15 * diversity.score
        + 0.15 * complete.score
    )

    warnings: list[str] = []
    suggestions: list[str] = []
    _collect_messages(cov, fresh, ground, diversity, complete, warnings, suggestions)

    coverage_score = _clamp_score(cov.score)
    freshness_score = _clamp_score(fresh.score)
    grounding_score = _clamp_score(ground.score)
    diversity_score = _clamp_score(diversity.score)
    completeness_score = _clamp_score(complete.score)
    confidence_score = _clamp_score(confidence)
    overall_score = _clamp_score(overall)

    return ResearchHealth(
        coverage_score=coverage_score,
        freshness_score=freshness_score,
        grounding_score=grounding_score,
        diversity_score=diversity_score,
        completeness_score=completeness_score,
        confidence_score=confidence_score,
        overall_score=overall_score,
        warnings=warnings,
        suggestions=suggestions,
        details={
            "coverage": {
                "score": coverage_score,
                "notes": cov.notes,
                "tasks": coverage_rows,
            },
            "freshness": {"score": freshness_score, "notes": fresh.notes},
            "grounding": {"score": grounding_score, "notes": ground.notes},
            "diversity": {"score": diversity_score, "notes": diversity.notes},
            "completeness": {"score": completeness_score, "notes": complete.notes},
            "retained_evidence_count": len(retained),
            "status": _overall_status(overall_score),
        },
    )


def research_health_to_dict(health: ResearchHealth) -> dict[str, Any]:
    return asdict(health)


def format_research_health_summary(health: ResearchHealth) -> str:
    """Short Chinese summary suitable for an optional Writer section."""
    status = (health.details or {}).get("status") or _overall_status(health.overall_score)
    lines = [
        f"研究健康度：{health.overall_score:.0f}/100（{status}）",
        (
            f"覆盖 {health.coverage_score:.0f} · 时效 {health.freshness_score:.0f} · "
            f"接地 {health.grounding_score:.0f} · 多样 {health.diversity_score:.0f} · "
            f"完整 {health.completeness_score:.0f} · 置信 {health.confidence_score:.0f}"
        ),
    ]
    if health.warnings:
        lines.append("主要提示：")
        for w in health.warnings[:5]:
            lines.append(f"- {w}")
    if health.suggestions:
        lines.append("改进建议：")
        for s in health.suggestions[:5]:
            lines.append(f"- {s}")
    return "\n".join(lines)


def _overall_status(score: float) -> str:
    if score >= 80:
        return "良好"
    if score >= 60:
        return "一般"
    if score >= 40:
        return "偏弱"
    return "不足"


def _score_coverage(
    plan: ResearchPlan,
    coverage_rows: list[dict[str, Any]],
    retained: list[EvaluatedEvidence],
) -> _DimDetail:
    notes: list[str] = []
    if coverage_rows:
        statuses = [str(r.get("coverage_status") or "").upper() for r in coverage_rows]
        n = max(len(statuses), 1)
        sufficient = sum(1 for s in statuses if s == "SUFFICIENT")
        thin = sum(1 for s in statuses if s == "THIN")
        missing = sum(1 for s in statuses if s == "MISSING")
        score = 100.0 * (sufficient + 0.5 * thin) / n
        if missing:
            notes.append(f"{missing} 个研究任务证据缺失（MISSING）")
        if thin:
            notes.append(f"{thin} 个研究任务证据偏薄（THIN）")
        for row in coverage_rows:
            if str(row.get("coverage_status") or "").upper() != "SUFFICIENT":
                missing_types = row.get("missing_evidence_targets") or []
                if missing_types:
                    notes.append(
                        f"任务「{row.get('research_task')}」缺少类型："
                        + "、".join(str(t) for t in missing_types[:4])
                    )
        return _DimDetail(score=score, notes=notes)

    # Fallback without coverage diagnostics: per-task retained counts.
    tasks = [(step.title or f"Task {step.order}").strip() for step in plan.steps]
    if not tasks:
        return _DimDetail(score=0.0, notes=["无研究任务"])
    by_task: dict[str, int] = {}
    for e in retained:
        t = (e.source.research_task or "unknown").strip() or "unknown"
        by_task[t] = by_task.get(t, 0) + 1
    hit = sum(1 for t in tasks if by_task.get(t, 0) > 0)
    score = 100.0 * hit / max(len(tasks), 1)
    if hit < len(tasks):
        notes.append(f"{len(tasks) - hit}/{len(tasks)} 个任务无保留证据")
    return _DimDetail(score=score, notes=notes)


def _score_freshness(
    plan: ResearchPlan,
    retained: list[EvaluatedEvidence],
) -> _DimDetail:
    notes: list[str] = []
    if not retained:
        return _DimDetail(score=0.0, notes=["无保留证据，无法评估时效"])

    # Profile expectations (age_days thresholds).
    limits = {
        "BREAKING": 14,
        "RECENT": 90,
        "CURRENT": 365,
        "STRUCTURAL": 10_000,
    }
    profile_by_task = {
        (step.title or f"Task {step.order}").strip(): (
            getattr(step, "freshness_profile", None) or "CURRENT"
        ).upper()
        for step in plan.steps
    }

    scored = 0.0
    counted = 0
    stale = 0
    for e in retained:
        task = (e.source.research_task or "").strip()
        profile = (e.freshness_profile or profile_by_task.get(task) or "CURRENT").upper()
        limit = limits.get(profile, 365)
        age = e.age_days
        counted += 1
        if age is None:
            # Unknown age: partial credit; harsher for BREAKING/RECENT.
            if profile in {"BREAKING", "RECENT"}:
                scored += 40.0
                notes.append(
                    f"任务「{task or 'unknown'}」为 {profile} 但证据日期未知"
                )
            else:
                scored += 70.0
            continue
        # Future dates → negative age_days; score as age 0 without mutating evidence.
        if age < 0:
            age = 0
        if age <= limit:
            # Linear decay inside window still counts as pass.
            scored += 100.0 if age <= limit * 0.5 else 80.0
        else:
            stale += 1
            # Over-age penalty scaled by how far past the limit.
            ratio = min(2.0, age / max(limit, 1))
            scored += max(10.0, 70.0 - 30.0 * (ratio - 1.0))
            if profile in {"BREAKING", "RECENT"}:
                notes.append(
                    f"{profile} 任务证据偏旧（age={age}天，期望≤{limit}天）"
                )

    score = scored / max(counted, 1)
    if stale and plan.time_sensitive:
        notes.append(f"时效敏感研究中有 {stale} 条保留证据超出期望窗口")
    return _DimDetail(score=score, notes=notes)


def _score_grounding(synthesis: SynthesisBrief | None) -> _DimDetail:
    notes: list[str] = []
    if synthesis is None:
        return _DimDetail(score=0.0, notes=["无合成结果"])

    content_findings = []
    for key in CONTENT_SECTIONS:
        for finding in getattr(synthesis, key) or []:
            if finding.finding_type == "gap":
                continue
            content_findings.append(finding)

    if not content_findings:
        gaps = len(synthesis.evidence_gaps or [])
        notes.append("无 grounded 内容发现，仅有证据缺口" if gaps else "无内容发现")
        return _DimDetail(score=20.0 if gaps else 0.0, notes=notes)

    ok = 0
    for finding in content_findings:
        has_ids = bool(finding.evidence_ids)
        has_excerpts = bool(finding.supporting_excerpts)
        if finding.finding_type == "supported_fact":
            if has_ids and has_excerpts:
                ok += 1
            else:
                notes.append("存在 supported_fact 缺少摘录或证据编号")
        elif finding.finding_type == "inference":
            # Inferences may be lightly grounded; require at least ids or excerpts.
            if has_ids or has_excerpts:
                ok += 0.85
            else:
                ok += 0.4
        else:
            ok += 0.5

    score = 100.0 * ok / max(len(content_findings), 1)
    return _DimDetail(score=min(100.0, score), notes=notes)


def _score_diversity(retained: list[EvaluatedEvidence]) -> _DimDetail:
    notes: list[str] = []
    if not retained:
        return _DimDetail(score=0.0, notes=["无保留证据"])

    types: set[str] = set()
    for e in retained:
        et = getattr(e.source, "evidence_type", None)
        if not et:
            et = classify_evidence_type(
                e.source.url, title=e.source.title, snippet=e.source.snippet
            ).value
        types.add(str(et).upper())

    # Target: at least 3 distinct non-general types for a healthy mix.
    non_general = {t for t in types if t != EvidenceType.GENERAL_WEB.value}
    n = len(non_general)
    if n >= 4:
        score = 100.0
    elif n == 3:
        score = 85.0
    elif n == 2:
        score = 65.0
    elif n == 1:
        score = 40.0
        notes.append("证据类型单一，多样性不足")
    else:
        score = 20.0
        notes.append("保留证据多为 GENERAL_WEB，缺少优选证据类型")

    if EvidenceType.COMPANY_FILING.value not in types and any(
        "映射" in ((e.source.research_task or ""))
        or "公司" in ((e.source.research_task or ""))
        for e in retained
    ):
        notes.append("公司/映射相关任务缺少 COMPANY_FILING 类证据")

    return _DimDetail(score=score, notes=notes)


def _score_completeness(
    plan: ResearchPlan,
    synthesis: SynthesisBrief | None,
) -> _DimDetail:
    notes: list[str] = []
    if synthesis is None:
        return _DimDetail(score=0.0, notes=["无合成结果"])

    # Sections expected from plan task types / always-core set.
    expected = _expected_sections(plan)
    filled = 0
    for key in expected:
        items = [
            f
            for f in (getattr(synthesis, key) or [])
            if f.finding_type != "gap"
        ]
        if items:
            filled += 1
        else:
            notes.append(f"章节缺失或为空：{key}")

    score = 100.0 * filled / max(len(expected), 1)
    gap_n = len(synthesis.evidence_gaps or [])
    if gap_n >= len(expected):
        score = min(score, 35.0)
        notes.append(f"证据缺口较多（{gap_n}）")
    return _DimDetail(score=score, notes=notes)


def _expected_sections(plan: ResearchPlan) -> list[str]:
    """Map plan tasks to synthesis sections; always include key_findings + risks."""
    expected = {"key_findings", "risks"}
    for step in plan.steps:
        strategy = getattr(step, "evidence_strategy", None)
        task_type = getattr(strategy, "task_type", None) if strategy else None
        title = f"{step.title} {step.description}".lower()
        if task_type == "chain" or "产业链" in title:
            expected.add("industry_chain_findings")
        if task_type == "demand_supply" or "供需" in title:
            expected.add("demand_supply_drivers")
        if task_type == "technology" or "技术" in title:
            expected.add("technology_findings")
        if task_type == "catalyst" or "催化" in title or "政策" in title:
            expected.add("catalysts")
        if task_type in {"mapping", "company"} or "上市公司" in title or "标的" in title:
            expected.add("company_findings")
        if task_type == "risks" or "风险" in title:
            expected.add("risks")

    # Preserve stable order from CONTENT_SECTIONS.
    return [k for k in CONTENT_SECTIONS if k in expected]


def _score_confidence(
    *,
    retained_count: int,
    coverage: float,
    grounding: float,
    completeness: float,
) -> float:
    data = min(100.0, retained_count * 12.0)  # ~9 retained → full
    agreement = (coverage + grounding + completeness) / 3.0
    return 0.45 * data + 0.55 * agreement


def _collect_messages(
    cov: _DimDetail,
    fresh: _DimDetail,
    ground: _DimDetail,
    diversity: _DimDetail,
    complete: _DimDetail,
    warnings: list[str],
    suggestions: list[str],
) -> None:
    for dim, label, threshold in (
        (cov, "覆盖", 70.0),
        (fresh, "时效", 70.0),
        (ground, "接地", 75.0),
        (diversity, "多样", 65.0),
        (complete, "完整", 70.0),
    ):
        if dim.score < threshold:
            warnings.append(f"{label}偏弱（{dim.score:.0f}/100）")
        for note in dim.notes[:3]:
            if note not in warnings:
                warnings.append(note)

    # Deterministic suggestions from known weakness patterns.
    joined = " ".join(warnings + cov.notes + diversity.notes + fresh.notes)
    if "COMPANY_FILING" in joined or "公司/映射" in joined:
        suggestions.append("补充检索公司年报/公告（site:cninfo.com.cn 或 年报 公告）")
    if "MISSING" in joined or "证据缺失" in joined:
        suggestions.append("对缺失任务发起针对性 follow-up 检索")
    if "BREAKING" in joined or "RECENT" in joined or "偏旧" in joined:
        suggestions.append("为时效任务补充近30日公告/新闻类证据")
    if "多样性不足" in joined or "GENERAL_WEB" in joined:
        suggestions.append("提高券商研报、交易所披露或权威财经媒体占比")
    if "章节缺失" in joined or "无 grounded" in joined:
        suggestions.append("检查空章节对应任务的可读证据是否不足")
    # Deduplicate preserve order
    warnings[:] = _dedupe(warnings)
    suggestions[:] = _dedupe(suggestions)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
