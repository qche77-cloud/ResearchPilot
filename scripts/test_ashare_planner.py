"""Test A-share LLM Planner prompts on sample queries."""

from __future__ import annotations

from src.env import load_env, openai_api_key_status
from src.models import ResearchDepth
from src.planner import Planner
from src.query_analyzer import QueryAnalyzer


def main() -> None:
    load_env(override=True)
    status = openai_api_key_status()
    print("key_detected:", status["present"], "model:", status["model"])

    analyzer = QueryAnalyzer()
    planner = Planner()

    for query in ["PCB产业链", "液冷", "圣泉集团"]:
        analyzed = analyzer.analyze(query)
        plan = planner.plan(analyzed, ResearchDepth.STANDARD)
        print("=" * 64)
        print("QUERY:", query)
        print("type:", analyzed.query_type.value)
        print("planner_source:", plan.planner_source)
        print("warning:", planner.last_warning)
        print("objective:", plan.research_objective)
        print("strategy:", plan.research_strategy)
        print("tasks:", len(plan.steps))
        for step in plan.steps:
            print(f"  {step.order}. {step.title}")
            print(f"     {step.description[:160]}")
            print(f"     queries: {step.search_queries}")

        assert plan.research_objective
        assert plan.research_strategy
        assert len(plan.steps) >= 3
        assert all(2 <= len(s.search_queries) <= 4 for s in plan.steps)

    print("ALL OK")


if __name__ == "__main__":
    main()
