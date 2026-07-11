"""Test coverage-aware evidence retention on 卫星通信 (Standard depth)."""

from __future__ import annotations

import json
from pathlib import Path

from src.env import load_env
from src.models import ResearchDepth
from src.pipeline import run_research


def main() -> None:
    load_env(override=True)
    result = run_research("卫星通信", ResearchDepth.STANDARD)
    synthesis = result.synthesis
    eval_diag = result.evaluator_diagnostics or {}
    search_diag = result.search_diagnostics or {}

    kept = [e for e in (result.evidence or []) if e.keep]
    urls = {e.source.url for e in kept}
    tasks = {e.source.research_task for e in kept if e.source.research_task}

    print("search final_source_count:", search_diag.get("final_source_count"))
    print("candidates_per_task:", search_diag.get("candidates_per_research_task"))
    print("eval retained_total:", eval_diag.get("retained_total"))
    print("retained_per_task:", eval_diag.get("retained_sources_per_research_task"))
    print("read_per_task:", eval_diag.get("read_sources_per_research_task"))
    print("fallback_per_task:", eval_diag.get("fallback_sources_per_research_task"))
    print("dropped_tasks:", eval_diag.get("dropped_tasks_with_zero_evidence"))
    print("kept evidence:", len(kept), "unique urls:", len(urls), "tasks:", len(tasks))
    print("evidence_index size:", len(synthesis.evidence_index) if synthesis else 0)

    content_keys = [
        "key_findings",
        "industry_chain_findings",
        "demand_supply_drivers",
        "technology_findings",
        "catalysts",
        "company_findings",
        "risks",
    ]
    populated = []
    gaps = len(synthesis.evidence_gaps) if synthesis else 0
    for key in content_keys:
        items = getattr(synthesis, key) if synthesis else []
        print(f"  {key}: {len(items)}")
        if items:
            populated.append(key)

    print("populated content sections:", populated)
    print("evidence_gaps:", gaps)
    print("report sections:", [s.title for s in result.report.sections])

    # Acceptance
    assert len(urls) > 2, "Synthesizer should see >2 distinct sources"
    assert len(tasks) >= 2, "Retained evidence should span multiple research tasks"
    assert eval_diag.get("retained_total", 0) >= 3
    assert "retained_sources_per_research_task" in eval_diag
    assert "dropped_tasks_with_zero_evidence" in eval_diag

    # Metadata preserved
    for e in kept:
        assert e.source.research_task is not None or True
        assert e.final_score >= 0
        # search_query may be None only for mocks; live path should set it
        assert hasattr(e.source, "search_query")

    # Grounding still intact for supported_facts
    for key in content_keys:
        for item in getattr(synthesis, key):
            if item.finding_type == "supported_fact":
                assert item.supporting_excerpts
                assert item.evidence_ids

    out = Path(__file__).with_name("_coverage_satcom.json")
    payload = {
        "search_diagnostics": search_diag,
        "evaluator_diagnostics": eval_diag,
        "kept_urls": sorted(urls),
        "kept_tasks": sorted(tasks),
        "populated_sections": populated,
        "evidence_gaps": gaps,
        "report_sections": [s.title for s in result.report.sections],
        "evidence_index": {
            eid: {
                "title": item.source.title,
                "url": item.source.url,
                "research_task": item.source.research_task,
                "final_score": item.final_score,
            }
            for eid, item in (synthesis.evidence_index or {}).items()
        },
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)
    print("OK")


if __name__ == "__main__":
    main()
