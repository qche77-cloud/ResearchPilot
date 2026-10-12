"""Searcher — discover candidate sources for a research plan.

Responsibility
--------------
Own *only* source discovery. Given a ``ResearchPlan``, execute the
Planner's per-task ``search_queries`` (via Tavily when configured) and
return normalized ``Source`` metadata.

Does not fetch full page content (Reader) or score quality
(EvidenceEvaluator). Missing keys and request failures return no evidence;
synthetic source templates are private fixtures and never a live fallback.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse, urlunparse

from src.domain_penalty import apply_relevance_penalty, domain_of, load_domain_penalties
from src.env import load_env
from src.observability import request_json, traced_tool
from src.evidence_coverage import coverage_limits, search_candidate_limit
from src.evidence_types import classify_evidence_type, preference_boost
from src.freshness import (
    FreshnessProfile,
    augment_queries_for_freshness,
    parse_date_best_effort,
    score_freshness,
)
from src.models import ResearchDepth, ResearchPlan, Source

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_TIMEOUT_SECONDS = 30
# Per-query fetch size before cross-task balancing / capping.
_PER_QUERY_MAX_RESULTS = 4
_REPLACEMENT_MAX_RESULTS = 3

SOURCE_TEMPLATES: list[tuple[str, str, str, str]] = [
    (
        "{topic} Market Size & Forecast Report 2025–2030",
        "https://example.com/reports/{slug}-market-forecast",
        "Comprehensive analysis of global {topic} market sizing, CAGR projections, and regional breakdown.",
        "Industry Report",
    ),
    (
        "State of {topic}: Technology Trends and Adoption",
        "https://example.com/insights/{slug}-technology-trends",
        "Survey of emerging technologies, R&D investments, and commercialization timelines in {topic}.",
        "Technology Brief",
    ),
    (
        "{topic} Value Chain Analysis",
        "https://example.com/analysis/{slug}-value-chain",
        "End-to-end mapping of suppliers, manufacturers, distributors, and end-users in the {topic} industry.",
        "Analyst Note",
    ),
    (
        "Top Companies in {topic} — Competitive Landscape",
        "https://example.com/companies/{slug}-leaders",
        "Profiles of market leaders including revenue estimates, product portfolios, and strategic positioning.",
        "Competitive Intelligence",
    ),
    (
        "{topic} Supply Chain & Raw Material Outlook",
        "https://example.com/supply-chain/{slug}-materials",
        "Assessment of upstream dependencies, capacity utilization, and cost pressures affecting {topic}.",
        "Supply Chain Report",
    ),
    (
        "Recent Developments in {topic}",
        "https://example.com/news/{slug}-developments",
        "Roundup of product launches, partnerships, regulatory changes, and investment activity in {topic}.",
        "News Digest",
    ),
    (
        "{topic} Risk Factors and Market Uncertainties",
        "https://example.com/risks/{slug}-outlook",
        "Analysis of geopolitical, technological, and demand-side risks shaping the {topic} market outlook.",
        "Risk Assessment",
    ),
    (
        "Policy Landscape for {topic}",
        "https://example.com/policy/{slug}-regulation",
        "Overview of subsidies, trade policies, environmental regulations, and standards impacting {topic}.",
        "Policy Review",
    ),
    (
        "{topic} Patent and IP Landscape",
        "https://example.com/ip/{slug}-patents",
        "Mapping of key patent holders, licensing activity, and IP barriers in the {topic} space.",
        "IP Analysis",
    ),
    (
        "Investor Sentiment on {topic}",
        "https://example.com/investing/{slug}-sentiment",
        "VC funding trends, public market performance, and analyst consensus on {topic} sector growth.",
        "Investment Research",
    ),
    (
        "{topic} Regional Market Comparison",
        "https://example.com/regions/{slug}-comparison",
        "Comparative analysis of North America, Europe, and Asia-Pacific markets for {topic}.",
        "Regional Report",
    ),
    (
        "Expert Interviews: Future of {topic}",
        "https://example.com/interviews/{slug}-experts",
        "Synthesis of executive and analyst perspectives on long-term trajectory of {topic}.",
        "Expert Commentary",
    ),
]


def _slugify(topic: str) -> str:
    """Convert a topic string into a URL-friendly slug."""
    return topic.lower().replace(" ", "-").replace("/", "-")


def _canonical_url(url: str) -> str:
    """Normalize a URL for deduplication."""
    parsed = urlparse((url or "").strip())
    scheme = (parsed.scheme or "https").lower()
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "").rstrip("/")
    return urlunparse((scheme, host, path, "", "", ""))


def _infer_source_type(url: str) -> str:
    """Best-effort source type from the URL host."""
    host = urlparse(url).netloc.lower()
    if any(token in host for token in ("reuters", "bloomberg", "ft.com", "wsj", "cnbc", "news")):
        return "News"
    if any(token in host for token in ("arxiv", "ieee", "nature", "sciencedirect", "springer")):
        return "Research"
    if host.endswith(".gov") or ".gov." in host:
        return "Government"
    if any(token in host for token in ("sec.gov", "edgar", "cninfo", "sse.com", "szse")):
        return "Regulatory Filing"
    return "Web Result"


def _normalize_tavily_result(
    item: dict,
    index: int,
    *,
    search_query: str,
    research_task: str,
    freshness_profile: str | None = None,
) -> Source | None:
    """Convert a Tavily result dict into a ``Source``, or None if unusable."""
    title = (item.get("title") or "").strip()
    url = (item.get("url") or "").strip()
    snippet = (item.get("content") or item.get("snippet") or "").strip()
    if not title or not url:
        return None

    score = item.get("score")
    try:
        relevance = round(float(score), 2) if score is not None else round(0.95 - index * 0.04, 2)
    except (TypeError, ValueError):
        relevance = round(0.95 - index * 0.04, 2)

    published = item.get("published_date") or item.get("publishedDate")
    published_date = str(published).strip() if published else None
    published_at = None
    date_source = "none"
    date_confidence = "none"
    if published_date:
        dt = parse_date_best_effort(published_date)
        if dt:
            published_at = dt.isoformat()
            date_source = "tavily"
            date_confidence = "medium"
            published_date = dt.date().isoformat()

    return Source(
        title=title,
        url=url,
        snippet=snippet or "No snippet available.",
        source_type=_infer_source_type(url),
        relevance=max(0.0, min(1.0, relevance)),
        published_date=published_date,
        search_query=search_query,
        research_task=research_task,
        published_at=published_at,
        date_source=date_source,
        date_confidence=date_confidence,
        freshness_profile=freshness_profile,
        evidence_type=classify_evidence_type(
            url, title=title, snippet=snippet or ""
        ).value,
        query_role="initial",
    )


def _preferred_types_for_task(plan: ResearchPlan, task: str) -> list[str]:
    for step in plan.steps:
        title = (step.title or f"Task {step.order}").strip()
        if title == task and step.evidence_strategy is not None:
            return list(step.evidence_strategy.preferred_source_types or [])
    return []


def _preferred_domains_for_task(plan: ResearchPlan, task: str) -> list[str]:
    for step in plan.steps:
        title = (step.title or f"Task {step.order}").strip()
        if title == task and step.evidence_strategy is not None:
            return list(step.evidence_strategy.preferred_domains or [])
    return []


def _collect_plan_queries(plan: ResearchPlan) -> list[tuple[str, str, str]]:
    """Collect (research_task, search_query, freshness_profile) pairs.

    When Evidence Strategy is attached, prefer ``selected_queries`` and only
    lightly freshness-augment BREAKING/RECENT tasks (≤1 extra).
    """
    pairs: list[tuple[str, str, str]] = []
    seen_queries: set[str] = set()
    time_sensitive = bool(getattr(plan, "time_sensitive", False))
    topic = plan.topic

    for step in plan.steps:
        task = (step.title or f"Task {step.order}").strip()
        profile = (
            getattr(step, "freshness_profile", None)
            or FreshnessProfile.CURRENT.value
        )
        try:
            profile_enum = FreshnessProfile(profile)
        except ValueError:
            profile_enum = FreshnessProfile.CURRENT
            profile = profile_enum.value

        strategy = getattr(step, "evidence_strategy", None)
        if strategy is not None and getattr(strategy, "selected_queries", None):
            base = list(strategy.selected_queries)
        else:
            base = list(step.search_queries or [])

        if strategy is not None:
            if profile_enum in {FreshnessProfile.BREAKING, FreshnessProfile.RECENT}:
                augmented = augment_queries_for_freshness(
                    base,
                    topic,
                    profile_enum,
                    time_sensitive=time_sensitive,
                )
                extras = [q for q in augmented if q not in base][:1]
                queries = base + extras
            else:
                queries = base
        else:
            queries = augment_queries_for_freshness(
                base,
                topic,
                profile_enum,
                time_sensitive=time_sensitive,
            )

        for query in queries:
            key = query.lower()
            if key in seen_queries:
                continue
            seen_queries.add(key)
            pairs.append((task, query, profile))

    return pairs


def _fallback_topic_query(plan: ResearchPlan) -> str:
    """Single topic query used only when the Planner provided no search_queries."""
    return f"{plan.topic} 中国 A股 产业链"


def _replacement_query(plan: ResearchPlan, failed_source: Source) -> str:
    """Build a cheap replacement query from task context + failed title."""
    task = (failed_source.research_task or "").strip()
    title = (failed_source.title or "").strip()
    topic = (plan.topic or "").strip()
    pieces = [p for p in (topic, task, title[:80]) if p]
    return " ".join(pieces) if pieces else topic or "research"


def _source_rank_key(
    source: Source,
    *,
    penalties: dict[str, float] | None = None,
    preferred_types: list[str] | None = None,
    preferred_domains: list[str] | None = None,
) -> tuple:
    """Rank key: relevance + preference boost + soft domain penalty + freshness."""
    try:
        profile = FreshnessProfile(source.freshness_profile or "CURRENT")
    except ValueError:
        profile = FreshnessProfile.CURRENT
    dt = parse_date_best_effort(source.published_at or source.published_date)
    fresh_score, _ = score_freshness(dt, profile)
    boost = preference_boost(
        source.url,
        preferred_types or [],
        preferred_domains or [],
    )
    adj_rel, _matched, _applied = apply_relevance_penalty(
        float(source.relevance) + boost,
        source.url,
        penalties=penalties,
    )
    return (adj_rel, fresh_score / 100.0)


def _domain_penalty_events(
    sources: list[Source],
    *,
    penalties: dict[str, float] | None = None,
) -> list[dict]:
    """Diagnostics for sources that received a soft domain penalty."""
    events: list[dict] = []
    for source in sources:
        adj_rel, matched, applied = apply_relevance_penalty(
            float(source.relevance),
            source.url,
            penalties=penalties,
        )
        if not applied or matched is None:
            continue
        events.append(
            {
                "source_id": source.source_id,
                "url": source.url,
                "domain": matched,
                "research_task": source.research_task,
                "original_relevance": float(source.relevance),
                "adjusted_relevance": round(adj_rel, 4),
                "multiplier": round(
                    adj_rel / float(source.relevance), 3
                )
                if source.relevance
                else None,
            }
        )
    return events


def _balance_sources_across_tasks(
    sources: list[Source],
    limit: int,
    *,
    per_task_target: int = 2,
    penalties: dict[str, float] | None = None,
    plan: ResearchPlan | None = None,
) -> list[Source]:
    """Prefer coverage across research tasks, then fill by relevance/freshness."""
    if limit <= 0 or not sources:
        return []

    def _key(source: Source) -> tuple:
        task = source.research_task or "unknown"
        prefs = _preferred_types_for_task(plan, task) if plan else []
        domains = _preferred_domains_for_task(plan, task) if plan else []
        return _source_rank_key(
            source,
            penalties=penalties,
            preferred_types=prefs,
            preferred_domains=domains,
        )

    by_task: dict[str, list[Source]] = {}
    for source in sources:
        task = source.research_task or "unknown"
        by_task.setdefault(task, []).append(source)

    for task_sources in by_task.values():
        task_sources.sort(key=_key, reverse=True)

    selected: list[Source] = []
    selected_urls: set[str] = set()
    task_names = list(by_task.keys())
    per_task_taken: dict[str, int] = {t: 0 for t in task_names}
    n_tasks = max(len(task_names), 1)
    max_per_task = max(
        per_task_target + 1,
        (limit + n_tasks - 1) // n_tasks,
    )

    for _wave in range(per_task_target):
        progress = False
        for task in task_names:
            if len(selected) >= limit:
                break
            if per_task_taken[task] >= per_task_target:
                continue
            bucket = by_task[task]
            while bucket:
                candidate = bucket.pop(0)
                canon = _canonical_url(candidate.url)
                if canon in selected_urls:
                    continue
                selected_urls.add(canon)
                selected.append(candidate)
                per_task_taken[task] += 1
                progress = True
                break
        if not progress or len(selected) >= limit:
            break

    if len(selected) < limit:
        remainder = sorted(
            (s for s in sources if _canonical_url(s.url) not in selected_urls),
            key=_key,
            reverse=True,
        )
        for candidate in remainder:
            if len(selected) >= limit:
                break
            task = candidate.research_task or "unknown"
            if per_task_taken.get(task, 0) >= max_per_task:
                continue
            selected.append(candidate)
            selected_urls.add(_canonical_url(candidate.url))
            per_task_taken[task] = per_task_taken.get(task, 0) + 1

    return selected


def _per_task_candidate_counts(sources: list[Source]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for source in sources:
        task = source.research_task or "unknown"
        counts[task] = counts.get(task, 0) + 1
    return dict(sorted(counts.items()))


class Searcher:
    """Discover candidate industry sources for a research plan.

    Attributes:
        last_warning: Human-readable warning from the most recent ``search`` call.
        last_diagnostics: Temporary diagnostics for multi-query execution.
    """

    def __init__(self) -> None:
        self.last_warning: str | None = None
        self.last_diagnostics: dict = {}
        load_env()

    @traced_tool('searcher.search')
    def search(self, plan: ResearchPlan) -> list[Source]:
        """Search using Planner ``search_queries`` when available.

        Missing configuration or service failures never manufacture evidence.
        """
        self.last_warning = None
        self.last_diagnostics = {}
        load_env()
        api_key = os.getenv("TAVILY_API_KEY", "").strip()

        if not api_key:
            self.last_warning = (
                "TAVILY_API_KEY is not configured. No live search was performed. "
                "Add the key to your .env file to enable live web search."
            )
            logger.info(self.last_warning)
            self.last_diagnostics = {'mode': 'unavailable', 'error_type': 'missing_configuration', 'tavily_search_calls': 0}
            return []

        try:
            sources = self._tavily_multi_query_search(plan, api_key)
            if not sources:
                self.last_warning = (
                    "Tavily returned no results. No simulated sources were substituted."
                )
                logger.warning(self.last_warning)
                self.last_diagnostics['mode'] = 'no_results'
                return []
            return sources
        except Exception as exc:  # noqa: BLE001 — intentional graceful fallback
            self.last_warning = (
                f"Tavily search failed ({type(exc).__name__}). No simulated sources were substituted."
            )
            logger.warning(self.last_warning)
            self.last_diagnostics.update(mode='unavailable', error_type=type(exc).__name__)
            return []

    def _mock_search(self, plan: ResearchPlan) -> list[Source]:
        """Private synthetic fixture helper; never used by the live search path."""
        topic = plan.topic
        slug = _slugify(topic)
        count = plan.depth.source_count
        query_pairs = _collect_plan_queries(plan)
        sources: list[Source] = []

        for i, (title_tpl, url_tpl, snippet_tpl, source_type) in enumerate(
            SOURCE_TEMPLATES[:count]
        ):
            if query_pairs:
                task, query, profile = query_pairs[i % len(query_pairs)]
            else:
                task, query, profile = "Fallback", _fallback_topic_query(plan), "CURRENT"
            relevance = round(0.95 - (i * 0.04), 2)
            sources.append(
                Source(
                    title=title_tpl.format(topic=topic),
                    url=url_tpl.format(slug=slug),
                    snippet=snippet_tpl.format(topic=topic),
                    source_type=source_type,
                    relevance=relevance,
                    published_date=None,
                    search_query=query,
                    research_task=task,
                    source_id=f"S{i + 1}",
                    freshness_profile=profile,
                )
            )

        self.last_diagnostics = {
            "planner_queries_generated": len(query_pairs),
            "queries_executed": 0,
            "executed_queries": [],
            "results_per_query": {},
            "raw_results_total": len(sources),
            "unique_sources_after_dedupe": len(sources),
            "duplicate_url_dropped": 0,
            "dropped_by_candidate_limit": 0,
            "final_source_count": len(sources),
            "source_ids": [s.source_id for s in sources if s.source_id],
            "mode": "mock",
            "initial_queries_executed": 0,
            "followup_queries_executed": 0,
            "tavily_search_calls": 0,
            "evidence_strategy": getattr(plan, "evidence_strategy_diagnostics", None),
            "v11_baseline_query_estimate": max(20, len(plan.steps) * 4),
            "queries_saved_vs_v11_baseline": max(20, len(plan.steps) * 4),
        }
        return sources

    def _tavily_multi_query_search(self, plan: ResearchPlan, api_key: str) -> list[Source]:
        """Execute each Planner search query via Tavily and balance coverage."""
        query_pairs = _collect_plan_queries(plan)
        used_fallback_topic_query = False

        if not query_pairs:
            used_fallback_topic_query = True
            query_pairs = [
                ("Fallback topic query", _fallback_topic_query(plan), "CURRENT")
            ]

        depth_flag = "basic" if plan.depth != ResearchDepth.DEEP else "advanced"
        per_task_target, max_retained = coverage_limits(plan.depth)
        task_count = len(plan.steps) or 1
        target_total = search_candidate_limit(plan.depth, task_count)
        penalties = load_domain_penalties()

        all_sources: list[Source] = []
        seen_urls: set[str] = set()
        results_per_query: dict[str, int] = {}
        executed_queries: list[dict[str, object]] = []
        raw_results_total = 0
        duplicate_url_dropped = 0
        raw_per_task: dict[str, int] = {}
        unique_per_task_before_balance: dict[str, int] = {}
        duplicates_per_task: dict[str, int] = {}
        freshness_profile_per_task: dict[str, str] = {
            (step.title or f"Task {step.order}").strip(): (
                getattr(step, "freshness_profile", None) or "CURRENT"
            )
            for step in plan.steps
        }

        for task, query, profile in query_pairs:
            raw_results = self._tavily_request(
                query=query,
                api_key=api_key,
                max_results=_PER_QUERY_MAX_RESULTS,
                search_depth=depth_flag,
            )
            results_per_query[query] = len(raw_results)
            raw_results_total += len(raw_results)
            raw_per_task[task] = raw_per_task.get(task, 0) + len(raw_results)
            kept_for_query = 0
            freshness_profile_per_task.setdefault(task, profile)

            for index, item in enumerate(raw_results):
                if not isinstance(item, dict):
                    continue
                source = _normalize_tavily_result(
                    item,
                    index,
                    search_query=query,
                    research_task=task,
                    freshness_profile=profile,
                )
                if source is None:
                    continue
                canon = _canonical_url(source.url)
                if not canon:
                    continue
                if canon in seen_urls:
                    duplicate_url_dropped += 1
                    duplicates_per_task[task] = duplicates_per_task.get(task, 0) + 1
                    continue
                seen_urls.add(canon)
                all_sources.append(source)
                unique_per_task_before_balance[task] = (
                    unique_per_task_before_balance.get(task, 0) + 1
                )
                kept_for_query += 1

            executed_queries.append(
                {
                    "research_task": task,
                    "query": query,
                    "freshness_profile": profile,
                    "raw_results": len(raw_results),
                    "unique_kept": kept_for_query,
                }
            )

        balanced = _balance_sources_across_tasks(
            all_sources,
            target_total,
            per_task_target=per_task_target,
            penalties=penalties,
            plan=plan,
        )
        # Assign stable source IDs after final Searcher selection (traceability only).
        for i, source in enumerate(balanced, start=1):
            source.source_id = f"S{i}"

        balanced_urls = {_canonical_url(s.url) for s in balanced}
        dropped_by_candidate_limit = sum(
            1 for s in all_sources if _canonical_url(s.url) not in balanced_urls
        )
        per_task_candidates = _per_task_candidate_counts(balanced)
        plan_tasks = [
            (step.title or f"Task {step.order}").strip() for step in plan.steps
        ]
        dropped_at_search = [
            t for t in plan_tasks if per_task_candidates.get(t, 0) == 0
        ]
        domain_penalty_events = _domain_penalty_events(balanced, penalties=penalties)
        demoted_out = [
            e
            for e in _domain_penalty_events(all_sources, penalties=penalties)
            if _canonical_url(str(e.get("url") or "")) not in balanced_urls
        ]

        self.last_diagnostics = {
            "planner_queries_generated": 0
            if used_fallback_topic_query
            else len(query_pairs),
            "queries_executed": len(executed_queries),
            "executed_queries": [row["query"] for row in executed_queries],
            "executed_query_details": executed_queries,
            "results_per_query": results_per_query,
            "raw_results_total": raw_results_total,
            "raw_results_per_research_task": dict(sorted(raw_per_task.items())),
            "duplicate_url_dropped": duplicate_url_dropped,
            "duplicates_per_research_task": dict(sorted(duplicates_per_task.items())),
            "unique_sources_after_dedupe": len(all_sources),
            "unique_per_research_task_before_balance": dict(
                sorted(unique_per_task_before_balance.items())
            ),
            "dropped_by_candidate_limit": dropped_by_candidate_limit,
            "final_source_count": len(balanced),
            "candidate_limit": target_total,
            "per_task_target": per_task_target,
            "max_retained_target": max_retained,
            "candidates_per_research_task": per_task_candidates,
            "dropped_tasks_at_search": dropped_at_search,
            "tasks_represented": sorted(
                {s.research_task for s in balanced if s.research_task}
            ),
            "source_ids": [s.source_id for s in balanced if s.source_id],
            "freshness_profile_per_task": dict(sorted(freshness_profile_per_task.items())),
            "time_sensitive": bool(getattr(plan, "time_sensitive", False)),
            "used_fallback_topic_query": used_fallback_topic_query,
            "mode": "tavily_multi_query",
            "domain_penalties_config": dict(sorted(penalties.items())),
            "domain_penalties_applied": domain_penalty_events,
            "domain_penalties_applied_count": len(domain_penalty_events),
            "domain_penalties_demoted_out": demoted_out,
            "domain_penalties_demoted_out_count": len(demoted_out),
            "initial_queries_executed": len(executed_queries),
            "followup_queries_executed": 0,
            "tavily_search_calls": len(executed_queries),
            "evidence_strategy": getattr(plan, "evidence_strategy_diagnostics", None),
            "v11_baseline_query_estimate": max(20, len(plan.steps) * 4),
            "queries_saved_vs_v11_baseline": max(
                0, max(20, len(plan.steps) * 4) - len(executed_queries)
            ),
        }
        return balanced

    @traced_tool('searcher.followup_search')
    def followup_search(
        self,
        plan: ResearchPlan,
        query_pairs: list[tuple[str, str, str]],
        *,
        exclude_urls: set[str] | None = None,
        start_source_id: int = 1,
    ) -> list[Source]:
        """Execute one bounded follow-up search phase (gap-driven)."""
        load_env()
        api_key = os.getenv("TAVILY_API_KEY", "").strip()
        if not api_key or not query_pairs:
            self.last_diagnostics = {
                **(self.last_diagnostics or {}),
                "followup_queries_executed": 0,
                "followup_mode": "skipped_no_key_or_queries",
            }
            return []

        depth_flag = "basic" if plan.depth != ResearchDepth.DEEP else "advanced"
        exclude = {_canonical_url(u) for u in (exclude_urls or set()) if u}
        sources: list[Source] = []
        executed: list[dict] = []
        next_id = start_source_id

        for task, query, profile in query_pairs:
            try:
                raw_results = self._tavily_request(
                    query=query,
                    api_key=api_key,
                    max_results=_PER_QUERY_MAX_RESULTS,
                    search_depth=depth_flag,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Follow-up search failed for %s: %s", query, exc)
                executed.append(
                    {
                        "research_task": task,
                        "query": query,
                        "freshness_profile": profile,
                        "raw_results": 0,
                        "unique_kept": 0,
                        "error": str(exc),
                    }
                )
                continue

            kept = 0
            for index, item in enumerate(raw_results):
                if not isinstance(item, dict):
                    continue
                source = _normalize_tavily_result(
                    item,
                    index,
                    search_query=query,
                    research_task=task,
                    freshness_profile=profile,
                )
                if source is None:
                    continue
                canon = _canonical_url(source.url)
                if not canon or canon in exclude:
                    continue
                exclude.add(canon)
                source.source_id = f"S{next_id}"
                source.is_followup = True
                source.query_role = "followup"
                next_id += 1
                sources.append(source)
                kept += 1

            executed.append(
                {
                    "research_task": task,
                    "query": query,
                    "freshness_profile": profile,
                    "raw_results": len(raw_results),
                    "unique_kept": kept,
                }
            )

        prev = dict(self.last_diagnostics or {})
        prev_calls = int(prev.get("tavily_search_calls") or prev.get("queries_executed") or 0)
        self.last_diagnostics = {
            **prev,
            "followup_queries_executed": len(executed),
            "followup_executed_query_details": executed,
            "followup_sources": len(sources),
            "tavily_search_calls": prev_calls + len(executed),
            "followup_mode": "tavily",
        }
        return sources

    def find_replacement_source(
        self,
        *,
        plan: ResearchPlan,
        failed_source: Source,
        exclude_urls: set[str] | None = None,
        next_source_id: str | None = None,
    ) -> tuple[Source | None, str]:
        """Cheap one-shot replacement search for a failed Reader source.

        Does not change the public ``search()`` interface. Prefer a different
        domain from ``failed_source``. Returns ``(source_or_None, query_used)``.
        """
        load_env()
        api_key = os.getenv("TAVILY_API_KEY", "").strip()
        query = _replacement_query(plan, failed_source)
        if not api_key:
            return None, query

        exclude = {_canonical_url(u) for u in (exclude_urls or set()) if u}
        exclude.add(_canonical_url(failed_source.url))
        failed_domain = domain_of(failed_source.url)
        depth_flag = "basic" if plan.depth != ResearchDepth.DEEP else "advanced"

        try:
            raw_results = self._tavily_request(
                query=query,
                api_key=api_key,
                max_results=_REPLACEMENT_MAX_RESULTS,
                search_depth=depth_flag,
            )
        except Exception as exc:  # noqa: BLE001 — replacement is best-effort
            logger.warning("Replacement search failed for %s: %s", failed_source.url, exc)
            return None, query

        profile = failed_source.freshness_profile or "CURRENT"
        task = failed_source.research_task or "unknown"
        same_domain_fallback: Source | None = None

        for index, item in enumerate(raw_results):
            if not isinstance(item, dict):
                continue
            candidate = _normalize_tavily_result(
                item,
                index,
                search_query=query,
                research_task=task,
                freshness_profile=profile,
            )
            if candidate is None:
                continue
            canon = _canonical_url(candidate.url)
            if not canon or canon in exclude:
                continue
            candidate.source_id = next_source_id
            if domain_of(candidate.url) == failed_domain:
                if same_domain_fallback is None:
                    same_domain_fallback = candidate
                continue
            return candidate, query

        # Prefer different domain; only fall back to same-domain if nothing else.
        if same_domain_fallback is not None:
            return same_domain_fallback, query
        return None, query

    def _tavily_request(
        self,
        *,
        query: str,
        api_key: str,
        max_results: int,
        search_depth: str,
    ) -> list[dict]:
        """Execute one Tavily search request and return raw result dicts."""
        payload = {
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
            "include_answer": False,
            "include_raw_content": False,
        }

        request = urllib.request.Request(
            TAVILY_SEARCH_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        try:
            data = request_json(request, timeout=TAVILY_TIMEOUT_SECONDS, opener=urllib.request.urlopen,
                                operation='tavily.search', kind='tool')
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"network error: {exc.reason}") from exc

        try:
            if not isinstance(data, dict):
                raise RuntimeError('invalid JSON response from Tavily')
        except json.JSONDecodeError as exc:
            raise RuntimeError("invalid JSON response from Tavily") from exc

        raw_results = data.get("results") or []
        return [item for item in raw_results if isinstance(item, dict)]


def search_sources(topic: str, depth: ResearchDepth) -> list[Source]:
    """Convenience wrapper: analyze, plan, then search."""
    from src.planner import Planner
    from src.query_analyzer import QueryAnalyzer

    analyzed = QueryAnalyzer().analyze(topic)
    plan = Planner().plan(analyzed, depth)
    return Searcher().search(plan)
