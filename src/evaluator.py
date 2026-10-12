"""EvidenceEvaluator — score, filter, and rank extracted evidence.

Responsibility
--------------
Own *only* evidence quality control. Given ``EvidenceDocument`` objects
and the research plan, produce ``EvaluatedEvidence`` with quality scores
and coverage-aware ``keep`` flags for synthesis.

Does not search or write. Scoring is rule-based; final retention preserves
coverage across ``ResearchPlanStep`` tasks so one high-scoring task cannot
dominate the evidence set.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

from src.evidence_coverage import coverage_limits
from src.observability import traced_tool
from src.freshness import (
    FreshnessProfile,
    PROFILE_WEIGHTS,
    age_bucket,
    parse_date_best_effort,
    score_freshness,
)
from src.models import (
    EvidenceDocument,
    EvaluatedEvidence,
    ResearchPlan,
)

# Legacy uniform weights kept for documentation; profile weights override in evaluate().
_W_CREDIBILITY = 0.35
_W_RELEVANCE = 0.45
_W_RECENCY = 0.20

_KEEP_THRESHOLD = 45

# High: company announcements / government / regulators
_HIGH_HOST_HINTS = (
    ".gov",
    "gov.cn",
    "sec.gov",
    "sse.com.cn",
    "szse.cn",
    "csrc.gov",
    "stats.gov",
    "miit.gov",
    "ndrc.gov",
    "investor.",
    "ir.",
    "announcements",
)

# Medium-high: major financial / business news
_FINANCE_HOST_HINTS = (
    "reuters",
    "bloomberg",
    "wsj.com",
    "ft.com",
    "cnbc",
    "economist",
    "caixin",
    "yicai",
    "cls.cn",
    "stcn.com",
    "eastmoney",
    "sina.com.cn",
    "finance.yahoo",
    "marketwatch",
    "barrons",
    "nikkei",
)

# Medium: industry / research / encyclopedic
_INDUSTRY_HOST_HINTS = (
    "wikipedia",
    "investopedia",
    "gartner",
    "idc.com",
    "statista",
    "mckinsey",
    "deloitte",
    "pwc.com",
    "ey.com",
    "ieee",
    "nature.com",
    "sciencedirect",
    "techcrunch",
    "theverge",
    "arstechnica",
    "semi.org",
    "ipc.org",
)

# Low: blogs / forums / social
_LOW_HOST_HINTS = (
    "medium.com",
    "blogspot",
    "wordpress",
    "reddit.com",
    "quora.com",
    "zhihu.com",
    "tieba.baidu",
    "facebook.com",
    "twitter.com",
    "x.com",
    "forum",
    "discourse",
    "substack.com",
)

_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "for",
    "to",
    "in",
    "on",
    "with",
    "by",
    "from",
    "at",
    "is",
    "are",
    "as",
    "vs",
    "into",
    "about",
    "over",
    "chain",
}


class EvidenceEvaluator:
    """Evaluate and rank evidence with rule-based quality scores."""

    def __init__(self) -> None:
        self.last_diagnostics: dict = {}

    @traced_tool('evaluator.evaluate')
    def evaluate(
        self,
        documents: list[EvidenceDocument],
        plan: ResearchPlan,
    ) -> list[EvaluatedEvidence]:
        """Score each document and apply coverage-aware retention.

        Args:
            documents: Documents produced by the Reader.
            plan: Active research plan (topic / depth / tasks).

        Returns:
            EvaluatedEvidence list sorted by final_score (descending).
            ``keep`` reflects coverage-aware retention for the Synthesizer.
        """
        self.last_diagnostics = {}
        topic_tokens = _tokenize(plan.topic)
        evaluated: list[EvaluatedEvidence] = []
        task_profiles = {
            (step.title or f"Task {step.order}").strip(): (
                getattr(step, "freshness_profile", None) or "CURRENT"
            )
            for step in plan.steps
        }

        for doc in documents:
            credibility, cred_reason = _score_credibility(doc)
            relevance, rel_reason = _score_relevance(doc, plan.topic, topic_tokens)

            task = (doc.source.research_task or "unknown").strip() or "unknown"
            profile_label = (
                doc.source.freshness_profile
                or task_profiles.get(task)
                or "CURRENT"
            )
            try:
                profile = FreshnessProfile(profile_label)
            except ValueError:
                profile = FreshnessProfile.CURRENT
                profile_label = profile.value

            published_dt = parse_date_best_effort(
                doc.source.published_at or doc.source.published_date
            )
            freshness, age_days = score_freshness(published_dt, profile)
            # Keep legacy recency_score aligned with freshness for diagnostics.
            recency = freshness
            rec_reason = (
                f"Freshness {freshness} (profile={profile_label}, "
                f"age_days={age_days if age_days is not None else 'unknown'}, "
                f"date_source={doc.source.date_source or 'none'})"
            )

            w_c, w_r, w_f = PROFILE_WEIGHTS[profile]
            final_score = int(
                round(w_c * credibility + w_r * relevance + w_f * freshness)
            )
            final_score = _clamp(final_score)

            provisional_keep = final_score >= _KEEP_THRESHOLD
            reason = (
                f"{cred_reason}; {rel_reason}; {rec_reason}. "
                f"Final {final_score}/100"
                f"{'' if provisional_keep else ' — below keep threshold'}."
            )

            evaluated.append(
                EvaluatedEvidence(
                    document=doc,
                    credibility_score=credibility,
                    relevance_score=relevance,
                    recency_score=recency,
                    final_score=final_score,
                    evaluation_reason=reason,
                    keep=provisional_keep,
                    freshness_score=freshness,
                    age_days=age_days,
                    freshness_profile=profile_label,
                )
            )

        retained, diagnostics = _select_with_task_coverage(evaluated, plan)
        retained_ids = {id(item) for item in retained}
        for item in evaluated:
            item.keep = id(item) in retained_ids

        evaluated.sort(key=lambda e: (e.keep, e.final_score), reverse=True)
        self.last_diagnostics = diagnostics
        return evaluated


def _canonical_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    scheme = (parsed.scheme or "https").lower()
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "").rstrip("/")
    return urlunparse((scheme, host, path, "", "", ""))


def _plan_task_names(plan: ResearchPlan) -> list[str]:
    names: list[str] = []
    for step in plan.steps:
        title = (step.title or f"Task {step.order}").strip()
        if title and title not in names:
            names.append(title)
    return names


def _quality_key(item: EvaluatedEvidence) -> tuple:
    """Prefer successful reads, then freshness, then final_score."""
    success = 1 if item.document.read_status == "success" else 0
    return (success, item.freshness_score, item.final_score)


def _age_priority(age_days: int | None) -> int:
    """Higher is fresher (for time-sensitive ranking)."""
    if age_days is None:
        return 0
    if age_days <= 1:
        return 5
    if age_days <= 7:
        return 4
    if age_days <= 30:
        return 3
    if age_days <= 90:
        return 2
    return 1


def _hot_topic_quality_key(item: EvaluatedEvidence) -> tuple:
    """Age-first ranking for hot topics: today → 7d → 30d → 90d, then score."""
    success = 1 if item.document.read_status == "success" else 0
    return (
        _age_priority(item.age_days),
        success,
        item.freshness_score,
        item.final_score,
    )


def _is_recent_enough_for_catalyst(item: EvaluatedEvidence) -> bool:
    """True when an item can support current-event / catalyst claims."""
    if item.age_days is not None:
        return item.age_days <= 90
    profile = (item.freshness_profile or "").upper()
    if profile in {"BREAKING", "RECENT"}:
        return item.freshness_score >= 70
    return False


def _select_with_task_coverage(
    evaluated: list[EvaluatedEvidence],
    plan: ResearchPlan,
) -> tuple[list[EvaluatedEvidence], dict]:
    """Retain evidence with coverage; use hot-topic allocation when time_sensitive."""
    if bool(getattr(plan, "time_sensitive", False)):
        selected, meta = _select_time_sensitive(evaluated, plan)
    else:
        selected, meta = _select_balanced(evaluated, plan)
    diagnostics = _build_retention_diagnostics(evaluated, selected, plan, meta)
    return selected, diagnostics


def _select_balanced(
    evaluated: list[EvaluatedEvidence],
    plan: ResearchPlan,
) -> tuple[list[EvaluatedEvidence], dict]:
    """Normal (non-hot-topic) per-task coverage retention."""
    per_task_target, max_total = coverage_limits(plan.depth)
    plan_tasks = _plan_task_names(plan)
    max_per_task = per_task_target + 1

    by_task: dict[str, list[EvaluatedEvidence]] = {}
    for item in evaluated:
        task = (item.source.research_task or "unknown").strip() or "unknown"
        by_task.setdefault(task, []).append(item)

    for bucket in by_task.values():
        bucket.sort(key=_quality_key, reverse=True)

    selected: list[EvaluatedEvidence] = []
    selected_urls: set[str] = set()
    per_task_counts: dict[str, int] = {t: 0 for t in plan_tasks}

    def _try_add(item: EvaluatedEvidence) -> bool:
        if len(selected) >= max_total:
            return False
        canon = _canonical_url(item.source.url)
        if not canon or canon in selected_urls:
            return False
        task = (item.source.research_task or "unknown").strip() or "unknown"
        if per_task_counts.get(task, 0) >= max_per_task:
            return False
        selected.append(item)
        selected_urls.add(canon)
        per_task_counts[task] = per_task_counts.get(task, 0) + 1
        return True

    coverage_order = list(plan_tasks)
    for task in by_task:
        if task not in coverage_order:
            coverage_order.append(task)

    for task in coverage_order:
        bucket = by_task.get(task) or []
        if not bucket:
            continue
        taken = 0
        eligible = [i for i in bucket if i.final_score >= _KEEP_THRESHOLD]
        pool = eligible if eligible else bucket[:1]
        for item in pool:
            if taken >= per_task_target:
                break
            if _try_add(item):
                taken += 1

    remainder = sorted(
        (i for i in evaluated if _canonical_url(i.source.url) not in selected_urls),
        key=_quality_key,
        reverse=True,
    )
    for item in remainder:
        if len(selected) >= max_total:
            break
        if item.final_score < _KEEP_THRESHOLD:
            continue
        _try_add(item)

    return selected, {
        "mode": "balanced",
        "per_task_target": per_task_target,
        "max_total": max_total,
        "max_per_task": max_per_task,
        "per_task_counts": per_task_counts,
        "selected_urls": selected_urls,
    }


def _select_time_sensitive(
    evaluated: list[EvaluatedEvidence],
    plan: ResearchPlan,
) -> tuple[list[EvaluatedEvidence], dict]:
    """Hot-topic retention: recent-aged evidence dominates; STRUCTURAL capped at 1–2."""
    _, max_total = coverage_limits(plan.depth)
    recent_budget = max(3, int(round(max_total * 0.75)))
    current_budget = max(1, int(round(max_total * 0.15)))
    structural_budget = 2

    def _profile(item: EvaluatedEvidence) -> str:
        p = (item.freshness_profile or "CURRENT").upper()
        return p if p in {"BREAKING", "RECENT", "CURRENT", "STRUCTURAL"} else "CURRENT"

    # Age-first pools so fresh pages win even if Planner labeled the task STRUCTURAL.
    catalyst_pool = [
        i
        for i in evaluated
        if (i.age_days is not None and i.age_days <= 90)
        or _is_recent_enough_for_catalyst(i)
    ]
    catalyst_ids = {id(i) for i in catalyst_pool}
    catalyst_pool.sort(key=_hot_topic_quality_key, reverse=True)

    current_pool = [
        i
        for i in evaluated
        if id(i) not in catalyst_ids
        and (
            (i.age_days is not None and i.age_days <= 365)
            or _profile(i) == "CURRENT"
        )
    ]
    current_pool.sort(key=_hot_topic_quality_key, reverse=True)

    # Background only: STRUCTURAL-labeled and not already in the catalyst age pool.
    structural_pool = [
        i
        for i in evaluated
        if _profile(i) == "STRUCTURAL" and id(i) not in catalyst_ids
    ]
    structural_pool.sort(key=lambda i: (-i.final_score, -(i.age_days or 0)))

    selected: list[EvaluatedEvidence] = []
    selected_urls: set[str] = set()
    counts = {"BREAKING": 0, "RECENT": 0, "CURRENT": 0, "STRUCTURAL": 0}
    role_counts = {"catalyst": 0, "current": 0, "structural": 0}

    def _catalyst_bucket(item: EvaluatedEvidence) -> str:
        age = item.age_days
        if age is not None and age <= 1:
            return "BREAKING"
        if _profile(item) == "BREAKING":
            return "BREAKING"
        return "RECENT"

    def _try_add(item: EvaluatedEvidence, *, role: str) -> bool:
        if len(selected) >= max_total:
            return False
        canon = _canonical_url(item.source.url)
        if not canon or canon in selected_urls:
            return False
        selected.append(item)
        selected_urls.add(canon)
        if role == "catalyst":
            bucket = _catalyst_bucket(item)
            counts[bucket] = counts.get(bucket, 0) + 1
        elif role == "structural":
            counts["STRUCTURAL"] = counts.get("STRUCTURAL", 0) + 1
        else:
            counts["CURRENT"] = counts.get("CURRENT", 0) + 1
        role_counts[role] = role_counts.get(role, 0) + 1
        return True

    # 1) Catalyst / recent-aged evidence first (majority).
    for item in catalyst_pool:
        if role_counts["catalyst"] >= recent_budget or len(selected) >= max_total:
            break
        if item.final_score < _KEEP_THRESHOLD and role_counts["catalyst"] > 0:
            continue
        _try_add(item, role="catalyst")

    # 2) Limited STRUCTURAL background (max 1–2).
    for item in structural_pool:
        if role_counts["structural"] >= structural_budget or len(selected) >= max_total:
            break
        if _canonical_url(item.source.url) in selected_urls:
            continue
        if item.final_score < _KEEP_THRESHOLD and role_counts["structural"] > 0:
            continue
        _try_add(item, role="structural")

    # 3) Small CURRENT context budget.
    for item in current_pool:
        if role_counts["current"] >= current_budget or len(selected) >= max_total:
            break
        if _canonical_url(item.source.url) in selected_urls:
            continue
        if item.final_score < _KEEP_THRESHOLD:
            continue
        _try_add(item, role="current")

    # 4) Fill remainder with more catalyst items only.
    if len(selected) < max_total:
        for item in catalyst_pool:
            if len(selected) >= max_total:
                break
            if _canonical_url(item.source.url) in selected_urls:
                continue
            if item.final_score < _KEEP_THRESHOLD:
                continue
            _try_add(item, role="catalyst")

    recent_total = counts.get("BREAKING", 0) + counts.get("RECENT", 0)
    return selected, {
        "mode": "time_sensitive",
        "per_task_target": 0,
        "max_total": max_total,
        "max_per_task": max_total,
        "per_task_counts": {},
        "selected_urls": selected_urls,
        "allocation_budgets": {
            "breaking_recent": recent_budget,
            "current": current_budget,
            "structural": structural_budget,
        },
        "allocation_counts": counts,
        "allocation_roles": role_counts,
        "breaking_recent_total": recent_total,
        "breaking_recent_pct": round(100.0 * recent_total / max(len(selected), 1), 1),
        "structural_background": counts.get("STRUCTURAL", 0),
        "recent_catalyst_insufficient": role_counts.get("catalyst", 0) < 2,
    }


def _build_retention_diagnostics(
    evaluated: list[EvaluatedEvidence],
    selected: list[EvaluatedEvidence],
    plan: ResearchPlan,
    meta: dict,
) -> dict:
    plan_tasks = _plan_task_names(plan)
    selected_urls: set[str] = set(meta.get("selected_urls") or set())
    per_task_counts: dict[str, int] = dict(meta.get("per_task_counts") or {})
    max_per_task = int(meta.get("max_per_task") or 0)
    max_total = int(meta.get("max_total") or coverage_limits(plan.depth)[1])

    retained_per_task: dict[str, int] = {}
    read_per_task: dict[str, int] = {}
    fallback_per_task: dict[str, int] = {}
    for item in selected:
        task = (item.source.research_task or "unknown").strip() or "unknown"
        retained_per_task[task] = retained_per_task.get(task, 0) + 1
        if item.document.read_status == "success":
            read_per_task[task] = read_per_task.get(task, 0) + 1
        else:
            fallback_per_task[task] = fallback_per_task.get(task, 0) + 1

    dropped_tasks = [t for t in plan_tasks if retained_per_task.get(t, 0) == 0]

    drop_reasons: dict[str, int] = {
        "low_relevance": 0,
        "low_credibility": 0,
        "below_score_threshold": 0,
        "global_source_limit": 0,
        "per_task_source_limit": 0,
        "duplicate_url": 0,
        "old_structural_deprioritized": 0,
        "other": 0,
    }
    selected_set = {id(x) for x in selected}
    time_sensitive = bool(getattr(plan, "time_sensitive", False))
    for item in evaluated:
        if id(item) in selected_set:
            continue
        canon = _canonical_url(item.source.url)
        task = (item.source.research_task or "unknown").strip() or "unknown"
        profile = (item.freshness_profile or "").upper()
        if canon in selected_urls:
            drop_reasons["duplicate_url"] += 1
        elif item.final_score < _KEEP_THRESHOLD:
            drop_reasons["below_score_threshold"] += 1
            if item.relevance_score < 45:
                drop_reasons["low_relevance"] += 1
            if item.credibility_score < 45:
                drop_reasons["low_credibility"] += 1
        elif time_sensitive and profile == "STRUCTURAL":
            drop_reasons["old_structural_deprioritized"] += 1
        elif per_task_counts.get(task, 0) >= max_per_task > 0:
            drop_reasons["per_task_source_limit"] += 1
        elif len(selected) >= max_total:
            drop_reasons["global_source_limit"] += 1
        else:
            drop_reasons["other"] += 1

    passing_threshold = sum(1 for e in evaluated if e.final_score >= _KEEP_THRESHOLD)

    age_buckets: dict[str, int] = {
        "today": 0,
        "7_days": 0,
        "30_days": 0,
        "90_days": 0,
        "1_year": 0,
        "older": 0,
        "unknown": 0,
    }
    profile_counts: dict[str, int] = {}
    retained_date_rows: list[dict] = []
    for item in selected:
        bucket = age_bucket(item.age_days)
        age_buckets[bucket] = age_buckets.get(bucket, 0) + 1
        profile = item.freshness_profile or "CURRENT"
        profile_counts[profile] = profile_counts.get(profile, 0) + 1
        retained_date_rows.append(
            {
                "source_id": item.source.source_id,
                "research_task": item.source.research_task,
                "freshness_profile": profile,
                "published_at": item.source.published_at,
                "date_source": item.source.date_source,
                "date_confidence": item.source.date_confidence,
                "age_days": item.age_days,
                "age_bucket": bucket,
                "freshness_score": item.freshness_score,
                "final_score": item.final_score,
            }
        )

    # Hot-topic diagnostics use allocation roles (age-based), not Planner labels alone.
    alloc = meta.get("allocation_counts") or {}
    if meta.get("mode") == "time_sensitive" and alloc:
        breaking_recent = int(alloc.get("BREAKING", 0)) + int(alloc.get("RECENT", 0))
        structural_background = int(alloc.get("STRUCTURAL", 0))
        effective_profiles = {
            k: int(alloc.get(k, 0))
            for k in ("BREAKING", "RECENT", "CURRENT", "STRUCTURAL")
            if int(alloc.get(k, 0)) > 0
        }
        br_pct = float(
            meta.get("breaking_recent_pct")
            or round(100.0 * breaking_recent / max(len(selected), 1), 1)
        )
    else:
        breaking_recent = profile_counts.get("BREAKING", 0) + profile_counts.get(
            "RECENT", 0
        )
        structural_background = profile_counts.get("STRUCTURAL", 0)
        effective_profiles = dict(sorted(profile_counts.items()))
        br_pct = round(100.0 * breaking_recent / max(len(selected), 1), 1)

    diagnostics = {
        "per_task_target": meta.get("per_task_target"),
        "max_total": max_total,
        "max_per_task": max_per_task,
        "evaluated_total": len(evaluated),
        "passing_score_threshold": passing_threshold,
        "retained_total": len(selected),
        "retained_sources_per_research_task": dict(sorted(retained_per_task.items())),
        "read_sources_per_research_task": dict(sorted(read_per_task.items())),
        "fallback_sources_per_research_task": dict(sorted(fallback_per_task.items())),
        "dropped_tasks_with_zero_evidence": dropped_tasks,
        "tasks_covered": sorted(retained_per_task.keys()),
        "unique_urls_retained": len(selected_urls),
        "drop_reasons": drop_reasons,
        "keep_threshold": _KEEP_THRESHOLD,
        "retained_age_buckets": age_buckets,
        "retained_freshness_profiles": effective_profiles,
        "retained_planner_profiles": dict(sorted(profile_counts.items())),
        "retained_source_dates": retained_date_rows,
        "time_sensitive": time_sensitive,
        "retention_mode": meta.get("mode"),
        "breaking_recent_total": breaking_recent,
        "breaking_recent_pct": br_pct,
        "structural_background": structural_background,
        "allocation_budgets": meta.get("allocation_budgets"),
        "allocation_counts": meta.get("allocation_counts"),
        "allocation_roles": meta.get("allocation_roles"),
        "recent_catalyst_insufficient": bool(meta.get("recent_catalyst_insufficient")),
    }
    return diagnostics


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, value))


def _tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric tokens, dropping stopwords."""
    raw = re.findall(r"[a-z0-9\u4e00-\u9fff]+", (text or "").lower())
    return {t for t in raw if t not in _STOPWORDS and len(t) > 1}


