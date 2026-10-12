"""Research pipeline orchestrator.

Responsibility
--------------
Wire the research workflow end-to-end without owning domain logic:

    Query → Analyze → Plan → Search → Read → Evaluate → Synthesize → Write

Each step delegates to a single-responsibility component. This module is
the only place that knows the full stage order.

Future integration
------------------
When OpenAI and Search APIs are added, swap implementations inside each
component. The pipeline signature stays the same::

    result = run_research(topic, depth)

Optional ResearchState checkpoints (v1.3) can be enabled via keyword-only
``research_state`` / ``state_callback`` without changing the return type.
"""

from __future__ import annotations

from collections.abc import Callable

from src.domain_penalty import domain_of
from src.env import load_env
from src.observability import trace_scope
from src.verifier import verify_report
from src.evaluator import EvidenceEvaluator
from src.evidence_flow import build_evidence_flow_diagnostics
from src.models import EvidenceDocument, GroundedFinding, ResearchDepth, ResearchResult, Source
from src.planner import Planner
from src.query_analyzer import QueryAnalyzer
from src.reader import REPLACEABLE_EXTRACTION_STATUSES, Reader, build_reader_diagnostics
from src.research_state import ResearchState
from src.searcher import Searcher, _canonical_url
from src.synthesizer import Synthesizer
from src.writer import Writer

# Ensure project-root .env is loaded for all pipeline components.
load_env()

_MAX_REPLACEMENTS_PER_TASK = 2
_PERSIST_DIAG_KEY = "state_persistence"
_CB_ERROR_MAX_LEN = 240


def _truncate_callback_error(exc: Exception, *, max_len: int = _CB_ERROR_MAX_LEN) -> str:
    """Short safe message for persistence diagnostics (no traceback)."""
    text = f"{type(exc).__name__}: {exc}".replace("\r", " ").replace("\n", " ").strip()
    lower = text.lower()
    for marker in ("traceback (most recent call last)", "traceback:"):
        idx = lower.find(marker)
        if idx >= 0:
            text = text[:idx].strip()
            break
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text or type(exc).__name__


def _safe_state_checkpoint(
    state: ResearchState,
    callback: Callable[[ResearchState], None] | None,
    *,
    success_stage: str | None = None,
) -> None:
    """Invoke ``state_callback`` without letting persistence errors fail research."""
    if callback is None:
        return
    try:
        callback(state)
    except Exception as exc:  # noqa: BLE001 — persistence must not break research
        bucket = state.diagnostics.get(_PERSIST_DIAG_KEY)
        if not isinstance(bucket, dict):
            bucket = {}
            state.diagnostics[_PERSIST_DIAG_KEY] = bucket
        bucket["failure_count"] = int(bucket.get("failure_count") or 0) + 1
        bucket["last_error_type"] = type(exc).__name__
        bucket["last_error_message"] = _truncate_callback_error(exc)
        bucket["last_failed_stage"] = state.current_stage
        # Do not re-enter callback to persist this failure.
        return
    if success_stage:
        bucket = state.diagnostics.get(_PERSIST_DIAG_KEY)
        if not isinstance(bucket, dict):
            bucket = {}
            state.diagnostics[_PERSIST_DIAG_KEY] = bucket
        bucket["last_success_stage"] = success_stage


def _mark_stage(
    state: ResearchState,
    stage: str,
    callback: Callable[[ResearchState], None] | None,
) -> None:
    state.mark_running(stage)
    _safe_state_checkpoint(state, callback, success_stage=stage)


def _resolve_research_state(
    topic: str,
    depth: ResearchDepth,
    research_state: ResearchState | None,
) -> ResearchState:
    """Create or reuse ResearchState; sync topic/depth to the live call args."""
    if research_state is None:
        return ResearchState(topic=topic, depth=depth)
    # Usability: align caller-provided state with the actual invocation.
    if research_state.topic != topic or research_state.depth != depth:
        research_state.topic = topic
        research_state.depth = depth
        research_state.touch()
    return research_state


