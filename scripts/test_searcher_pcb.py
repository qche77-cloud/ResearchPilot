"""Verify Searcher executes Planner search_queries for PCB产业链."""

from __future__ import annotations

import json
from pathlib import Path

from src.env import load_env
from src.models import ResearchDepth
from src.pipeline import run_research


def main() -> None:
    load_env(override=True)
    result = run_research("PCB产业链", ResearchDepth.STANDARD)
    diag = result.search_diagnostics or {}

    print("planner_source:", result.plan.planner_source)
    print("planner_queries_generated:", diag.get("planner_queries_generated"))
    print("queries_executed:", diag.get("queries_executed"))
    print("executed_queries:")
    for q in diag.get("executed_queries") or []:
        print(" -", q)
    print("results_per_query:")
    for q, n in (diag.get("results_per_query") or {}).items():
        print(f" - {n}: {q}")
    print("unique_after_dedupe:", diag.get("unique_sources_after_dedupe"))
    print("final_source_count:", diag.get("final_source_count"))
    print("tasks_represented:", diag.get("tasks_represented"))
    print("used_fallback_topic_query:", diag.get("used_fallback_topic_query"))

    print("\nSources (title / task / query):")
    for s in result.sources:
        print("-", s.title[:80])
        print("  task:", s.research_task)
        print("  query:", s.search_query)
        print("  url:", s.url)

    # Guardrails for the intended integration.
    assert diag.get("mode") in {"tavily_multi_query", "mock"}
    if diag.get("mode") == "tavily_multi_query":
        assert diag.get("planner_queries_generated", 0) >= 3
        assert diag.get("queries_executed", 0) >= 3
        assert not diag.get("used_fallback_topic_query")
        joined = " ".join(diag.get("executed_queries") or [])
        assert "PCB" in joined or "pcb" in joined.lower()
        # Should not be the old single generic English market-research query.
        for q in diag.get("executed_queries") or []:
            assert "industry research market analysis value chain" not in q.lower()

    out = Path(__file__).with_name("_searcher_pcb_out.json")
    out.write_text(
        json.dumps(
            {
                "diagnostics": diag,
                "sources": [
                    {
                        "title": s.title,
                        "url": s.url,
                        "task": s.research_task,
                        "query": s.search_query,
                    }
                    for s in result.sources
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\nwrote", out)
    print("OK")


if __name__ == "__main__":
    main()
