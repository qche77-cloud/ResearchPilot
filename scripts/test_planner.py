"""Smoke test for LLM / rule-based Planner."""

from __future__ import annotations

import os
from pathlib import Path

from src.models import ResearchDepth
from src.planner import Planner
from src.query_analyzer import QueryAnalyzer


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> None:
    _load_dotenv()
    key_set = bool(os.getenv("OPENAI_API_KEY", "").strip())
    print("OPENAI_API_KEY set:", key_set)

    analyzer = QueryAnalyzer()
    planner = Planner()

    for query in ["PCB industry chain", "Shengquan Group", "AI glasses"]:
        analyzed = analyzer.analyze(query)
        plan = planner.plan(analyzed, ResearchDepth.STANDARD)
        print("=" * 60)
        print("QUERY:", query)
        print("type:", analyzed.query_type.value)
        print("planner_source:", plan.planner_source)
        print("warning:", planner.last_warning)
        print("objective:", plan.research_objective)
        strategy = plan.research_strategy
        print("strategy:", strategy[:140] + ("..." if len(strategy) > 140 else ""))
        print("tasks:", len(plan.steps))
        for step in plan.steps[:3]:
            print(f"  {step.order}. {step.title}")
            print(f"     queries: {step.search_queries}")

        assert plan.research_objective
        assert plan.research_strategy
        assert len(plan.steps) >= 3
        assert all(step.search_queries for step in plan.steps)

    print("ALL OK")


if __name__ == "__main__":
    main()