def run_research(
    topic: str,
    depth: ResearchDepth,
    *,
    research_state: ResearchState | None = None,
    state_callback: Callable[[ResearchState], None] | None = None,
    financial_payload: dict | None = None,
) -> ResearchResult:
    """Execute the full AI research workflow for a given topic.

    Pipeline stages:
        1. Analyze   — QueryAnalyzer
        2. Plan      — Planner
        3. Search    — Searcher
        4. Read      — Reader (+ cheap replacement for replaceable failures)
        5. Evaluate  — EvidenceEvaluator
        6. Synthesize — Synthesizer
        7. Write     — Writer

    Optional keyword-only ``research_state`` / ``state_callback`` enable
    in-memory checkpoints. Persistence is caller-owned (pipeline never opens
    SQLite). Callback failures are recorded under
    ``state.diagnostics['state_persistence']`` and do not fail the run.

    Args:
        topic: The industry, company, or technology topic to research.
        depth: How thorough the research should be.
        research_state: Optional existing run state to mutate in place.
        state_callback: Optional checkpoint hook (e.g. repository.save_state).

    Returns:
        A ResearchResult containing analyzed query, plan, sources, evidence, and report.

    Raises:
        ValueError: If topic is empty or whitespace-only.
    """
    load_env()
    state = _resolve_research_state(topic, depth, research_state)

    try:
        with trace_scope(state):
            return _run_research_with_state(topic, depth, state, state_callback, financial_payload)
    except Exception as exc:
        # Capture failed stage, checkpoint once, then re-raise the business error.
        fail_stage = state.current_stage or "failed"
        state.mark_failed(str(exc), stage=fail_stage)
        _safe_state_checkpoint(state, state_callback)
        raise


