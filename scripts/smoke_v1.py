"""V1 smoke tests: PCB产业链, 卫星通信, and one company query."""

from __future__ import annotations

import re
import sys

from src.env import load_env
from src.models import ResearchDepth
from src.pipeline import run_research

BANNED = (
    "Alpha Corp",
    "NovaTech",
    "Beta Industries",
    "Example Corp",
    "示例公司A",
    "虚构公司",
)


def _smoke(topic: str) -> dict:
    result = run_research(topic, ResearchDepth.QUICK)
    report = result.report
    synthesis = result.synthesis
    text = "\n".join(f"{s.title}\n{s.content}" for s in report.sections)

    for banned in BANNED:
        if banned in text:
            raise AssertionError(f"[{topic}] fictional placeholder found: {banned}")

    assert report.sections, f"[{topic}] empty report"
    assert any(s.title == "Sources" for s in report.sections), f"[{topic}] missing Sources"
    assert synthesis is not None, f"[{topic}] missing synthesis"

    valid = set(synthesis.evidence_index.keys())
    cited = {m.upper() for m in re.findall(r"\[(E\d+)\]", text, flags=re.IGNORECASE)}
    for eid in cited:
        assert eid in valid, f"[{topic}] citation {eid} not in evidence index"

    sources = next(s for s in report.sections if s.title == "Sources")
    for eid in valid:
        assert f"[{eid}]" in sources.content, f"[{topic}] Sources missing {eid}"
        assert synthesis.evidence_index[eid].source.url in sources.content

    for key in (
        "key_findings",
        "industry_chain_findings",
        "demand_supply_drivers",
        "technology_findings",
        "catalysts",
        "company_findings",
        "risks",
    ):
        for item in getattr(synthesis, key):
            if item.finding_type == "supported_fact":
                assert item.supporting_excerpts, f"[{topic}] supported_fact without excerpt"
                assert item.evidence_ids

    return {
        "topic": topic,
        "query_type": result.plan.query_type.value if result.plan.query_type else None,
        "planner_source": getattr(result.plan, "planner_source", None),
        "synthesizer_source": synthesis.synthesizer_source,
        "writer_source": report.writer_source,
        "evidence_kept": sum(1 for e in result.evidence if e.keep),
        "evidence_index": len(synthesis.evidence_index),
        "sections": [s.title for s in report.sections],
        "warnings": {
            "planner": result.planner_warning,
            "search": result.search_warning,
            "synthesizer": result.synthesizer_warning,
            "writer": result.writer_warning,
        },
    }


def main() -> int:
    load_env(override=True)
    topics = ["PCB产业链", "卫星通信", "宁德时代"]
    for topic in topics:
        print("=" * 60)
        print("SMOKE:", topic)
        summary = _smoke(topic)
        for k, v in summary.items():
            print(f"  {k}: {v}")
        print("  PASS")
    print("=" * 60)
    print("ALL SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
