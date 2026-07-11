"""Diagnose Planner OpenAI configuration without exposing secrets."""

from __future__ import annotations

from pathlib import Path

from src.env import load_env, openai_api_key_status, project_root
from src.models import ResearchDepth
from src.planner import Planner
from src.query_analyzer import QueryAnalyzer


def _env_openai_line_state() -> str:
    env_path = project_root() / ".env"
    if not env_path.is_file():
        return "missing_.env"
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped.startswith("#") and "OPENAI_API_KEY=" in stripped:
            return "commented_out"
        if stripped.startswith("OPENAI_API_KEY="):
            value = stripped.split("=", 1)[1].strip().strip('"').strip("'")
            return "active_nonempty" if value else "active_empty"
    return "not_present"


def main() -> None:
    load_env(override=True)
    status = openai_api_key_status()
    line_state = _env_openai_line_state()

    print("env_file:", project_root() / ".env")
    print("openai_line_state:", line_state)
    print("key_detected:", status["present"])
    print("key_length:", status["length"])
    print("key_prefix:", status["prefix"])
    print("model:", status["model"])

    query = "PCB产业链"
    analyzed = QueryAnalyzer().analyze(query)
    planner = Planner()
    plan = planner.plan(analyzed, ResearchDepth.STANDARD)

    print("query:", query)
    print("query_type:", analyzed.query_type.value)
    print("planner_source:", plan.planner_source)
    print("planner_warning:", planner.last_warning)
    print("objective:", plan.research_objective)
    print("tasks:", len(plan.steps))
    for step in plan.steps[:3]:
        print(f"  {step.order}. {step.title}")
        print(f"     queries: {step.search_queries}")


if __name__ == "__main__":
    main()