def _run_research_with_state(
    topic: str,
    depth: ResearchDepth,
    state: ResearchState,
    state_callback: Callable[[ResearchState], None] | None,
    financial_payload: dict | None = None,
) -> ResearchResult:
    _safe_state_checkpoint(state, state_callback, success_stage=state.current_stage)

    _mark_stage(state, "analyzing", state_callback)
    analyzed = QueryAnalyzer().analyze(topic)
    state.analyzed_query = analyzed
    _safe_state_checkpoint(state, state_callback, success_stage="analyzing")

    _mark_stage(state, "planning", state_callback)
    planner = Planner()
    plan = planner.plan(analyzed, depth)
    state.plan = plan
    if getattr(plan, "evidence_strategy_diagnostics", None) is not None:
        state.diagnostics["evidence_strategy"] = dict(plan.evidence_strategy_diagnostics)
    _safe_state_checkpoint(state, state_callback, success_stage="planning")

    _mark_stage(state, "searching", state_callback)
    searcher = Searcher()
    sources = searcher.search(plan)
    state.sources = list(sources)
    if searcher.last_diagnostics:
        state.diagnostics["search"] = dict(searcher.last_diagnostics)
    _safe_state_checkpoint(state, state_callback, success_stage="searching")

    _mark_stage(state, "reading", state_callback)
    reader = Reader()
    documents = reader.read(sources)
    state.documents = list(documents)
    _safe_state_checkpoint(state, state_callback, success_stage="reading")

    needs_replace = any(
        (doc.extraction_status or "").upper() in REPLACEABLE_EXTRACTION_STATUSES
        for doc in documents
    )
    if needs_replace:
        _mark_stage(state, "replacing_sources", state_callback)
    documents, sources, replacement_diag = _apply_reader_replacements(
        plan=plan,
        searcher=searcher,
        reader=reader,
        sources=sources,
        documents=documents,
    )
    # Merge replacement + PDF counters into final reader diagnostics.
    base_diag = dict(reader.last_diagnostics or {})
    funnel = dict(base_diag.get("funnel") or {})
    # Rebuild funnel after replacements so rates reflect final documents.
    rebuilt = build_reader_diagnostics(
        documents,
        pdf_attempts=int(funnel.get("pdf_extraction_attempts") or 0)
        + int((replacement_diag.get("pdf_attempts_delta") or 0)),
        pdf_successes=int(funnel.get("pdf_extraction_successes") or 0)
        + int((replacement_diag.get("pdf_successes_delta") or 0)),
        domain_extract_used=int(funnel.get("domain_specific_extract_used") or 0)
        + int((replacement_diag.get("domain_extract_delta") or 0)),
        replacement=replacement_diag,
    )
    reader.last_diagnostics = rebuilt
    state.documents = list(documents)
    state.sources = list(sources)
    state.diagnostics["reader"] = dict(reader.last_diagnostics or {})
    if needs_replace:
        _safe_state_checkpoint(state, state_callback, success_stage="replacing_sources")

    _mark_stage(state, "evaluating", state_callback)
    if financial_payload is not None:
        from src.financial_analysis import attach_financial_analysis, bind_financial_tasks
        attach_financial_analysis(state, financial_payload)
        bind_financial_tasks(state)
        sources, documents = list(state.sources), list(state.documents)
    evaluator = EvidenceEvaluator()
    evidence = evaluator.evaluate(documents, plan)
    state.evidence = list(evidence)
    from src.research_reasoning import reflect_plan, update_hypotheses, build_evidence_graph, critic_review
    reflect_plan(state)
    if evaluator.last_diagnostics:
        state.diagnostics["evaluator"] = dict(evaluator.last_diagnostics)
    _safe_state_checkpoint(state, state_callback, success_stage="evaluating")

    # v1.2: deterministic coverage check + one bounded follow-up search phase.
    from src.evidence_strategy import (
        assess_evidence_coverage,
        build_followup_queries,
        coverage_to_dicts,
    )
    from src.synthesizer import CONTENT_SECTIONS

    _mark_stage(state, "checking_coverage", state_callback)
    coverage_before = assess_evidence_coverage(plan, evidence)
    state.coverage_before = list(coverage_before)
    followup_pairs = build_followup_queries(plan, coverage_before)
    followup_sources: list[Source] = []
    gaps_before = sum(1 for c in coverage_before if c.followup_needed)
    state.diagnostics["coverage"] = {
        "before_followup": coverage_to_dicts(coverage_before),
        "followup_queries": [
            {"research_task": t, "query": q, "freshness_profile": p}
            for t, q, p in followup_pairs
        ],
        "gaps_before": gaps_before,
    }
    _safe_state_checkpoint(state, state_callback, success_stage="checking_coverage")

    initial_mode = str((searcher.last_diagnostics or {}).get("mode") or "")
    allow_followup = followup_pairs and "mock" not in initial_mode.lower() and initial_mode != 'unavailable'

    if allow_followup:
        _mark_stage(state, "followup_searching", state_callback)
        exclude = {_canonical_url(s.url) for s in sources}
        start_id = len(sources) + 1
        followup_sources = searcher.followup_search(
            plan,
            followup_pairs,
            exclude_urls=exclude,
            start_source_id=start_id,
        )
        state.diagnostics["search"] = dict(searcher.last_diagnostics or {})
        _safe_state_checkpoint(state, state_callback, success_stage="followup_searching")

        if followup_sources:
            _mark_stage(state, "followup_reading", state_callback)
            followup_docs = reader.read(followup_sources)
            # Do not recursively replace follow-up failures (keeps cost bounded).
            documents = list(documents) + list(followup_docs)
            sources = list(sources) + list(followup_sources)
            # Rebuild reader diagnostics over the merged set.
            reader.last_diagnostics = build_reader_diagnostics(
                documents,
                pdf_attempts=int(
                    ((reader.last_diagnostics or {}).get("funnel") or {}).get(
                        "pdf_extraction_attempts"
                    )
                    or 0
                ),
                pdf_successes=int(
                    ((reader.last_diagnostics or {}).get("funnel") or {}).get(
                        "pdf_extraction_successes"
                    )
                    or 0
                ),
                domain_extract_used=int(
                    ((reader.last_diagnostics or {}).get("funnel") or {}).get(
                        "domain_specific_extract_used"
                    )
                    or 0
                ),
                replacement=(reader.last_diagnostics or {}).get("replacement"),
            )
            state.documents = list(documents)
            state.sources = list(sources)
            state.diagnostics["reader"] = dict(reader.last_diagnostics or {})
            _safe_state_checkpoint(state, state_callback, success_stage="followup_reading")

            _mark_stage(state, "followup_evaluating", state_callback)
            evidence = evaluator.evaluate(documents, plan)
            state.evidence = list(evidence)
            if evaluator.last_diagnostics:
                state.diagnostics["evaluator"] = dict(evaluator.last_diagnostics)
            _safe_state_checkpoint(
                state, state_callback, success_stage="followup_evaluating"
            )

    coverage_after = assess_evidence_coverage(plan, evidence)
    gaps_after = sum(1 for c in coverage_after if c.followup_needed)
    state.coverage_after = list(coverage_after)
    cov_diag = dict(state.diagnostics.get("coverage") or {})
    cov_diag["after_followup"] = coverage_to_dicts(coverage_after)
    cov_diag["gaps_after"] = gaps_after
    state.diagnostics["coverage"] = cov_diag
    _safe_state_checkpoint(state, state_callback, success_stage="checking_coverage")

    if not any(item.keep for item in evidence):
        raise ValueError('没有获得可用证据，研究未完成；未生成模拟报告。')

    _mark_stage(state, "synthesizing", state_callback)
    synthesizer = Synthesizer()
    synthesis = synthesizer.synthesize(plan, evidence)
    _ensure_time_sensitive_evidence_gaps(plan, evidence, synthesis)
    state.synthesis = synthesis
    update_hypotheses(state)
    build_evidence_graph(state)
    if synthesizer.last_diagnostics:
        state.diagnostics["synthesizer"] = dict(synthesizer.last_diagnostics)
    _safe_state_checkpoint(state, state_callback, success_stage="synthesizing")

    from src.research_health import assess_research_health

    _mark_stage(state, "assessing_health", state_callback)
    coverage_for_health = coverage_to_dicts(coverage_after)
    research_health = assess_research_health(
        plan=plan,
        evidence=evidence,
        synthesis=synthesis,
        coverage_results=coverage_for_health,
    )
    state.research_health = research_health
    _safe_state_checkpoint(state, state_callback, success_stage="assessing_health")

    _mark_stage(state, "writing", state_callback)
    writer = Writer()
    report = writer.write(plan, synthesis, research_health=research_health)
    state.report = report
    state.diagnostics['verification'] = verify_report(report, synthesis)
    critic_review(state)
    if not state.diagnostics['verification']['passed']:
        state.report = None
        raise ValueError('报告引用或数值校验失败，证据已保留。')
    if writer.last_diagnostics:
        state.diagnostics["writer"] = dict(writer.last_diagnostics)
    _safe_state_checkpoint(state, state_callback, success_stage="writing")

    search_diag = dict(searcher.last_diagnostics or {})
    findings_count = 0
    if synthesis is not None:
        for key in CONTENT_SECTIONS:
            for finding in getattr(synthesis, key) or []:
                if finding.finding_type != "gap":
                    findings_count += 1
    tavily_calls = int(
        search_diag.get("tavily_search_calls")
        or search_diag.get("queries_executed")
        or 0
    )
    # Include Reader replacement Tavily calls if recorded separately (best-effort).
    efficiency = {
        "planner_candidate_queries_generated": int(
            (getattr(plan, "evidence_strategy_diagnostics", None) or {}).get(
                "initial_queries_selected"
            )
            or search_diag.get("planner_queries_generated")
            or 0
        ),
        "initial_queries_executed": int(
            search_diag.get("initial_queries_executed")
            or search_diag.get("queries_executed")
            or 0
        ),
        "followup_queries_executed": int(search_diag.get("followup_queries_executed") or 0),
        "total_search_queries": tavily_calls,
        "tavily_search_calls": tavily_calls,
        "queries_saved_vs_v11_baseline": int(
            search_diag.get("queries_saved_vs_v11_baseline") or 0
        ),
        "v11_baseline_query_estimate": int(
            search_diag.get("v11_baseline_query_estimate") or 20
        ),
        "grounded_findings": findings_count,
        "grounded_findings_per_search_call": round(
            findings_count / max(tavily_calls, 1), 3
        ),
        "evidence_gaps_before_followup": gaps_before,
        "evidence_gaps_after_followup": gaps_after,
        "followup_sources_added": len(followup_sources),
        "coverage_before": coverage_to_dicts(coverage_before),
        "coverage_after": coverage_to_dicts(coverage_after),
    }
    state.diagnostics["search_efficiency"] = efficiency

    state.mark_completed()
    from src.research_memory import finalize_research_memory
    finalize_research_memory(state)
    _safe_state_checkpoint(state, state_callback, success_stage="completed")

    result = ResearchResult(
        plan=plan,
        sources=sources,
        report=report,
        analyzed_query=analyzed,
        documents=documents,
        evidence=evidence,
        synthesis=synthesis,
        research_health=research_health,
        search_warning=searcher.last_warning,
        planner_warning=planner.last_warning,
        search_diagnostics=search_diag or None,
        synthesizer_warning=synthesizer.last_warning,
        synthesizer_diagnostics=synthesizer.last_diagnostics or None,
        writer_warning=writer.last_warning,
        writer_diagnostics=writer.last_diagnostics or None,
        evaluator_diagnostics=evaluator.last_diagnostics or None,
        reader_diagnostics=reader.last_diagnostics or None,
        evidence_strategy_diagnostics=getattr(plan, "evidence_strategy_diagnostics", None),
        coverage_diagnostics={
            "before_followup": coverage_to_dicts(coverage_before),
            "after_followup": coverage_to_dicts(coverage_after),
            "followup_queries": [
                {"research_task": t, "query": q, "freshness_profile": p}
                for t, q, p in followup_pairs
            ],
            "gaps_before": gaps_before,
            "gaps_after": gaps_after,
        },
        search_efficiency_diagnostics=efficiency,
    )
    result.evidence_flow_diagnostics = build_evidence_flow_diagnostics(result)
    state.diagnostics["evidence_flow"] = result.evidence_flow_diagnostics
    return result


