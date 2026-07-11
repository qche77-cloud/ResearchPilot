"""Test LLM Synthesizer on 商业航天产业链."""

from __future__ import annotations

import json
from pathlib import Path

from src.env import load_env
from src.models import ResearchDepth
from src.pipeline import run_research


def _count_findings(synthesis) -> int:
    keys = [
        "key_findings",
        "industry_chain_findings",
        "demand_supply_drivers",
        "technology_findings",
        "catalysts",
        "company_findings",
        "risks",
        "evidence_gaps",
    ]
    return sum(len(getattr(synthesis, k)) for k in keys)


def main() -> None:
    load_env(override=True)
    result = run_research("商业航天产业链", ResearchDepth.QUICK)
    synthesis = result.synthesis
    diag = result.synthesizer_diagnostics or {}

    print("planner_source:", result.plan.planner_source)
    print("synthesizer_source:", diag.get("synthesizer_source"), synthesis.synthesizer_source)
    print("warning:", result.synthesizer_warning)
    print("evidence_sent:", diag.get("evidence_items_sent"))
    print("generated_findings:", diag.get("generated_findings"), _count_findings(synthesis))
    print("evidence_ids:", list(synthesis.evidence_index.keys()))

    for key in [
        "key_findings",
        "industry_chain_findings",
        "demand_supply_drivers",
        "technology_findings",
        "catalysts",
        "company_findings",
        "risks",
        "evidence_gaps",
    ]:
        items = getattr(synthesis, key)
        print("=" * 40, key)
        for item in items[:4]:
            print(f"- [{item.kind}] {item.finding}")
            print(f"  ids={item.evidence_ids}")

    # Basic grounding checks when LLM path succeeded.
    if synthesis.synthesizer_source == "llm":
        valid = set(synthesis.evidence_index.keys())
        for key in [
            "key_findings",
            "industry_chain_findings",
            "demand_supply_drivers",
            "technology_findings",
            "catalysts",
            "company_findings",
            "risks",
        ]:
            for item in getattr(synthesis, key):
                for eid in item.evidence_ids:
                    assert eid in valid, f"unknown evidence id {eid} in {key}"
                # Invented company placeholders from old mock should not appear.
                assert "Alpha " not in item.finding
                assert "NovaTech" not in item.finding

    # Writer compatibility: legacy findings populated.
    assert synthesis.findings.get("Executive Summary")
    assert result.report.sections

    out = Path(__file__).with_name("_synthesis_commercial_space.json")
    payload = {
        "diagnostics": diag,
        "warning": result.synthesizer_warning,
        "sections": {
            key: [
                {
                    "finding": f.finding,
                    "evidence_ids": f.evidence_ids,
                    "kind": f.kind,
                }
                for f in getattr(synthesis, key)
            ]
            for key in [
                "key_findings",
                "industry_chain_findings",
                "demand_supply_drivers",
                "technology_findings",
                "catalysts",
                "company_findings",
                "risks",
                "evidence_gaps",
            ]
        },
        "evidence_index": {
            eid: {
                "title": item.source.title,
                "url": item.source.url,
                "score": item.final_score,
            }
            for eid, item in synthesis.evidence_index.items()
        },
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)
    print("OK")


if __name__ == "__main__":
    main()
