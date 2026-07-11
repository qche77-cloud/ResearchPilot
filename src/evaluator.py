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
from src.models import (
    EvidenceDocument,
    EvaluatedEvidence,
    ResearchPlan,
)

# final_score = w_c * credibility + w_r * relevance + w_t * recency
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

        for doc in documents:
            credibility, cred_reason = _score_credibility(doc)
            relevance, rel_reason = _score_relevance(doc, plan.topic, topic_tokens)
            recency, rec_reason = _score_recency(doc.source.published_date)

            final_score = int(
                round(
                    _W_CREDIBILITY * credibility
                    + _W_RELEVANCE * relevance
                    + _W_RECENCY * recency
                )
            )
            final_score = _clamp(final_score)

            # Provisional keep from score threshold; coverage pass may revive
            # below-threshold items when a task would otherwise have zero evidence.
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
    """Prefer successful reads, then higher final_score."""
    success = 1 if item.document.read_status == "success" else 0
    return (success, item.final_score)


def _select_with_task_coverage(
    evaluated: list[EvaluatedEvidence],
    plan: ResearchPlan,
) -> tuple[list[EvaluatedEvidence], dict]:
    """Retain 1–2 sources per task when available, then fill by score."""
    per_task_target, max_total = coverage_limits(plan.depth)
    plan_tasks = _plan_task_names(plan)

    # Soft ceiling so one task cannot dominate the fill phase.
    max_per_task = max(per_task_target, min(per_task_target + 1, 3))

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

    # Pass 1: guarantee coverage — up to per_task_target per known plan task.
    # Prefer score-eligible items; if a task would get zero, allow best available.
    coverage_order = list(plan_tasks)
    for task in by_task:
        if task not in coverage_order:
            coverage_order.append(task)

    for task in coverage_order:
        bucket = by_task.get(task) or []
        if not bucket:
            continue
        taken = 0
        # First prefer items that meet the score threshold.
        eligible = [i for i in bucket if i.final_score >= _KEEP_THRESHOLD]
        pool = eligible if eligible else bucket[:1]  # revive best if needed for coverage
        for item in pool:
            if taken >= per_task_target:
                break
            if _try_add(item):
                taken += 1

    # Pass 2: fill remaining slots by global quality, respecting max_per_task.
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

    # Diagnostics
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

    dropped_tasks = [
        t for t in plan_tasks if retained_per_task.get(t, 0) == 0
    ]

    diagnostics = {
        "per_task_target": per_task_target,
        "max_total": max_total,
        "max_per_task": max_per_task,
        "retained_total": len(selected),
        "retained_sources_per_research_task": dict(sorted(retained_per_task.items())),
        "read_sources_per_research_task": dict(sorted(read_per_task.items())),
        "fallback_sources_per_research_task": dict(sorted(fallback_per_task.items())),
        "dropped_tasks_with_zero_evidence": dropped_tasks,
        "tasks_covered": sorted(retained_per_task.keys()),
        "unique_urls_retained": len(selected_urls),
    }
    return selected, diagnostics


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
