"""v1.2 Evidence Strategy regression across five topics.

Compares search-call counts and coverage vs v1.1.2 baseline estimates.
Excludes mock/example.com topics from quality aggregates.

Usage:
  python scripts/test_v12_regression.py
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

CASES = (
    ("PCB产业链", "Standard"),
    ("卫星通信", "Standard"),
    ("今天商业航天为什么涨", "Quick"),
    ("圣泉集团", "Quick"),
    ("液冷产业链", "Quick"),
)

V112_BASELINE = {
    "readable_rate_pct": 80.6,
    "snippet_fallback_rate_pct": 19.4,
    "search_calls_estimate": 20,
}


def _depth(label: str) -> ResearchDepth:
    for d in ResearchDepth:
        if d.value.lower() == label.lower() or d.name.lower() == label.lower():
            return d
    return ResearchDepth.QUICK


def _is_mock(url: str) -> bool:
    host = domain_of(url)
    return host == "example.com" or host.endswith(".example.com")


def _findings(result) -> int:
    if not result.synthesis:
        return 0
    n = 0
    for key in CONTENT_SECTIONS:
        for f in getattr(result.synthesis, key) or []:
            if f.finding_type != "gap":
                n += 1
    return n


def main() -> int:
    load_env(override=True)
    os.environ.setdefault("RESEARCHPILOT_READER_TIMEOUT", "8")

    runs = []
    for topic, depth_label in CASES:
        print("=" * 72)
        print(f"Running {topic} ({depth_label}) …")
        try:
            result = run_research(topic, _depth(depth_label))
            docs = list(result.documents or [])
            real = [d for d in docs if not _is_mock(d.source.url)]
            mock = [d for d in docs if _is_mock(d.source.url)]
            mode = (result.search_diagnostics or {}).get("mode") or ""
            used_mock = bool(mock) or "mock" in str(mode).lower()
            readable = sum(
                1
                for d in real
                if (d.extraction_status or "").upper() in {"FULL_TEXT", "PARTIAL_TEXT"}
                and not d.snippet_fallback
            )
            fb = sum(1 for d in real if d.snippet_fallback)
            eff = result.search_efficiency_diagnostics or {}
            cov = result.coverage_diagnostics or {}
            strat = result.evidence_strategy_diagnostics or {}
            preferred_hits = 0
            retained = [e for e in (result.evidence or []) if e.keep]
            for e in retained:
                et = getattr(e.source, "evidence_type", None) or ""
                if et and et != "GENERAL_WEB":
                    preferred_hits += 1
            row = {
                "topic": topic,
                "depth": depth_label,
                "ok": True,
                "used_mock_search": used_mock,
                "search_mode": mode,
                "real_sources": len(real),
                "readable": readable,
                "snippet_fallback": fb,
                "readable_rate_pct": round(100.0 * readable / max(len(real), 1), 1),
                "grounded_findings": _findings(result),
                "evidence_gaps": len(result.synthesis.evidence_gaps) if result.synthesis else 0,
                "tavily_search_calls": eff.get("tavily_search_calls"),
                "initial_queries_executed": eff.get("initial_queries_executed"),
                "followup_queries_executed": eff.get("followup_queries_executed"),
                "queries_saved_vs_v11_baseline": eff.get("queries_saved_vs_v11_baseline"),
                "grounded_findings_per_search_call": eff.get(
                    "grounded_findings_per_search_call"
                ),
                "gaps_before_followup": cov.get("gaps_before"),
                "gaps_after_followup": cov.get("gaps_after"),
                "strategy_initial_queries": strat.get("initial_queries_selected"),
                "non_general_retained": preferred_hits,
                "time_sensitive": bool(getattr(result.plan, "time_sensitive", False)),
            }
            print(
                f"  calls={row['tavily_search_calls']} init={row['initial_queries_executed']} "
                f"follow={row['followup_queries_executed']} "
                f"readable={row['readable_rate_pct']}% findings={row['grounded_findings']} "
                f"gaps {row['gaps_before_followup']}→{row['gaps_after_followup']} "
                f"mock={used_mock}"
            )
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            row = {"topic": topic, "depth": depth_label, "ok": False, "error": str(exc)}
            print(f"  ERROR: {exc}")
        runs.append(row)

    real_runs = [r for r in runs if r.get("ok") and not r.get("used_mock_search")]
    mock_runs = [r for r in runs if r.get("ok") and r.get("used_mock_search")]

    def _avg(key: str) -> float:
        vals = [float(r.get(key) or 0) for r in real_runs if r.get(key) is not None]
        return round(sum(vals) / max(len(vals), 1), 2) if vals else 0.0

    agg = {
        "topics_real": len(real_runs),
        "avg_tavily_search_calls": _avg("tavily_search_calls"),
        "avg_initial_queries": _avg("initial_queries_executed"),
        "avg_followup_queries": _avg("followup_queries_executed"),
        "avg_readable_rate_pct": _avg("readable_rate_pct"),
        "avg_grounded_findings": _avg("grounded_findings"),
        "avg_findings_per_call": _avg("grounded_findings_per_search_call"),
        "avg_gaps_before": _avg("gaps_before_followup"),
        "avg_gaps_after": _avg("gaps_after_followup"),
        "total_queries_saved_vs_v11": sum(
            int(r.get("queries_saved_vs_v11_baseline") or 0) for r in real_runs
        ),
    }
    comparison = {
        "v1.1.2_baseline": V112_BASELINE,
        "v1.2_real_urls_aggregate": agg,
        "mock_topics_excluded": [r.get("topic") for r in mock_runs],
        "runs": runs,
    }
    out = Path(__file__).with_name("_v12_regression.json")
    out.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 72)
    print(json.dumps({"aggregate": agg, "mock_excluded": comparison["mock_topics_excluded"]}, ensure_ascii=False, indent=2))
    print("wrote", out)
    return 0 if any(r.get("ok") for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