def _apply_reader_replacements(
    *,
    plan,
    searcher: Searcher,
    reader: Reader,
    sources: list[Source],
    documents: list[EvidenceDocument],
) -> tuple[list[EvidenceDocument], list[Source], dict]:
    """Replace up to N replaceable Reader failures per task (no recursion)."""
    attempts: list[dict] = []
    per_task_used: dict[str, int] = {}
    # Original failures only — never replace a replacement source.
    replaceable_indexes: list[int] = []
    for idx, doc in enumerate(documents):
        status = (doc.extraction_status or "").upper()
        if status in REPLACEABLE_EXTRACTION_STATUSES:
            replaceable_indexes.append(idx)

    exclude_urls = {_canonical_url(s.url) for s in sources}
    next_id_num = len(sources) + 1
    pdf_before = getattr(reader, "_pdf_attempts", 0)
    pdf_ok_before = getattr(reader, "_pdf_successes", 0)
    domain_before = getattr(reader, "_domain_extract_used", 0)

    for idx in replaceable_indexes:
        doc = documents[idx]
        source = doc.source
        task = (source.research_task or "unknown").strip() or "unknown"
        if per_task_used.get(task, 0) >= _MAX_REPLACEMENTS_PER_TASK:
            attempts.append(
                {
                    "original_source_id": source.source_id,
                    "original_url": source.url,
                    "research_task": task,
                    "failure_status": doc.extraction_status,
                    "failure_reason": doc.error_message,
                    "replacement_query": None,
                    "replacement_source_id": None,
                    "replacement_url": None,
                    "success": False,
                    "skipped_reason": "per_task_limit",
                }
            )
            continue

        replacement_id = f"S{next_id_num}"
        replacement, query = searcher.find_replacement_source(
            plan=plan,
            failed_source=source,
            exclude_urls=exclude_urls,
            next_source_id=replacement_id,
        )
        if replacement is None:
            attempts.append(
                {
                    "original_source_id": source.source_id,
                    "original_url": source.url,
                    "research_task": task,
                    "failure_status": doc.extraction_status,
                    "failure_reason": doc.error_message,
                    "replacement_query": query,
                    "replacement_source_id": None,
                    "replacement_url": None,
                    "success": False,
                    "skipped_reason": "no_candidate",
                }
            )
            continue

        # Mark so we never recursively replace this source.
        setattr(replacement, "_rp_is_replacement", True)
        exclude_urls.add(_canonical_url(replacement.url))
        next_id_num += 1
        per_task_used[task] = per_task_used.get(task, 0) + 1

        # One read attempt only — failure stays as snippet fallback on replacement.
        new_doc = reader._read_one(replacement)
        success = (
            new_doc.read_status == "success"
            and (new_doc.extraction_status or "").upper()
            in {"FULL_TEXT", "PARTIAL_TEXT"}
        )
        attempts.append(
            {
                "original_source_id": source.source_id,
                "original_url": source.url,
                "research_task": task,
                "failure_status": doc.extraction_status,
                "failure_reason": doc.error_message,
                "replacement_query": query,
                "replacement_source_id": replacement.source_id,
                "replacement_url": replacement.url,
                "replacement_domain": domain_of(replacement.url),
                "replacement_extraction_status": new_doc.extraction_status,
                "success": success,
                "skipped_reason": None if success else "replacement_read_failed",
            }
        )
        if success:
            documents[idx] = new_doc
            sources[idx] = replacement

    successes = sum(1 for a in attempts if a.get("success"))
    diag = {
        "attempts": attempts,
        "attempt_count": len(attempts),
        "success_count": successes,
        "success_rate_pct": round(100.0 * successes / max(len(attempts), 1), 1)
        if attempts
        else 0.0,
        "per_task_used": dict(per_task_used),
        "max_per_task": _MAX_REPLACEMENTS_PER_TASK,
        "pdf_attempts_delta": max(
            0, getattr(reader, "_pdf_attempts", 0) - pdf_before
        ),
        "pdf_successes_delta": max(
            0, getattr(reader, "_pdf_successes", 0) - pdf_ok_before
        ),
        "domain_extract_delta": max(
            0, getattr(reader, "_domain_extract_used", 0) - domain_before
        ),
        "failure_reasons_after_replacement": _failure_reasons_after(documents),
    }
    return documents, sources, diag

