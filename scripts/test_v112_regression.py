"""v1.1.2 Reader Reliability regression suite + comparison metrics.

Runs the four diagnostic topics with bounded Reader timeouts.
Excludes mock/example.com sources from aggregate quality metrics.

Usage:
  python scripts/test_v112_regression.py
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.domain_penalty import domain_of
from src.env import load_env
from src.models import ResearchDepth
from src.pipeline import run_research
from src.synthesizer import CONTENT_SECTIONS

CASES: tuple[tuple[str, str], ...] = (
    ("卫星通信", "Standard"),
    ("PCB产业链", "Standard"),
    ("今天商业航天为什么涨", "Quick"),
    ("圣泉集团", "Quick"),
)

# Baseline from v1.1.1 diagnostic (real URLs only).
V111_BASELINE = {
    "readable_rate_pct": 72.9,
    "snippet_fallback_rate_pct": 27.1,
    "sources": 48,
    "readable": 35,
    "snippet_fallback": 13,
}


def _depth(label: str) -> ResearchDepth:
    for d in ResearchDepth:
        if d.value.lower() == label.lower() or d.name.lower() == label.lower():
            return d
    return ResearchDepth.QUICK


def _is_mock_url(url: str) -> bool:
    host = domain_of(url)
    return host == "example.com" or host.endswith(".example.com")


def _count_findings(result) -> tuple[int, int]:
    synthesis = result.synthesis
    if synthesis is None:
        return 0, 0
    content = 0
    for key in CONTENT_SECTIONS:
        for finding in getattr(synthesis, key) or []:
            if finding.finding_type == "gap":
                continue
            content += 1
    gaps = len(synthesis.evidence_gaps or [])
    return content, gaps


def _metrics_from_result(result) -> dict:
    docs = list(result.documents or [])
    real_docs = [d for d in docs if not _is_mock_url(d.source.url)]
    mock_docs = [d for d in docs if _is_mock_url(d.source.url)]
    search_mode = (result.search_diagnostics or {}).get("mode") or ""
    used_mock = bool(mock_docs) or "mock" in str(search_mode).lower()

    def _rate(docs_subset):
        sent = len(docs_subset)
        readable = sum(
            1
            for d in docs_subset
            if (d.extraction_status or "").upper() in {"FULL_TEXT", "PARTIAL_TEXT"}
            and not d.snippet_fallback
        )
        fallback = sum(1 for d in docs_subset if d.snippet_fallback)
        return {
            "sources": sent,
            "readable": readable,
            "snippet_fallback": fallback,
            "readable_rate_pct": round(100.0 * readable / max(sent, 1), 1),
            "snippet_fallback_rate_pct": round(100.0 * fallback / max(sent, 1), 1),
        }

    findings, gaps = _count_findings(result)
    funnel = (result.reader_diagnostics or {}).get("funnel") or {}
    repl = (result.reader_diagnostics or {}).get("replacement") or {}
    penalties = int(
        (result.search_diagnostics or {}).get("domain_penalties_applied_count") or 0
    )
    return {
        "topic": result.plan.topic,
        "depth": result.plan.depth.value,
        "used_mock_search": used_mock,
        "search_mode": search_mode,
        "all": _rate(docs),
        "real_urls": _rate(real_docs),
        "mock_urls": _rate(mock_docs),
        "grounded_findings": findings,
        "evidence_gaps": gaps,
        "replacement_attempts": int(repl.get("attempt_count") or 0),
        "replacement_successes": int(repl.get("success_count") or 0),
        "replacement_success_rate_pct": float(repl.get("success_rate_pct") or 0.0),
        "pdf_attempts": int(funnel.get("pdf_extraction_attempts") or 0),
        "pdf_successes": int(funnel.get("pdf_extraction_successes") or 0),
        "pdf_success_rate_pct": float(funnel.get("pdf_extraction_success_rate_pct") or 0.0),
        "domain_penalties_applied_count": penalties,
        "status_counts": funnel.get("status_counts") or {},
    }


def main() -> int:
    load_env(override=True)
    os.environ.setdefault("RESEARCHPILOT_READER_TIMEOUT", "8")

    runs: list[dict] = []
    for topic, depth_label in CASES:
        print("=" * 72)
        print(f"Running {topic} ({depth_label}) …")
        try:
            result = run_research(topic, _depth(depth_label))
            row = _metrics_from_result(result)
            row["ok"] = True
            print(
                f"  real readable={row['real_urls']['readable_rate_pct']}% "
                f"fallback={row['real_urls']['snippet_fallback_rate_pct']}% "
                f"findings={row['grounded_findings']} gaps={row['evidence_gaps']} "
                f"repl={row['replacement_successes']}/{row['replacement_attempts']} "
                f"pdf={row['pdf_successes']}/{row['pdf_attempts']} "
                f"mock={row['used_mock_search']}"
            )
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            row = {
                "topic": topic,
                "depth": depth_label,
                "ok": False,
                "error": str(exc),
                "used_mock_search": True,
            }
            print(f"  ERROR: {exc}")
        runs.append(row)

    real_runs = [r for r in runs if r.get("ok") and not r.get("used_mock_search")]
    mock_runs = [r for r in runs if r.get("ok") and r.get("used_mock_search")]

    def _agg(subset: list[dict]) -> dict:
        sent = sum(int((r.get("real_urls") or {}).get("sources") or 0) for r in subset)
        readable = sum(int((r.get("real_urls") or {}).get("readable") or 0) for r in subset)
        fb = sum(
            int((r.get("real_urls") or {}).get("snippet_fallback") or 0) for r in subset
        )
        findings = sum(int(r.get("grounded_findings") or 0) for r in subset)
        gaps = sum(int(r.get("evidence_gaps") or 0) for r in subset)
        repl_a = sum(int(r.get("replacement_attempts") or 0) for r in subset)
        repl_s = sum(int(r.get("replacement_successes") or 0) for r in subset)
        pdf_a = sum(int(r.get("pdf_attempts") or 0) for r in subset)
        pdf_s = sum(int(r.get("pdf_successes") or 0) for r in subset)
        return {
            "topics": len(subset),
            "sources": sent,
            "readable": readable,
            "snippet_fallback": fb,
            "readable_rate_pct": round(100.0 * readable / max(sent, 1), 1),
            "snippet_fallback_rate_pct": round(100.0 * fb / max(sent, 1), 1),
            "grounded_findings": findings,
            "evidence_gaps": gaps,
            "replacement_attempts": repl_a,
            "replacement_successes": repl_s,
            "replacement_success_rate_pct": round(
                100.0 * repl_s / max(repl_a, 1), 1
            )
            if repl_a
            else 0.0,
            "pdf_attempts": pdf_a,
            "pdf_successes": pdf_s,
            "pdf_success_rate_pct": round(100.0 * pdf_s / max(pdf_a, 1), 1)
            if pdf_a
            else 0.0,
        }

    v112 = _agg(real_runs)
    comparison = {
        "metric": [
            "readable_rate_pct",
            "snippet_fallback_rate_pct",
            "grounded_findings",
            "evidence_gaps",
            "replacement_success_rate_pct",
            "pdf_success_rate_pct",
        ],
        "v1.1.1_real_urls": {
            "readable_rate_pct": V111_BASELINE["readable_rate_pct"],
            "snippet_fallback_rate_pct": V111_BASELINE["snippet_fallback_rate_pct"],
            "grounded_findings": "n/a (baseline diagnostic did not aggregate)",
            "evidence_gaps": "n/a",
            "replacement_success_rate_pct": 0.0,
            "pdf_success_rate_pct": 0.0,
            "sources": V111_BASELINE["sources"],
            "readable": V111_BASELINE["readable"],
            "snippet_fallback": V111_BASELINE["snippet_fallback"],
        },
        "v1.1.2_real_urls": v112,
        "mock_topics_excluded": [r.get("topic") for r in mock_runs],
    }

    payload = {
        "runs": runs,
        "aggregate_real_urls": v112,
        "mock_runs": mock_runs,
        "comparison": comparison,
    }
    out = Path(__file__).with_name("_v112_regression.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 72)
    print("# v1.1.1 vs v1.1.2 (real URLs only)")
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    print("wrote", out)
    return 0 if any(r.get("ok") for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
