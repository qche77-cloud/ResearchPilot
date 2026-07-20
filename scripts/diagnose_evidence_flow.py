"""Diagnose where evidence is dropped across the ResearchPilot pipeline.

Does not change ranking, retention, or synthesis behavior — read-only funnel
metrics over a live run.

Usage:
  python scripts/diagnose_evidence_flow.py
  python scripts/diagnose_evidence_flow.py --topic 卫星通信 --depth Quick
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.env import load_env
from src.evidence_flow import format_evidence_flow_report
from src.models import ResearchDepth
from src.pipeline import run_research

DEFAULT_TOPICS = ("卫星通信", "PCB产业链", "圣泉集团")


def _depth_from_label(label: str) -> ResearchDepth:
    for depth in ResearchDepth:
        if depth.value.lower() == label.lower() or depth.name.lower() == label.lower():
            return depth
    return ResearchDepth.QUICK


def diagnose_topic(topic: str, depth: ResearchDepth) -> dict:
    result = run_research(topic, depth)
    diag = result.evidence_flow_diagnostics or {}
    print(format_evidence_flow_report(diag))
    print()
    return diag


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", action="append", dest="topics", help="Topic to diagnose")
    parser.add_argument("--depth", default="Quick", help="Quick | Standard | Deep")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional JSON output path (ignored by git via scripts/_*.json)",
    )
    args = parser.parse_args(argv)

    load_env(override=True)
    depth = _depth_from_label(args.depth)
    topics = tuple(args.topics) if args.topics else DEFAULT_TOPICS

    all_diags = []
    for topic in topics:
        print("=" * 72)
        diag = diagnose_topic(topic, depth)
        all_diags.append(diag)

    # Cross-topic summary of top loss reasons.
    print("=" * 72)
    print("# Cross-topic loss ranking")
    combined: dict[str, int] = {}
    for diag in all_diags:
        for reason, count in diag.get("drop_off_reasons") or []:
            combined[reason] = combined.get(reason, 0) + int(count)
    for i, (reason, count) in enumerate(
        sorted(combined.items(), key=lambda kv: kv[1], reverse=True)[:5],
        start=1,
    ):
        print(f"{i}. {reason} ({count})")

    if args.out:
        args.out.write_text(
            json.dumps(all_diags, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("wrote", args.out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
