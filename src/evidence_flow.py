"""Evidence-flow diagnostics — locate where sources are dropped.

Read-only analysis over pipeline outputs. Does not change ranking, retention,
or synthesis behavior.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import asdict
from typing import Any

from src.models import ResearchResult
from src.synthesizer import CONTENT_SECTIONS, STRUCTURED_SECTIONS

_TABLE_COLUMNS = (
    "Research Task",
    "Planner Queries",
    "Search Results",
    "Unique",
    "Read",
    "Fallback",
    "Evaluated",
    "Pass Threshold",
    "Retained",
    "Sent to Synthesizer",
    "Findings",
)


def build_evidence_flow_diagnostics(result: ResearchResult) -> dict[str, Any]:
    """Aggregate per-task funnel metrics and drop-off reasons."""
    plan = result.plan
    search = result.search_diagnostics or {}
    evaluator = result.evaluator_diagnostics or {}
    synth = result.synthesizer_diagnostics or {}

    plan_tasks = [
        (step.title or f"Task {step.order}").strip() for step in plan.steps
    ]
    # Preserve plan order; append any unexpected task labels seen downstream.
    task_order: list[str] = []
    for name in plan_tasks:
        if name and name not in task_order:
            task_order.append(name)

    def _ensure_task(name: str) -> str:
        label = (name or "unknown").strip() or "unknown"
        if label not in task_order:
            task_order.append(label)
        return label

    # Planner queries per task
    planner_queries: dict[str, int] = {t: 0 for t in task_order}
    for step in plan.steps:
        task = _ensure_task(step.title or f"Task {step.order}")
        planner_queries[task] = len(step.search_queries or [])

    raw_per_task = dict(search.get("raw_results_per_research_task") or {})
    unique_before = dict(search.get("unique_per_research_task_before_balance") or {})
    # Fallback: derive from executed_query_details if older diagnostics shape.
    if not raw_per_task:
        for row in search.get("executed_query_details") or []:
            task = _ensure_task(str(row.get("research_task") or "unknown"))
            raw_per_task[task] = raw_per_task.get(task, 0) + int(row.get("raw_results") or 0)
            unique_before[task] = unique_before.get(task, 0) + int(row.get("unique_kept") or 0)

    for task in list(raw_per_task) + list(unique_before):
        _ensure_task(task)

    # Reader outcomes among Searcher-final sources (documents aligned to sources).
    read_ok: dict[str, int] = Counter()
    fallback: dict[str, int] = Counter()
    for doc in result.documents or []:
        task = _ensure_task(doc.source.research_task or "unknown")
        if doc.read_status == "success":
            read_ok[task] += 1
        else:
            fallback[task] += 1

    # Evaluator funnel
    evaluated_per_task: dict[str, int] = Counter()
    pass_threshold_per_task: dict[str, int] = Counter()
    retained_per_task: dict[str, int] = Counter()
    keep_threshold = int(evaluator.get("keep_threshold") or 45)

    for item in result.evidence or []:
        task = _ensure_task(item.source.research_task or "unknown")
        evaluated_per_task[task] += 1
        if item.final_score >= keep_threshold:
            pass_threshold_per_task[task] += 1
        if item.keep:
            retained_per_task[task] += 1

    # Prefer evaluator retained counts when present (should match keep flags).
    for task, count in (evaluator.get("retained_sources_per_research_task") or {}).items():
        retained_per_task[_ensure_task(task)] = int(count)

    sent_per_task = Counter()
    for task, count in (synth.get("sent_per_research_task") or {}).items():
        sent_per_task[_ensure_task(task)] = int(count)

    # If synthesizer map missing, reconstruct from evidence_index.
    if not sent_per_task and result.synthesis and result.synthesis.evidence_index:
        for item in result.synthesis.evidence_index.values():
            sent_per_task[_ensure_task(item.source.research_task or "unknown")] += 1

    findings_per_task = Counter()
    for task, count in (synth.get("findings_per_research_task") or {}).items():
        findings_per_task[_ensure_task(task)] = int(count)

    if not findings_per_task and result.synthesis:
        id_to_task = {}
        for eid, item in (result.synthesis.evidence_index or {}).items():
            id_to_task[eid] = _ensure_task(item.source.research_task or "unknown")
        for key in STRUCTURED_SECTIONS:
            for finding in getattr(result.synthesis, key) or []:
                if key == "evidence_gaps" or finding.finding_type == "gap":
                    continue
                tasks_hit = {
                    id_to_task[eid]
                    for eid in (finding.evidence_ids or [])
                    if eid in id_to_task
                }
                for task in tasks_hit or set():
                    findings_per_task[task] += 1

    rows: list[dict[str, Any]] = []
    for task in task_order:
        rows.append(
            {
                "research_task": task,
                "planner_queries": planner_queries.get(task, 0),
                "search_results": int(raw_per_task.get(task, 0)),
                "unique": int(unique_before.get(task, 0)),
                "read": int(read_ok.get(task, 0)),
                "fallback": int(fallback.get(task, 0)),
                "evaluated": int(evaluated_per_task.get(task, 0)),
                "pass_threshold": int(pass_threshold_per_task.get(task, 0)),
                "retained": int(retained_per_task.get(task, 0)),
                "sent_to_synthesizer": int(sent_per_task.get(task, 0)),
                "findings": int(findings_per_task.get(task, 0)),
            }
        )

    drop_off = _aggregate_drop_off_reasons(result, rows)
    summary = _build_loss_summary(drop_off)
    reader_yield = _build_reader_evidence_yield(result)

    # Keep reader_diagnostics self-contained for diagnose_reader.py.
    if result.reader_diagnostics is not None:
        result.reader_diagnostics = {
            **result.reader_diagnostics,
            "evidence_yield": reader_yield,
        }

    # Traceability: S# → E#
    id_trace = []
    for eid, meta in (synth.get("evidence_id_map") or {}).items():
        id_trace.append(
            {
                "evidence_id": eid,
                "source_id": meta.get("source_id"),
                "research_task": meta.get("research_task"),
                "url": meta.get("url"),
                "read_status": meta.get("read_status"),
                "final_score": meta.get("final_score"),
                "findings_using": (synth.get("findings_per_evidence_id") or {}).get(eid, 0),
            }
        )
    if not id_trace and result.synthesis:
        for eid, item in (result.synthesis.evidence_index or {}).items():
            id_trace.append(
                {
                    "evidence_id": eid,
                    "source_id": item.source.source_id,
                    "research_task": item.source.research_task,
                    "url": item.source.url,
                    "read_status": item.document.read_status,
                    "final_score": item.final_score,
                    "findings_using": 0,
                }
            )

    return {
        "topic": plan.topic,
        "depth": plan.depth.value,
        "table_columns": list(_TABLE_COLUMNS),
        "per_task_rows": rows,
        "drop_off_reasons": drop_off,
        "loss_summary": summary,
        "totals": {
            "planner_queries": sum(r["planner_queries"] for r in rows),
            "search_results": sum(r["search_results"] for r in rows),
            "unique": sum(r["unique"] for r in rows),
            "read": sum(r["read"] for r in rows),
            "fallback": sum(r["fallback"] for r in rows),
            "evaluated": sum(r["evaluated"] for r in rows),
            "pass_threshold": sum(r["pass_threshold"] for r in rows),
            "retained": sum(r["retained"] for r in rows),
            "sent_to_synthesizer": sum(r["sent_to_synthesizer"] for r in rows),
            "findings": sum(r["findings"] for r in rows),
            "content_findings": sum(
                len(getattr(result.synthesis, key) or [])
                for key in CONTENT_SECTIONS
            )
            if result.synthesis
            else 0,
            "evidence_gaps": len(result.synthesis.evidence_gaps) if result.synthesis else 0,
        },
        "evaluator_diagnostics": evaluator,
        "reader_diagnostics": result.reader_diagnostics,
        "reader_evidence_yield": reader_yield,
        "reader_reliability": {
            "domain_penalties_applied_count": int(
                (result.search_diagnostics or {}).get(
                    "domain_penalties_applied_count"
                )
                or 0
            ),
            "domain_penalties_demoted_out_count": int(
                (result.search_diagnostics or {}).get(
                    "domain_penalties_demoted_out_count"
                )
                or 0
            ),
            "domain_penalties_applied": (
                (result.search_diagnostics or {}).get("domain_penalties_applied")
                or []
            ),
            "replacement": (result.reader_diagnostics or {}).get("replacement")
            or {},
            "pdf_extraction_attempts": (
                ((result.reader_diagnostics or {}).get("funnel") or {}).get(
                    "pdf_extraction_attempts"
                )
            ),
            "pdf_extraction_successes": (
                ((result.reader_diagnostics or {}).get("funnel") or {}).get(
                    "pdf_extraction_successes"
                )
            ),
            "pdf_extraction_success_rate_pct": (
                ((result.reader_diagnostics or {}).get("funnel") or {}).get(
                    "pdf_extraction_success_rate_pct"
                )
            ),
            "full_partial_rate_pct": (
                ((result.reader_diagnostics or {}).get("funnel") or {}).get(
                    "full_partial_rate_pct"
                )
            ),
            "fallback_rate_pct": (
                ((result.reader_diagnostics or {}).get("funnel") or {}).get(
                    "fallback_rate_pct"
                )
            ),
            "failure_reasons_after_replacement": (
                ((result.reader_diagnostics or {}).get("replacement") or {}).get(
                    "failure_reasons_after_replacement"
                )
                or []
            ),
        },
        "evidence_strategy": result.evidence_strategy_diagnostics
        or getattr(result.plan, "evidence_strategy_diagnostics", None),
        "coverage": result.coverage_diagnostics,
        "search_efficiency": result.search_efficiency_diagnostics,
        "research_health": (
            asdict(result.research_health)
            if result.research_health is not None
            else None
        ),
        "id_trace": id_trace,
        "freshness": {
            "time_sensitive": bool(getattr(plan, "time_sensitive", False)),
            "task_profiles": {
                (step.title or f"Task {step.order}").strip(): (
                    getattr(step, "freshness_profile", None) or "CURRENT"
                )
                for step in plan.steps
            },
            "retained_age_buckets": (evaluator.get("retained_age_buckets") or {}),
            "retained_freshness_profiles": (
                evaluator.get("retained_freshness_profiles") or {}
            ),
            "retained_source_dates": evaluator.get("retained_source_dates") or [],
            "breaking_recent_pct": evaluator.get("breaking_recent_pct"),
            "breaking_recent_total": evaluator.get("breaking_recent_total"),
            "structural_background": evaluator.get("structural_background"),
            "retention_mode": evaluator.get("retention_mode"),
            "recent_catalyst_insufficient": evaluator.get(
                "recent_catalyst_insufficient"
            ),
            "allocation_counts": evaluator.get("allocation_counts"),
            "allocation_roles": evaluator.get("allocation_roles"),
            "allocation_budgets": evaluator.get("allocation_budgets"),
            "retained_planner_profiles": evaluator.get("retained_planner_profiles"),
        },
        "stage_snapshots": {
            "search": {
                "raw_results_total": search.get("raw_results_total"),
                "duplicate_url_dropped": search.get("duplicate_url_dropped"),
                "unique_sources_after_dedupe": search.get("unique_sources_after_dedupe"),
                "dropped_by_candidate_limit": search.get("dropped_by_candidate_limit"),
                "final_source_count": search.get("final_source_count"),
                "candidate_limit": search.get("candidate_limit"),
            },
            "evaluator": {
                "evaluated_total": evaluator.get("evaluated_total"),
                "passing_score_threshold": evaluator.get("passing_score_threshold"),
                "retained_total": evaluator.get("retained_total"),
                "max_total": evaluator.get("max_total"),
                "max_per_task": evaluator.get("max_per_task"),
                "drop_reasons": evaluator.get("drop_reasons"),
            },
            "synthesizer": {
                "evidence_items_sent": synth.get("evidence_items_sent"),
                "truncated_by_max_evidence_items": synth.get("truncated_by_max_evidence_items"),
                "unused_evidence_ids": synth.get("unused_evidence_ids"),
                "generated_findings": synth.get("generated_findings"),
            },
        },
    }


def format_evidence_flow_table(diag: dict[str, Any]) -> str:
    """Render a markdown table from evidence-flow diagnostics."""
    rows = diag.get("per_task_rows") or []
    headers = [
        "Research Task",
        "Search Results",
        "Unique",
        "Read",
        "Fallback",
        "Evaluated",
        "Retained",
        "Sent to Synthesizer",
        "Findings",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] + ["---:"] * (len(headers) - 1)) + "|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["research_task"]),
                    str(row["search_results"]),
                    str(row["unique"]),
                    str(row["read"]),
                    str(row["fallback"]),
                    str(row["evaluated"]),
                    str(row["retained"]),
                    str(row["sent_to_synthesizer"]),
                    str(row["findings"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def format_evidence_flow_report(diag: dict[str, Any]) -> str:
    """Human-readable full diagnostic report."""
    parts = [
        f"# Evidence flow diagnostic — {diag.get('topic')} ({diag.get('depth')})",
        "",
        format_evidence_flow_table(diag),
        "",
        "## Totals",
    ]
    totals = diag.get("totals") or {}
    for key in (
        "search_results",
        "unique",
        "read",
        "fallback",
        "evaluated",
        "pass_threshold",
        "retained",
        "sent_to_synthesizer",
        "findings",
        "content_findings",
        "evidence_gaps",
    ):
        if key in totals:
            parts.append(f"- {key}: {totals[key]}")

    parts.extend(["", "## Top drop-off reasons"])
    for reason, count in (diag.get("drop_off_reasons") or []):
        parts.append(f"- {reason}: {count}")

    parts.extend(["", "## Loss summary", diag.get("loss_summary") or "(none)", ""])

    freshness = diag.get("freshness") or {}
    parts.append("## Freshness")
    parts.append(f"- time_sensitive: {freshness.get('time_sensitive')}")
    parts.append(f"- retention_mode: {freshness.get('retention_mode')}")
    parts.append(
        f"- BREAKING+RECENT: {freshness.get('breaking_recent_total')} "
        f"({freshness.get('breaking_recent_pct')}%)"
    )
    parts.append(f"- STRUCTURAL background: {freshness.get('structural_background')}")
    parts.append(
        f"- recent_catalyst_insufficient: {freshness.get('recent_catalyst_insufficient')}"
    )
    parts.append("- task profiles:")
    for task, profile in (freshness.get("task_profiles") or {}).items():
        parts.append(f"  - {task}: {profile}")
    parts.append("- retained age buckets:")
    for bucket, count in (freshness.get("retained_age_buckets") or {}).items():
        parts.append(f"  - {bucket}: {count}")
    parts.append("- retained freshness profiles:")
    for profile, count in (freshness.get("retained_freshness_profiles") or {}).items():
        parts.append(f"  - {profile}: {count}")
    for row in freshness.get("retained_source_dates") or []:
        parts.append(
            f"  - {row.get('source_id')} · {row.get('research_task')} · "
            f"profile={row.get('freshness_profile')} · age={row.get('age_days')} · "
            f"bucket={row.get('age_bucket')} · freshness={row.get('freshness_score')} · "
            f"date={row.get('published_at') or 'unknown'} ({row.get('date_confidence')})"
        )

    yield_block = diag.get("reader_evidence_yield") or {}
    if yield_block:
        parts.extend(["", "## Reader evidence yield"])
        for key, value in yield_block.items():
            parts.append(f"- {key}: {value}")

    parts.append("")
    parts.append("## ID trace (S# → E#)")
    for row in diag.get("id_trace") or []:
        parts.append(
            f"- {row.get('source_id') or '?'} → {row.get('evidence_id')} · "
            f"task=`{row.get('research_task')}` · findings={row.get('findings_using')} · "
            f"read={row.get('read_status')} · score={row.get('final_score')}"
        )
    return "\n".join(parts)


def _aggregate_drop_off_reasons(
    result: ResearchResult,
    rows: list[dict[str, Any]],
) -> list[tuple[str, int]]:
    search = result.search_diagnostics or {}
    evaluator = result.evaluator_diagnostics or {}
    synth = result.synthesizer_diagnostics or {}

    counts: Counter[str] = Counter()

    dup = int(search.get("duplicate_url_dropped") or 0)
    if dup:
        counts["duplicate URL"] = dup

    cand = int(search.get("dropped_by_candidate_limit") or 0)
    if cand:
        counts["global source limit (Searcher candidate pool)"] = cand

    # Reader: documents that are fallback count as failed webpage reads.
    fallback_total = sum(r["fallback"] for r in rows)
    if fallback_total:
        counts["failed webpage read (snippet fallback)"] = fallback_total

    eval_drops = dict(evaluator.get("drop_reasons") or {})
    mapping = {
        "low_relevance": "low relevance",
        "low_credibility": "low credibility",
        "below_score_threshold": "below score threshold",
        "global_source_limit": "global source limit (Evaluator retention)",
        "per_task_source_limit": "per-task source limit",
        "duplicate_url": "duplicate URL",
    }
    for key, label in mapping.items():
        val = int(eval_drops.get(key) or 0)
        if val:
            counts[label] += val

    truncated = int(synth.get("truncated_by_max_evidence_items") or 0)
    if truncated:
        counts["global source limit (Synthesizer MAX_EVIDENCE_ITEMS)"] = truncated

    unused = synth.get("unused_evidence_ids") or []
    if unused:
        counts["no grounded finding generated"] = len(unused)

    # Missing usable excerpt: unused evidence that never got a successful full read.
    if result.synthesis:
        for eid in unused:
            item = (result.synthesis.evidence_index or {}).get(eid)
            if item and item.document.read_status != "success":
                counts["missing usable excerpt"] += 1

    return counts.most_common()


def _build_reader_evidence_yield(result: ResearchResult) -> dict[str, Any]:
    """Measure how Reader outcomes feed retained evidence and grounded findings."""
    documents = list(result.documents or [])
    evidence = list(result.evidence or [])
    sent = len(documents)

    def _status(doc) -> str:
        return (getattr(doc, "extraction_status", None) or "").upper()

    full = sum(1 for d in documents if _status(d) == "FULL_TEXT")
    partial = sum(1 for d in documents if _status(d) == "PARTIAL_TEXT")
    readable = full + partial
    snippet_fb = sum(1 for d in documents if bool(getattr(d, "snippet_fallback", False)))
    failed = sent - readable

    retained = [e for e in evidence if e.keep]
    # Snippet-only = true search-snippet fallback (not merely non-FULL/PARTIAL).
    retained_snippet = [
        e
        for e in retained
        if bool(getattr(e.document, "snippet_fallback", False))
        or e.document.read_status != "success"
    ]
    retained_readable = [
        e
        for e in retained
        if _status(e.document) in {"FULL_TEXT", "PARTIAL_TEXT"}
        and not bool(getattr(e.document, "snippet_fallback", False))
    ]

    # Map source_id / evidence id → provenance class for findings.
    index = (result.synthesis.evidence_index if result.synthesis else None) or {}
    eid_readable: set[str] = set()
    eid_snippet: set[str] = set()
    for eid, item in index.items():
        st = _status(item.document)
        is_snippet = bool(getattr(item.document, "snippet_fallback", False)) or (
            item.document.read_status != "success"
        )
        if st in {"FULL_TEXT", "PARTIAL_TEXT"} and not is_snippet:
            eid_readable.add(eid)
        elif is_snippet:
            eid_snippet.add(eid)

    findings_from_readable = 0
    findings_from_snippet_only = 0
    findings_mixed = 0
    content_findings = 0
    if result.synthesis:
        for key in CONTENT_SECTIONS:
            for finding in getattr(result.synthesis, key) or []:
                if finding.finding_type == "gap":
                    continue
                content_findings += 1
                ids = list(finding.evidence_ids or [])
                if not ids:
                    continue
                has_r = any(eid in eid_readable for eid in ids)
                has_s = any(eid in eid_snippet for eid in ids)
                if has_r and has_s:
                    findings_mixed += 1
                elif has_r:
                    findings_from_readable += 1
                elif has_s:
                    findings_from_snippet_only += 1

    readable_lengths = [
        int(getattr(d, "extracted_char_count", 0) or 0)
        for d in documents
        if _status(d) in {"FULL_TEXT", "PARTIAL_TEXT"}
    ]
    median_len = (
        int(statistics.median(readable_lengths)) if readable_lengths else 0
    )

    return {
        "sources_sent_to_reader": sent,
        "FULL_TEXT_count": full,
        "PARTIAL_TEXT_count": partial,
        "snippet_fallback_count": snippet_fb,
        "failed_extraction_count": failed,
        "full_partial_extraction_rate_pct": round(100.0 * readable / max(sent, 1), 1),
        "fallback_rate_pct": round(100.0 * snippet_fb / max(sent, 1), 1),
        "median_extracted_text_length": median_len,
        "retained_total": len(retained),
        "retained_readable_full_or_partial": len(retained_readable),
        "retained_snippet_only": len(retained_snippet),
        "retained_snippet_only_pct": round(
            100.0 * len(retained_snippet) / max(len(retained), 1), 1
        ),
        "content_findings_total": content_findings,
        "grounded_findings_from_full_partial": findings_from_readable,
        "grounded_findings_from_snippet_only": findings_from_snippet_only,
        "grounded_findings_mixed_provenance": findings_mixed,
    }


def _build_loss_summary(drop_off: list[tuple[str, int]]) -> str:
    if not drop_off:
        return "Most evidence loss occurred at: (insufficient data — no drop-offs recorded)"
    top = drop_off[:3]
    lines = ["Most evidence loss occurred at:"]
    for i, (reason, count) in enumerate(top, start=1):
        lines.append(f"{i}. {reason} ({count})")
    return "\n".join(lines)
