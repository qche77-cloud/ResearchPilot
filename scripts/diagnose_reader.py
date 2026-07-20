"""Diagnose Reader / evidence-extraction quality for ResearchPilot.

Diagnostic-only: classifies extraction outcomes, domain failures, and
evidence yield. Does not add browsers, PDF OCR, or paid extractors.

Usage:
  python scripts/diagnose_reader.py
  python scripts/diagnose_reader.py --topic 卫星通信 --depth Standard
  python scripts/diagnose_reader.py --topic PCB产业链 --topic 圣泉集团 --depth Quick
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from collections import Counter
from pathlib import Path

# Allow `python scripts/diagnose_reader.py` from repo root.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.env import load_env
from src.models import ResearchDepth
from src.pipeline import run_research
from src.reader import format_reader_diagnostics_report

DEFAULT_CASES: tuple[tuple[str, str], ...] = (
    ("卫星通信", "Standard"),
    ("PCB产业链", "Standard"),
    ("今天商业航天为什么涨", "Quick"),
    ("圣泉集团", "Quick"),
)


def _depth_from_label(label: str) -> ResearchDepth:
    for depth in ResearchDepth:
        if depth.value.lower() == label.lower() or depth.name.lower() == label.lower():
            return depth
    return ResearchDepth.QUICK


def diagnose_topic(topic: str, depth: ResearchDepth) -> dict:
    result = run_research(topic, depth)
    diag = dict(result.reader_diagnostics or {})
    diag["topic"] = topic
    diag["depth"] = depth.value
    diag["ok"] = True
    # Yield is attached by evidence_flow onto reader_diagnostics.
    if "evidence_yield" not in diag and result.evidence_flow_diagnostics:
        diag["evidence_yield"] = (
            result.evidence_flow_diagnostics.get("reader_evidence_yield") or {}
        )
    print(format_reader_diagnostics_report(diag, topic=f"{topic} ({depth.value})"))
    print()
    return diag


def _write_partial(path: Path, diags: list[dict], cross: dict | None = None) -> None:
    payload = {
        "runs": diags,
        "cross_topic": cross or _cross_topic_summary(diags),
        "completed": len([d for d in diags if d.get("ok")]),
        "failed_topics": [
            {"topic": d.get("topic"), "error": d.get("error")}
            for d in diags
            if not d.get("ok")
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _cross_topic_summary(diags: list[dict]) -> dict:
    status_totals: Counter[str] = Counter()
    reason_totals: Counter[str] = Counter()
    domain_fail: Counter[str] = Counter()
    domain_ok: Counter[str] = Counter()
    sent = full = partial = fallback = 0
    findings_readable = findings_snippet = 0
    retained_snippet_pcts: list[float] = []

    for diag in diags:
        funnel = diag.get("funnel") or {}
        sent += int(funnel.get("sources_sent_to_reader") or 0)
        full += int(funnel.get("FULL_TEXT") or 0)
        partial += int(funnel.get("PARTIAL_TEXT") or 0)
        fallback += int(funnel.get("snippet_fallback_count") or 0)
        for status, count in (funnel.get("status_counts") or {}).items():
            status_totals[status] += int(count)
        for item in diag.get("top_failure_reasons") or []:
            reason_totals[str(item.get("reason") or "")] += int(item.get("count") or 0)
        for row in diag.get("by_domain") or []:
            domain = str(row.get("domain") or "unknown")
            readable = int(row.get("FULL_TEXT") or 0) + int(row.get("PARTIAL_TEXT") or 0)
            failed = int(row.get("sources") or 0) - readable
            domain_ok[domain] += readable
            domain_fail[domain] += failed
        yield_block = diag.get("evidence_yield") or {}
        findings_readable += int(
            yield_block.get("grounded_findings_from_full_partial") or 0
        )
        findings_snippet += int(
            yield_block.get("grounded_findings_from_snippet_only") or 0
        )
        if yield_block.get("retained_snippet_only_pct") is not None:
            retained_snippet_pcts.append(float(yield_block["retained_snippet_only_pct"]))

    readable = full + partial
    return {
        "topics": len(diags),
        "sources_sent_to_reader": sent,
        "FULL_TEXT": full,
        "PARTIAL_TEXT": partial,
        "full_partial_rate_pct": round(100.0 * readable / max(sent, 1), 1),
        "snippet_fallback_count": fallback,
        "fallback_rate_pct": round(100.0 * fallback / max(sent, 1), 1),
        "status_totals": dict(status_totals),
        "top_failure_causes": [
            {"reason": r, "count": c}
            for r, c in reason_totals.most_common(10)
            if r
        ],
        "domains_most_failures": [
            {"domain": d, "failed": c, "readable": domain_ok[d]}
            for d, c in domain_fail.most_common(10)
            if c > 0
        ],
        "domains_most_readable": [
            {"domain": d, "readable": c, "failed": domain_fail[d]}
            for d, c in domain_ok.most_common(10)
            if c > 0
        ],
        "grounded_findings_from_full_partial": findings_readable,
        "grounded_findings_from_snippet_only": findings_snippet,
        "avg_retained_snippet_only_pct": (
            round(sum(retained_snippet_pcts) / len(retained_snippet_pcts), 1)
            if retained_snippet_pcts
            else 0.0
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", action="append", dest="topics", help="Topic to diagnose")
    parser.add_argument(
        "--depth",
        default=None,
        help="Quick | Standard | Deep (applies to all --topic values)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).with_name("_reader_diag.json"),
        help="JSON output path",
    )
    args = parser.parse_args(argv)

    load_env(override=True)
    # Bound Reader HTTP waits for diagnostic suite throughput.
    os.environ.setdefault("RESEARCHPILOT_READER_TIMEOUT", "8")

    if args.topics:
        depth = _depth_from_label(args.depth or "Quick")
        cases = [(topic, depth.value) for topic in args.topics]
    else:
        cases = list(DEFAULT_CASES)
        if args.depth:
            depth = _depth_from_label(args.depth)
            cases = [(topic, depth.value) for topic, _ in cases]

    diags: list[dict] = []
    for topic, depth_label in cases:
        print("=" * 72)
        try:
            diag = diagnose_topic(topic, _depth_from_label(depth_label))
        except Exception as exc:  # noqa: BLE001 — keep suite moving
            print(f"[error] {topic} ({depth_label}): {exc}")
            traceback.print_exc()
            diag = {
                "topic": topic,
                "depth": depth_label,
                "ok": False,
                "error": str(exc),
                "funnel": {},
                "per_source": [],
                "by_domain": [],
                "top_failure_reasons": [],
                "evidence_yield": {},
            }
        diags.append(diag)
        _write_partial(args.out, diags)
        print(f"[checkpoint] wrote {args.out} ({len(diags)}/{len(cases)})")

    ok_diags = [d for d in diags if d.get("ok")]
    cross = _cross_topic_summary(ok_diags)
    print("=" * 72)
    print("# Cross-topic Reader summary")
    print(json.dumps(cross, ensure_ascii=False, indent=2))
    _write_partial(args.out, diags, cross=cross)
    print()
    print("wrote", args.out)
    return 0 if ok_diags else 1


if __name__ == "__main__":
    sys.exit(main())