def _failure_reasons_after(documents: list[EvidenceDocument]) -> list[dict]:
    from collections import Counter

    counts: Counter[str] = Counter()
    for doc in documents:
        if doc.snippet_fallback or doc.read_status != "success":
            counts[doc.error_message or doc.extraction_status or "unknown"] += 1
    return [
        {"reason": reason, "count": count}
        for reason, count in counts.most_common(12)
    ]

def _ensure_time_sensitive_evidence_gaps(plan, evidence, synthesis) -> None:
    """If hot-topic retention lacks recent catalyst evidence, record an explicit gap.

    Does not invent facts or change Synthesizer/Writer logic — only appends a
    ``finding_type=gap`` note when recent BREAKING/RECENT evidence is insufficient.
    """
    if synthesis is None or not bool(getattr(plan, "time_sensitive", False)):
        return

    # Age-first: young retained sources count as catalysts even if Planner
    # labeled the task STRUCTURAL.
    recent_kept = [
        e
        for e in evidence
        if e.keep
        and (
            (e.age_days is not None and e.age_days <= 90)
            or (
                e.age_days is None
                and (e.freshness_profile or "").upper() in {"BREAKING", "RECENT"}
                and e.freshness_score >= 70
            )
        )
    ]
    if len(recent_kept) >= 2:
        return

    gap_text = "未检索到足够的近期催化证据"
    existing = [g.finding for g in (synthesis.evidence_gaps or [])]
    if any(gap_text in (t or "") for t in existing):
        return
    synthesis.evidence_gaps.append(
        GroundedFinding(
            finding=gap_text,
            evidence_ids=[],
            finding_type="gap",
            supporting_excerpts=[],
        )
    )
    # Refresh legacy findings markdown if present.
    if hasattr(synthesis, "findings") and synthesis.findings is not None:
        from src.synthesizer import _legacy_findings_from_structured

        synthesis.findings = _legacy_findings_from_structured(synthesis)