def _score_credibility(doc: EvidenceDocument) -> tuple[int, str]:
    """Domain / source-type credibility tier (0–100)."""
    source = doc.source
    host = urlparse(source.url).netloc.lower()
    stype = (source.source_type or "").lower()
    title_l = (source.title or "").lower()

    if any(h in host for h in _HIGH_HOST_HINTS) or any(
        k in stype for k in ("government", "regulatory")
    ):
        score = 92
        label = "government / regulatory / IR source"
    elif any(h in host for h in _FINANCE_HOST_HINTS) or "news" in stype:
        score = 80
        label = "major financial / business news"
    elif any(h in host for h in _INDUSTRY_HOST_HINTS) or any(
        k in stype for k in ("industry", "research", "analyst", "report")
    ):
        score = 65
        label = "industry / research site"
    elif any(h in host for h in _LOW_HOST_HINTS) or any(
        k in title_l for k in ("forum", "blog", "opinion")
    ):
        score = 32
        label = "blog / forum / low-authority site"
    elif "example.com" in host:
        score = 40
        label = "placeholder / mock host"
    else:
        score = 55
        label = "general web source"

    if doc.read_status == "success" and doc.word_count >= 200:
        score = _clamp(score + 4)
        label += ", full page read"
    elif doc.read_status == "fallback":
        score = _clamp(score - 8)
        label += ", snippet fallback"

    return score, f"Credibility {score} ({label})"


