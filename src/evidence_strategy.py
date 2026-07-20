"""Evidence Strategy — planning-layer metadata for adaptive A-share search.

Not a new agent. Attaches strategies to ResearchPlanStep, selects initial
queries within a budget, scores coverage after Evaluate, and builds one
bounded follow-up query set for THIN/MISSING tasks.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from src.evidence_types import EvidenceType, classify_evidence_type
from src.models import (
    AnalyzedQuery,
    EvidenceDocument,
    EvaluatedEvidence,
    QueryType,
    ResearchDepth,
    ResearchPlan,
    ResearchPlanStep,
)


@dataclass
class EvidenceStrategy:
    """Per-task evidence intent for Searcher budgeting and follow-up."""

    research_task: str
    task_type: str  # chain|demand_supply|technology|catalyst|mapping|risks|company|general
    evidence_targets: list[str] = field(default_factory=list)
    preferred_source_types: list[str] = field(default_factory=list)
    preferred_domains: list[str] = field(default_factory=list)
    freshness_profile: str = "CURRENT"
    initial_query_budget: int = 2
    followup_query_budget: int = 1
    selected_queries: list[str] = field(default_factory=list)


@dataclass
class EvidenceCoverageResult:
    research_task: str
    coverage_status: str  # SUFFICIENT | THIN | MISSING
    retained_count: int = 0
    readable_count: int = 0
    evidence_types_present: list[str] = field(default_factory=list)
    missing_evidence_targets: list[str] = field(default_factory=list)
    followup_needed: bool = False


# --- Task-type templates -------------------------------------------------

_TASK_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # More specific types first — titles often include the industry topic word.
    ("catalyst", ("催化", "政策", "公告", "中标", "订单", "涨价", "扩产", "热点", "为什么涨", "事件")),
    ("mapping", ("标的", "映射", "上市公司", "a股", "公司梳理", "受益", "可跟踪")),
    ("risks", ("风险", "壁垒", "竞争格局", "挑战", "不确定")),
    ("technology", ("技术", "瓶颈", "工艺", "研发", "技术趋势", "technology")),
    ("demand_supply", ("供需", "需求", "供给", "产能", "景气", "周期", "库存")),
    ("company", ("公司概况", "主营", "业务", "客户", "供应商", "同业", "股权", "业绩")),
    ("chain", ("产业链", "上中下游", "价值链", "value chain", "industry chain", "拆解", "结构")),
)

_STRATEGY_TEMPLATES: dict[str, dict[str, Any]] = {
    "chain": {
        "evidence_targets": [
            "industry research reports",
            "brokerage research",
            "industry association material",
            "company business descriptions",
        ],
        "preferred_source_types": [
            EvidenceType.BROKER_RESEARCH.value,
            EvidenceType.INDUSTRY_ASSOCIATION.value,
            EvidenceType.COMPANY_FILING.value,
            EvidenceType.INDUSTRY_MEDIA.value,
        ],
        "preferred_domains": ["chyxx.com", "askci.com", "eastmoney.com", "stcn.com"],
        "freshness_profile": "STRUCTURAL",
        "query_hints": ["产业链", "上中下游", "格局"],
    },
    "demand_supply": {
        "evidence_targets": [
            "market data",
            "company order / capacity statements",
            "industry statistics",
            "recent financial media",
        ],
        "preferred_source_types": [
            EvidenceType.MARKET_DATA.value,
            EvidenceType.COMPANY_FILING.value,
            EvidenceType.COMPANY_IR.value,
            EvidenceType.FINANCIAL_NEWS.value,
        ],
        "preferred_domains": ["cls.cn", "stcn.com", "eastmoney.com", "sina.com.cn"],
        "freshness_profile": "CURRENT",
        "query_hints": ["供需", "产能", "需求", "库存"],
    },
    "technology": {
        "evidence_targets": [
            "technical reports",
            "academic material",
            "brokerage technical research",
            "company technical disclosures",
        ],
        "preferred_source_types": [
            EvidenceType.ACADEMIC_RESEARCH.value,
            EvidenceType.BROKER_RESEARCH.value,
            EvidenceType.COMPANY_FILING.value,
            EvidenceType.INDUSTRY_MEDIA.value,
        ],
        "preferred_domains": ["cnki.net", "ofweek.com", "eastmoney.com"],
        "freshness_profile": "CURRENT",
        "query_hints": ["技术", "瓶颈", "工艺", "研发"],
    },
    "catalyst": {
        "evidence_targets": [
            "policies",
            "announcements",
            "major orders",
            "tenders",
            "capacity expansion",
            "price changes",
            "technology breakthroughs",
        ],
        "preferred_source_types": [
            EvidenceType.GOVERNMENT_POLICY.value,
            EvidenceType.EXCHANGE_ANNOUNCEMENT.value,
            EvidenceType.COMPANY_FILING.value,
            EvidenceType.FINANCIAL_NEWS.value,
        ],
        "preferred_domains": [
            "gov.cn",
            "miit.gov.cn",
            "cninfo.com.cn",
            "cls.cn",
            "stcn.com",
        ],
        "freshness_profile": "RECENT",
        "query_hints": ["催化", "公告", "中标", "扩产", "政策", "近一年"],
    },
    "mapping": {
        "evidence_targets": [
            "annual reports",
            "company announcements",
            "investor relations",
            "exchange disclosures",
            "authoritative brokerage research",
        ],
        "preferred_source_types": [
            EvidenceType.COMPANY_FILING.value,
            EvidenceType.EXCHANGE_ANNOUNCEMENT.value,
            EvidenceType.COMPANY_IR.value,
            EvidenceType.BROKER_RESEARCH.value,
        ],
        "preferred_domains": ["cninfo.com.cn", "sse.com.cn", "szse.cn", "eastmoney.com"],
        "freshness_profile": "CURRENT",
        "query_hints": ["上市公司", "年报", "公告", "A股", "标的"],
    },
    "risks": {
        "evidence_targets": [
            "annual report risk disclosures",
            "regulatory documents",
            "company announcements",
            "industry research",
        ],
        "preferred_source_types": [
            EvidenceType.COMPANY_FILING.value,
            EvidenceType.GOVERNMENT_POLICY.value,
            EvidenceType.BROKER_RESEARCH.value,
        ],
        "preferred_domains": ["cninfo.com.cn", "gov.cn", "stcn.com"],
        "freshness_profile": "CURRENT",
        "query_hints": ["风险", "监管", "壁垒"],
    },
    "company": {
        "evidence_targets": [
            "company filings",
            "exchange announcements",
            "annual reports",
            "investor relations",
            "brokerage research",
            "financial news",
        ],
        "preferred_source_types": [
            EvidenceType.COMPANY_FILING.value,
            EvidenceType.EXCHANGE_ANNOUNCEMENT.value,
            EvidenceType.COMPANY_IR.value,
            EvidenceType.BROKER_RESEARCH.value,
            EvidenceType.FINANCIAL_NEWS.value,
        ],
        "preferred_domains": [
            "cninfo.com.cn",
            "sse.com.cn",
            "szse.cn",
            "eastmoney.com",
            "stcn.com",
            "cls.cn",
        ],
        "freshness_profile": "CURRENT",
        "query_hints": ["年报", "公告", "投资者关系", "主营业务"],
    },
    "general": {
        "evidence_targets": ["industry overview", "financial media", "research notes"],
        "preferred_source_types": [
            EvidenceType.FINANCIAL_NEWS.value,
            EvidenceType.BROKER_RESEARCH.value,
            EvidenceType.INDUSTRY_MEDIA.value,
        ],
        "preferred_domains": ["stcn.com", "cls.cn", "eastmoney.com"],
        "freshness_profile": "CURRENT",
        "query_hints": [],
    },
}


def classify_task_type(title: str, description: str = "", *, query_type: QueryType | None = None) -> str:
    text = f"{title} {description}".lower()
    if query_type == QueryType.COMPANY:
        # Company plans still get fine-grained types when title matches.
        for task_type, hints in _TASK_PATTERNS:
            if task_type == "company":
                continue
            if any(h.lower() in text for h in hints):
                return task_type
        return "company"
    for task_type, hints in _TASK_PATTERNS:
        if any(h.lower() in text for h in hints):
            return task_type
    return "general"


def initial_query_budget_for_depth(depth: ResearchDepth, task_count: int) -> dict[str, int]:
    """Return global and suggested per-task initial budgets."""
    tasks = max(1, task_count)
    if depth == ResearchDepth.QUICK:
        total = min(6, max(4, tasks))
        per = 1
    elif depth == ResearchDepth.STANDARD:
        total = min(10, max(8, tasks + 3))
        per = 2
    else:
        total = min(16, max(12, tasks * 2))
        per = 2
    return {"total_initial": total, "default_per_task": per, "followup_per_task": 1 if depth == ResearchDepth.QUICK else 2}


def build_evidence_strategy(
    step: ResearchPlanStep,
    *,
    plan: ResearchPlan,
    analyzed: AnalyzedQuery | None = None,
) -> EvidenceStrategy:
    """Build a strategy for one plan step (deterministic, no LLM)."""
    analyzed = analyzed or plan.analyzed_query
    query_type = plan.query_type or (analyzed.query_type if analyzed else QueryType.INDUSTRY)
    task = (step.title or f"Task {step.order}").strip()
    task_type = classify_task_type(task, step.description or "", query_type=query_type)
    tmpl = _STRATEGY_TEMPLATES.get(task_type, _STRATEGY_TEMPLATES["general"])

    # Preserve Planner/freshness annotation when already set for hot topics.
    freshness = (step.freshness_profile or tmpl["freshness_profile"] or "CURRENT").upper()
    if plan.time_sensitive and task_type == "catalyst":
        freshness = step.freshness_profile or "BREAKING"
    if plan.time_sensitive and task_type == "chain":
        # Keep structural background limited under hot-topic plans.
        freshness = "STRUCTURAL"

    budgets = initial_query_budget_for_depth(plan.depth, len(plan.steps) or 1)
    initial_budget = budgets["default_per_task"]
    if plan.time_sensitive and task_type == "catalyst":
        initial_budget = max(initial_budget, 2)
    if plan.time_sensitive and task_type == "chain":
        initial_budget = 1

    followup_budget = budgets["followup_per_task"]
    if plan.depth == ResearchDepth.DEEP:
        followup_budget = min(2, followup_budget + 1)

    selected = select_queries_for_strategy(
        topic=plan.topic,
        step=step,
        task_type=task_type,
        hints=list(tmpl.get("query_hints") or []),
        budget=initial_budget,
        query_type=query_type,
        time_sensitive=bool(plan.time_sensitive),
        freshness=freshness,
    )

    return EvidenceStrategy(
        research_task=task,
        task_type=task_type,
        evidence_targets=list(tmpl["evidence_targets"]),
        preferred_source_types=list(tmpl["preferred_source_types"]),
        preferred_domains=list(tmpl["preferred_domains"]),
        freshness_profile=freshness,
        initial_query_budget=initial_budget,
        followup_query_budget=followup_budget,
        selected_queries=selected,
    )


def select_queries_for_strategy(
    *,
    topic: str,
    step: ResearchPlanStep,
    task_type: str,
    hints: list[str],
    budget: int,
    query_type: QueryType,
    time_sensitive: bool,
    freshness: str,
) -> list[str]:
    """Pick targeted queries from Planner candidates + strategy rewrite hints."""
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(q: str) -> None:
        q = re.sub(r"\s+", " ", (q or "").strip())
        if not q:
            return
        key = q.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(q)

    for q in step.search_queries or []:
        _add(q)

    # Strategy-shaped rewrites (generic across industries — no topic hardcoding).
    entity = topic.strip()
    if query_type == QueryType.COMPANY or task_type == "company":
        _add(f"{entity} 年报 公告")
        _add(f"{entity} 投资者关系")
        _add(f"{entity} 主营业务 公告")
    if task_type == "mapping":
        _add(f"{entity} 上市公司 年报 公告")
        _add(f"{entity} A股 公司 投资者关系")
        _add(f"site:cninfo.com.cn {entity}")
    if task_type == "catalyst":
        if time_sensitive or freshness in {"BREAKING", "RECENT"}:
            _add(f"{entity} 中标 公告 近30日")
            _add(f"{entity} 扩产 订单 最新")
            _add(f"{entity} 为什么涨 催化")
        _add(f"{entity} 工信部 政策")
        _add(f"site:miit.gov.cn {entity} 政策")
        _add(f"{entity} 政府 指导意见 近一年")
    if task_type == "chain":
        _add(f"{entity} 产业链 上中下游")
        _add(f"{entity} 产业链 格局 研报")
    if task_type == "demand_supply":
        _add(f"{entity} 供需 产能 需求")
        _add(f"{entity} 订单 产能利用率")
    if task_type == "technology":
        _add(f"{entity} 技术 瓶颈 工艺")
        _add(f"{entity} 技术趋势 研报")
    if task_type == "risks":
        _add(f"{entity} 风险 年报")
        _add(f"{entity} 监管 风险提示")

    for h in hints:
        _add(f"{entity} {h}")

    # Score: prefer queries with evidence/source intent tokens.
    intent_tokens = (
        "年报",
        "公告",
        "投资者关系",
        "政策",
        "研报",
        "产业链",
        "产能",
        "中标",
        "site:",
        "近一年",
        "最新",
        "近30日",
        "工信部",
    )

    def _score(q: str) -> tuple:
        hits = sum(1 for t in intent_tokens if t.lower() in q.lower())
        # Prefer planner originals slightly when equally intent-rich.
        planner_bonus = 1 if q in (step.search_queries or []) else 0
        return (hits, planner_bonus, -len(q))

    ranked = sorted(candidates, key=_score, reverse=True)
    return ranked[: max(1, budget)]


def attach_evidence_strategies(plan: ResearchPlan, analyzed: AnalyzedQuery | None = None) -> ResearchPlan:
    """Attach EvidenceStrategy to every step and trim step.search_queries to selected."""
    analyzed = analyzed or plan.analyzed_query
    budgets = initial_query_budget_for_depth(plan.depth, len(plan.steps) or 1)
    total_budget = budgets["total_initial"]
    # Hot-topic: spend more on catalyst/breaking tasks.
    if plan.time_sensitive:
        total_budget = min(total_budget + 1, 12 if plan.depth != ResearchDepth.DEEP else 16)

    assigned = 0
    for step in plan.steps:
        strategy = build_evidence_strategy(step, plan=plan, analyzed=analyzed)
        # Global remaining budget may force smaller per-task selection.
        remaining = max(0, total_budget - assigned)
        if remaining <= 0 and assigned > 0:
            # Still keep 1 query for uncovered tasks so coverage does not collapse.
            strategy.selected_queries = strategy.selected_queries[:1]
            strategy.initial_query_budget = 1
        else:
            take = min(strategy.initial_query_budget, max(1, remaining))
            strategy.selected_queries = strategy.selected_queries[:take]
            strategy.initial_query_budget = take
        step.evidence_strategy = strategy
        # Keep Planner candidates for diagnostics but execute selected set.
        if strategy.selected_queries:
            step.search_queries = list(strategy.selected_queries)
        # Align freshness profile with strategy when Planner left CURRENT.
        if strategy.freshness_profile:
            step.freshness_profile = strategy.freshness_profile
        assigned += len(strategy.selected_queries)

    plan.evidence_strategy_diagnostics = {
        "total_initial_budget": total_budget,
        "initial_queries_selected": assigned,
        "per_task": [
            {
                "research_task": s.evidence_strategy.research_task if s.evidence_strategy else s.title,
                "task_type": s.evidence_strategy.task_type if s.evidence_strategy else None,
                "initial_query_budget": s.evidence_strategy.initial_query_budget if s.evidence_strategy else None,
                "followup_query_budget": s.evidence_strategy.followup_query_budget if s.evidence_strategy else None,
                "selected_queries": list(s.evidence_strategy.selected_queries) if s.evidence_strategy else [],
                "preferred_source_types": list(s.evidence_strategy.preferred_source_types)
                if s.evidence_strategy
                else [],
                "freshness_profile": s.freshness_profile,
            }
            for s in plan.steps
        ],
    }
    return plan


def assess_evidence_coverage(
    plan: ResearchPlan,
    evidence: list[EvaluatedEvidence],
) -> list[EvidenceCoverageResult]:
    """Deterministic per-task coverage after Evaluate (no LLM)."""
    results: list[EvidenceCoverageResult] = []
    by_task: dict[str, list[EvaluatedEvidence]] = {}
    for item in evidence:
        if not item.keep:
            continue
        task = (item.source.research_task or "unknown").strip() or "unknown"
        by_task.setdefault(task, []).append(item)

    for step in plan.steps:
        task = (step.title or f"Task {step.order}").strip()
        strategy = step.evidence_strategy
        preferred = set((strategy.preferred_source_types if strategy else []) or [])
        retained = by_task.get(task, [])
        readable = [
            e
            for e in retained
            if e.document.read_status == "success"
            and not bool(getattr(e.document, "snippet_fallback", False))
        ]
        types_present: list[str] = []
        seen_types: set[str] = set()
        for e in retained:
            et = getattr(e.source, "evidence_type", None) or classify_evidence_type(
                e.source.url, title=e.source.title, snippet=e.source.snippet
            )
            et_s = et.value if isinstance(et, EvidenceType) else str(et)
            if et_s not in seen_types:
                seen_types.add(et_s)
                types_present.append(et_s)

        missing = [t for t in preferred if t not in seen_types]
        # Status rules
        if len(retained) == 0:
            status = "MISSING"
        elif len(readable) == 0 or (len(retained) < 2 and missing):
            status = "THIN"
        elif preferred and not any(t in seen_types for t in preferred):
            status = "THIN"
        elif plan.time_sensitive and (strategy and strategy.task_type == "catalyst"):
            # Hot catalyst tasks need young/readable evidence.
            young = [
                e
                for e in retained
                if e.age_days is not None and e.age_days <= 90
            ]
            status = "SUFFICIENT" if (len(readable) >= 1 and young) or len(readable) >= 2 else "THIN"
        else:
            status = "SUFFICIENT" if len(readable) >= 1 and len(retained) >= 1 else "THIN"

        followup = status in {"THIN", "MISSING"}
        results.append(
            EvidenceCoverageResult(
                research_task=task,
                coverage_status=status,
                retained_count=len(retained),
                readable_count=len(readable),
                evidence_types_present=types_present,
                missing_evidence_targets=missing[:6],
                followup_needed=followup,
            )
        )
    return results


def build_followup_queries(
    plan: ResearchPlan,
    coverage: list[EvidenceCoverageResult],
) -> list[tuple[str, str, str]]:
    """Return (task, query, freshness_profile) for one follow-up phase only."""
    pairs: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    topic = plan.topic

    cov_by_task = {c.research_task: c for c in coverage}
    for step in plan.steps:
        task = (step.title or f"Task {step.order}").strip()
        cov = cov_by_task.get(task)
        if not cov or not cov.followup_needed:
            continue
        strategy = step.evidence_strategy
        budget = strategy.followup_query_budget if strategy else 1
        freshness = (strategy.freshness_profile if strategy else step.freshness_profile) or "CURRENT"
        missing = list(cov.missing_evidence_targets)
        task_type = strategy.task_type if strategy else "general"

        candidates: list[str] = []
        if EvidenceType.COMPANY_FILING.value in missing or task_type in {"mapping", "company"}:
            candidates.append(f"{topic} 年报 公告")
            candidates.append(f"site:cninfo.com.cn {topic}")
        if EvidenceType.GOVERNMENT_POLICY.value in missing or task_type == "catalyst":
            candidates.append(f"{topic} 工信部 政策")
            candidates.append(f"{topic} 政府 指导意见 近一年")
        if EvidenceType.EXCHANGE_ANNOUNCEMENT.value in missing:
            candidates.append(f"{topic} 公告 披露")
        if EvidenceType.BROKER_RESEARCH.value in missing:
            candidates.append(f"{topic} 研报 深度")
        if EvidenceType.COMPANY_IR.value in missing:
            candidates.append(f"{topic} 投资者关系")
        if plan.time_sensitive and task_type == "catalyst":
            candidates.append(f"{topic} 中标 公告 近30日")
            candidates.append(f"{topic} 扩产 订单 最新")
        if not candidates:
            candidates.append(f"{topic} {task} 最新")

        # Avoid reusing already-selected initial queries.
        already = {q.lower() for q in (strategy.selected_queries if strategy else [])}
        already.update(q.lower() for q in (step.search_queries or []))
        picked = 0
        for q in candidates:
            key = q.lower()
            if key in already or key in seen:
                continue
            seen.add(key)
            pairs.append((task, q, freshness))
            picked += 1
            if picked >= max(1, budget):
                break

    return pairs


def coverage_to_dicts(coverage: list[EvidenceCoverageResult]) -> list[dict[str, Any]]:
    return [asdict(c) for c in coverage]


def strategy_summary(plan: ResearchPlan) -> dict[str, Any]:
    return dict(getattr(plan, "evidence_strategy_diagnostics", None) or {})
