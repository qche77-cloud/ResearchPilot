"""Research pipeline orchestrator.

Responsibility
--------------
Wire the research workflow end-to-end without owning domain logic:

    Query → Analyze → Plan → Search → Read → Evaluate → Synthesize → Write

Each step delegates to a single-responsibility component. This module is
the only place that knows the full stage order.

Future integration
------------------
When OpenAI and Search APIs are added, swap implementations inside each
component. The pipeline signature stays the same::

    result = run_research(topic, depth)
"""

from __future__ import annotations

from src.env import load_env
from src.evaluator import EvidenceEvaluator
from src.models import ResearchDepth, ResearchResult
from src.planner import Planner
from src.query_analyzer import QueryAnalyzer
from src.reader import Reader
from src.searcher import Searcher
from src.synthesizer import Synthesizer
from src.writer import Writer

# Ensure project-root .env is loaded for all pipeline components.
load_env()


def run_research(topic: str, depth: ResearchDepth) -> ResearchResult:
    """Execute the full AI research workflow for a given topic.

    Pipeline stages:
        1. Analyze   — QueryAnalyzer
        2. Plan      — Planner
        3. Search    — Searcher
        4. Read      — Reader
        5. Evaluate  — EvidenceEvaluator
        6. Synthesize — Synthesizer
        7. Write     — Writer

    Args:
        topic: The industry, company, or technology topic to research.
        depth: How thorough the research should be.

    Returns:
        A ResearchResult containing analyzed query, plan, sources, evidence, and report.

    Raises:
        ValueError: If topic is empty or whitespace-only.
    """
    load_env()

    analyzed = QueryAnalyzer().analyze(topic)

    planner = Planner()
    plan = planner.plan(analyzed, depth)

    searcher = Searcher()
    sources = searcher.search(plan)

    documents = Reader().read(sources)
    evaluator = EvidenceEvaluator()
    evidence = evaluator.evaluate(documents, plan)

    synthesizer = Synthesizer()
    synthesis = synthesizer.synthesize(plan, evidence)

    writer = Writer()
    report = writer.write(plan, synthesis)

    return ResearchResult(
        plan=plan,
        sources=sources,
        report=report,
        analyzed_query=analyzed,
        documents=documents,
        evidence=evidence,
        synthesis=synthesis,
        search_warning=searcher.last_warning,
        planner_warning=planner.last_warning,
        search_diagnostics=searcher.last_diagnostics or None,
        synthesizer_warning=synthesizer.last_warning,
        synthesizer_diagnostics=synthesizer.last_diagnostics or None,
        writer_warning=writer.last_warning,
        writer_diagnostics=writer.last_diagnostics or None,
        evaluator_diagnostics=evaluator.last_diagnostics or None,
    )