def _score_relevance(
    doc: EvidenceDocument,
    topic: str,
    topic_tokens: set[str],
) -> tuple[int, str]:
    """Topic overlap against title and extracted content (0–100)."""
    if not topic_tokens:
        return 50, "Relevance 50 (no topic tokens)"

    source = doc.source
    title_tokens = _tokenize(source.title)
    body_tokens = _tokenize((doc.extracted_text or "")[:4000])
    snippet_tokens = _tokenize(source.snippet or "")

    title_hits = topic_tokens & title_tokens
    body_hits = topic_tokens & body_tokens
    snippet_hits = topic_tokens & snippet_tokens

    title_cov = len(title_hits) / len(topic_tokens)
    body_cov = len(body_hits) / len(topic_tokens)
    snippet_cov = len(snippet_hits) / len(topic_tokens)

    score = int(round(100 * (0.50 * title_cov + 0.35 * body_cov + 0.15 * snippet_cov)))

    try:
        search_rel = float(source.relevance)
        score = int(round(0.85 * score + 0.15 * (search_rel * 100)))
    except (TypeError, ValueError):
        pass

    topic_l = topic.lower()
    haystack = f"{source.title} {doc.extracted_text[:800]}".lower()
    if topic_l and topic_l in haystack:
        score = _clamp(score + 12)

    score = _clamp(score)
    matched = sorted(title_hits | body_hits)[:6]
    match_note = ", ".join(matched) if matched else "weak token overlap"
    return score, f"Relevance {score} ({match_note})"


def _score_recency(published_date: str | None) -> tuple[int, str]:
    """Recency from publication date; neutral mid score if unknown."""
    if not published_date:
        return 55, "Recency 55 (no publication date)"

    parsed = _parse_date(published_date)
    if parsed is None:
        return 50, "Recency 50 (unparsed date)"

    now = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    age_days = max(0, (now - parsed).days)

    if age_days <= 30:
        score = 95
    elif age_days <= 90:
        score = 85
    elif age_days <= 180:
        score = 75
    elif age_days <= 365:
        score = 65
    elif age_days <= 730:
        score = 50
    elif age_days <= 1825:
        score = 35
    else:
        score = 20

    return score, f"Recency {score} ({age_days}d old)"


def _parse_date(value: str):
    """Best-effort parse of common date strings."""
    text = (value or "").strip()
    if not text:
        return None

    match = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if match:
        try:
            return datetime(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                tzinfo=timezone.utc,
            )
        except ValueError:
            pass

    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:32], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None
