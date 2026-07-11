"""Searcher — discover candidate sources for a research plan.

Responsibility
--------------
Own *only* source discovery. Given a ``ResearchPlan``, execute the
Planner's per-task ``search_queries`` (via Tavily when configured) and
return normalized ``Source`` metadata.

Does not fetch full page content (Reader) or score quality
(EvidenceEvaluator). Falls back to mock sources if the API key is
missing or requests fail.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse, urlunparse

from src.env import load_env
from src.evidence_coverage import coverage_limits, search_candidate_limit
from src.models import ResearchDepth, ResearchPlan, Source

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_TIMEOUT_SECONDS = 30
# Per-query fetch size before cross-task balancing / capping.
_PER_QUERY_MAX_RESULTS = 4

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

    return Source(
        title=title,
        url=url,
        snippet=snippet or "No snippet available.",
        source_type=_infer_source_type(url),
        relevance=max(0.0, min(1.0, relevance)),
        published_date=published_date,
        search_query=search_query,
        research_task=research_task,
    )


def _collect_plan_queries(plan: ResearchPlan) -> list[tuple[str, str]]:
    """Collect (research_task, search_query) pairs from the plan steps."""
    pairs: list[tuple[str, str]] = []
    seen_queries: set[str] = set()

    for step in plan.steps:
        task = (step.title or f"Task {step.order}").strip()
        for raw in step.search_queries or []:
            query = str(raw).strip()
            if not query:
                continue
            key = query.lower()
            if key in seen_queries:
                continue
            seen_queries.add(key)
            pairs.append((task, query))

    return pairs


def _fallback_topic_query(plan: ResearchPlan) -> str:
    """Single topic query used only when the Planner provided no search_queries."""
    return f"{plan.topic} 中国 A股 产业链"


def _balance_sources_across_tasks(
    sources: list[Source],
    limit: int,
    *,
    per_task_target: int = 2,
) -> list[Source]:
    """Prefer coverage across research tasks, then fill by relevance.

    Takes up to ``per_task_target`` from each task in round-robin waves so
    one task cannot dominate the candidate pool before Reader/Evaluator.
    """
    if limit <= 0 or not sources:
        return []

    by_task: dict[str, list[Source]] = {}
    for source in sources:
        task = source.research_task or "unknown"
        by_task.setdefault(task, []).append(source)

    for task_sources in by_task.values():
        task_sources.sort(key=lambda s: s.relevance, reverse=True)

    selected: list[Source] = []
    selected_urls: set[str] = set()
    task_names = list(by_task.keys())
    per_task_taken: dict[str, int] = {t: 0 for t in task_names}
    max_per_task = max(per_task_target, min(per_task_target + 1, 3))

    # Wave 1..N: take one from each task until per_task_target or limit.
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
            key=lambda s: s.relevance,
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

    def search(self, plan: ResearchPlan) -> list[Source]:
        """Search using Planner ``search_queries`` when available.

        Tries Tavily when ``TAVILY_API_KEY`` is set; otherwise uses mocks.
        On API failure, falls back to mocks and sets ``last_warning``.
        """
        self.last_warning = None
        self.last_diagnostics = {}
        load_env()
        api_key = os.getenv("TAVILY_API_KEY", "").strip()

        if not api_key:
            self.last_warning = (
                "TAVILY_API_KEY is not configured. Using mock search results. "
                "Add the key to your .env file to enable live web search."
            )
            logger.info(self.last_warning)
            return self._mock_search(plan)

        try:
            sources = self._tavily_multi_query_search(plan, api_key)
            if not sources:
                self.last_warning = (
                    "Tavily returned no results. Falling back to mock search results."
                )
                logger.warning(self.last_warning)
                return self._mock_search(plan)
            return sources
        except Exception as exc:  # noqa: BLE001 — intentional graceful fallback
            self.last_warning = (
                f"Tavily search failed ({exc}). Falling back to mock search results."
            )
            logger.warning(self.last_warning)
            return self._mock_search(plan)

    def _mock_search(self, plan: ResearchPlan) -> list[Source]:
        """Return template-based mock sources (offline / fallback path)."""
        topic = plan.topic
        slug = _slugify(topic)
        count = plan.depth.source_count
        query_pairs = _collect_plan_queries(plan)
        sources: list[Source] = []

        for i, (title_tpl, url_tpl, snippet_tpl, source_type) in enumerate(
            SOURCE_TEMPLATES[:count]
        ):
            if query_pairs:
                task, query = query_pairs[i % len(query_pairs)]
            else:
                task, query = "Fallback", _fallback_topic_query(plan)
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
                )
            )

        self.last_diagnostics = {
            "planner_queries_generated": len(query_pairs),
            "queries_executed": 0,
            "executed_queries": [],
            "results_per_query": {},
            "unique_sources_after_dedupe": len(sources),
            "final_source_count": len(sources),
            "mode": "mock",
        }
        return sources

    def _tavily_multi_query_search(self, plan: ResearchPlan, api_key: str) -> list[Source]:
        """Execute each Planner search query via Tavily and balance coverage."""
        query_pairs = _collect_plan_queries(plan)
        used_fallback_topic_query = False

        if not query_pairs:
            used_fallback_topic_query = True
            query_pairs = [("Fallback topic query", _fallback_topic_query(plan))]

        depth_flag = "basic" if plan.depth != ResearchDepth.DEEP else "advanced"
        per_task_target, max_retained = coverage_limits(plan.depth)
        task_count = len(plan.steps) or 1
        target_total = search_candidate_limit(plan.depth, task_count)

        all_sources: list[Source] = []
        seen_urls: set[str] = set()
        results_per_query: dict[str, int] = {}
        executed_queries: list[dict[str, object]] = []

        for task, query in query_pairs:
            raw_results = self._tavily_request(
                query=query,
                api_key=api_key,
                max_results=_PER_QUERY_MAX_RESULTS,
                search_depth=depth_flag,
            )
            results_per_query[query] = len(raw_results)
            kept_for_query = 0

            for index, item in enumerate(raw_results):
                if not isinstance(item, dict):
                    continue
                source = _normalize_tavily_result(
                    item,
                    index,
                    search_query=query,
                    research_task=task,
                )
                if source is None:
                    continue
                canon = _canonical_url(source.url)
                if not canon or canon in seen_urls:
                    continue
                seen_urls.add(canon)
                all_sources.append(source)
                kept_for_query += 1

            executed_queries.append(
                {
                    "research_task": task,
                    "query": query,
                    "raw_results": len(raw_results),
                    "unique_kept": kept_for_query,
                }
            )

        balanced = _balance_sources_across_tasks(
            all_sources,
            target_total,
            per_task_target=per_task_target,
        )
        per_task_candidates = _per_task_candidate_counts(balanced)
        plan_tasks = [
            (step.title or f"Task {step.order}").strip() for step in plan.steps
        ]
        dropped_at_search = [
            t for t in plan_tasks if per_task_candidates.get(t, 0) == 0
        ]

        self.last_diagnostics = {
            "planner_queries_generated": 0
            if used_fallback_topic_query
            else len(query_pairs),
            "queries_executed": len(executed_queries),
            "executed_queries": [row["query"] for row in executed_queries],
            "executed_query_details": executed_queries,
            "results_per_query": results_per_query,
            "unique_sources_after_dedupe": len(all_sources),
            "final_source_count": len(balanced),
            "candidate_limit": target_total,
            "per_task_target": per_task_target,
            "max_retained_target": max_retained,
            "candidates_per_research_task": per_task_candidates,
            "dropped_tasks_at_search": dropped_at_search,
            "tasks_represented": sorted(
                {s.research_task for s in balanced if s.research_task}
            ),
            "used_fallback_topic_query": used_fallback_topic_query,
            "mode": "tavily_multi_query",
        }
        return balanced

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
            with urllib.request.urlopen(request, timeout=TAVILY_TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"network error: {exc.reason}") from exc

        try:
            data = json.loads(body)
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
