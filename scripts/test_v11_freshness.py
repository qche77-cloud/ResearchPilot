"""v1.1 search-quality / freshness regression checks.

Runs four intents and prints evidence-flow + freshness summaries.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.env import load_env
from src.evidence_flow import format_evidence_flow_report
from src.models import ResearchDepth
from src.pipeline import run_research

CASES = (
    ("PCB产业链", "structural+current"),
    ("卫星通信", "structure+recent"),
    ("今天商业航天为什么涨", "breaking/hot-topic"),
    ("圣泉集团", "company-current"),
)


def main() -> int:
    load_env(override=True)
    out_rows = []
    for topic, intent in CASES:
        print("=" * 72)
        print(f"CASE: {topic} ({intent})")
        result = run_research(topic, ResearchDepth.QUICK)
        diag = result.evidence_flow_diagnostics or {}
        analyzed = result.analyzed_query
        print(
            f"time_sensitive={getattr(analyzed, 'time_sensitive', None)} "
            f"query_type={getattr(analyzed, 'query_type', None)}"
        )
        print(format_evidence_flow_report(diag))
        totals = diag.get("totals") or {}
        search = (diag.get("stage_snapshots") or {}).get("search") or {}
        out_rows.append(
            {
                "topic": topic,
                "intent": intent,
                "time_sensitive": getattr(analyzed, "time_sensitive", None),
                "final_source_count": search.get("final_source_count"),
                "candidate_limit": search.get("candidate_limit"),
                "unique_after_dedupe": search.get("unique_sources_after_dedupe"),
                "retained": totals.get("retained"),
                "sent": totals.get("sent_to_synthesizer"),
                "findings": totals.get("content_findings"),
                "freshness": diag.get("freshness"),
            }
        )
        # Lightweight acceptance checks
        assert search.get("final_source_count", 0) >= 8, "v1.1 Quick should send >=8 to Reader"
        if "今天" in topic or "为什么涨" in topic:
            assert getattr(analyzed, "time_sensitive", False) is True

    out = Path(__file__).with_name("_v11_freshness.json")
    out.write_text(json.dumps(out_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=" * 72)
    print("wrote", out)
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
