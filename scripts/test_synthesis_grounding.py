"""Test grounded synthesizer excerpts on 卫星通信."""

from __future__ import annotations

import json
from pathlib import Path

from src.env import load_env
from src.models import ResearchDepth
from src.pipeline import run_research


def main() -> None:
    load_env(override=True)
    result = run_research("卫星通信", ResearchDepth.QUICK)
    synthesis = result.synthesis
    diag = result.synthesizer_diagnostics or {}

    print("synthesizer_source:", synthesis.synthesizer_source)
    print("warning:", result.synthesizer_warning)
    print("evidence_sent:", diag.get("evidence_items_sent"))
    print("generated_findings:", diag.get("generated_findings"))
    print("supporting_excerpts:", diag.get("supporting_excerpts"))

    content_keys = [
        "key_findings",
        "industry_chain_findings",
        "demand_supply_drivers",
        "technology_findings",
        "catalysts",
        "company_findings",
        "risks",
    ]

    for key in content_keys + ["evidence_gaps"]:
        items = getattr(synthesis, key)
        print("=" * 40, key, f"({len(items)})")
        for item in items[:3]:
            print(f"- [{item.finding_type}] {item.finding}")
            print(f"  ids={item.evidence_ids}")
            for ex in item.supporting_excerpts[:2]:
                print(f"  excerpt[{ex.evidence_id}]: {ex.excerpt[:120]}")
                print(f"  source: {ex.source_title}")

    # Grounding assertions
    valid = set(synthesis.evidence_index.keys())
    for key in content_keys:
        for item in getattr(synthesis, key):
            assert "Evidence is insufficient" not in item.finding
            assert "证据不足" not in item.finding
            assert item.finding_type in {"supported_fact", "inference"}
            if item.finding_type == "supported_fact":
                assert item.supporting_excerpts, "supported_fact requires excerpts"
            for ex in item.supporting_excerpts:
                assert ex.evidence_id in valid
                doc = synthesis.evidence_index[ex.evidence_id]
                text = doc.document.extracted_text or doc.source.snippet or ""
                # Verbatim check with whitespace flexibility already enforced upstream;
                # ensure excerpt characters appear in source text.
                compact_src = "".join(text.split())
                compact_ex = "".join(ex.excerpt.split())
                assert compact_ex and compact_ex in compact_src

    for gap in synthesis.evidence_gaps:
        assert gap.finding_type != "supported_fact", "gaps must not claim supported_fact"

    out = Path(__file__).with_name("_synthesis_satcom.json")
    payload = {
        "diagnostics": diag,
        "sections": {
            key: [
                {
                    "finding": f.finding,
                    "finding_type": f.finding_type,
                    "evidence_ids": f.evidence_ids,
                    "supporting_excerpts": [
                        {
                            "evidence_id": ex.evidence_id,
                            "excerpt": ex.excerpt,
                            "source_title": ex.source_title,
                            "source_url": ex.source_url,
                        }
                        for ex in f.supporting_excerpts
                    ],
                }
                for f in getattr(synthesis, key)
            ]
            for key in content_keys + ["evidence_gaps"]
        },
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)
    print("OK")


if __name__ == "__main__":
    main()
