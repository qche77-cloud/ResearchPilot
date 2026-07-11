"""Shared data models for the ResearchPilot research workflow.

These types flow through the pipeline:

    AnalyzedQuery → ResearchPlan → Source → EvidenceDocument
        → EvaluatedEvidence → SynthesisBrief → ResearchReport → ResearchResult

Each stage consumes the previous stage's output and produces a typed result,
so QueryAnalyzer / Planner / Searcher / Reader / Evaluator / Synthesizer /
Writer stay decoupled and swappable (mock or live providers).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class QueryType(str, Enum):
    """High-level classification of a user research query."""

    INDUSTRY = "industry"
    COMPANY = "company"
    TECHNOLOGY = "technology/theme"


class ResearchDepth(str, Enum):
    """Research depth levels controlling scope and detail."""

    QUICK = "Quick"
    STANDARD = "Standard"
    DEEP = "Deep"

    @property
    def step_count(self) -> int:
        """Number of planning steps for this depth."""
        return {ResearchDepth.QUICK: 3, ResearchDepth.STANDARD: 5, ResearchDepth.DEEP: 8}[self]

    @property
    def source_count(self) -> int:
        """Target number of sources to retrieve for this depth."""
        return {ResearchDepth.QUICK: 4, ResearchDepth.STANDARD: 8, ResearchDepth.DEEP: 12}[self]


@dataclass
class AnalyzedQuery:
    """Structured interpretation of a user query (QueryAnalyzer output)."""

    raw_query: str
    query_type: QueryType
    normalized_topic: str
    research_goal: str


@dataclass
class ResearchPlanStep:
    """A single research task in the plan, with optional search queries."""

    order: int
    title: str
    description: str
    search_queries: List[str] = field(default_factory=list)


@dataclass
class ResearchPlan:
    """Structured research plan for a given topic (Planner output)."""

    topic: str
    depth: ResearchDepth
    steps: List[ResearchPlanStep] = field(default_factory=list)
    query_type: QueryType = QueryType.INDUSTRY
    research_goal: str = ""
    research_objective: str = ""
    research_strategy: str = ""
    analyzed_query: AnalyzedQuery | None = None
    planner_source: str = "rules"  # "llm" | "rules"


@dataclass
class Source:
    """A candidate source discovered by the Searcher (metadata only)."""

    title: str
    url: str
    snippet: str
    source_type: str
    relevance: float
    published_date: str | None = None
    search_query: str | None = None
    research_task: str | None = None


@dataclass
class EvidenceDocument:
    """Content extracted by the Reader from a Source.

    ``read_status`` is ``"success"`` when the page was fetched and parsed,
    or ``"fallback"`` when the search snippet was used instead.
    """

    source: Source
    extracted_text: str
    word_count: int
    read_status: str
    error_message: str | None = None
    key_excerpts: List[str] = field(default_factory=list)

    @property
    def content(self) -> str:
        """Alias for ``extracted_text`` (downstream compatibility)."""
        return self.extracted_text


@dataclass
class EvaluatedEvidence:
    """Evidence scored and ranked by the EvidenceEvaluator."""

    document: EvidenceDocument
    credibility_score: int
    relevance_score: int
    recency_score: int
    final_score: int
    evaluation_reason: str
    keep: bool = True

    @property
    def source(self) -> Source:
        """Convenience accessor for the underlying source metadata."""
        return self.document.source

    @property
    def credibility(self) -> float:
        """Legacy 0–1 credibility (derived from credibility_score)."""
        return self.credibility_score / 100.0

    @property
    def notes(self) -> str:
        """Alias for evaluation_reason (legacy callers)."""
        return self.evaluation_reason


@dataclass
class SupportingExcerpt:
    """A verbatim excerpt copied from an EvidenceDocument."""

    evidence_id: str
    excerpt: str
    source_title: str
    source_url: str


@dataclass
class GroundedFinding:
    """A single synthesis finding grounded in retrieved evidence."""

    finding: str
    evidence_ids: List[str] = field(default_factory=list)
    finding_type: str = "supported_fact"  # supported_fact | inference | gap
    supporting_excerpts: List[SupportingExcerpt] = field(default_factory=list)

    @property
    def kind(self) -> str:
        """Backward-compatible alias for ``finding_type``."""
        return self.finding_type


@dataclass
class SynthesisBrief:
    """Structured findings produced by the Synthesizer (not yet a report).

    Structured A-share sections hold grounded findings. Legacy ``findings``
    (dict of section title → markdown) is derived for the existing Writer.
    """

    topic: str
    depth: ResearchDepth
    findings: dict[str, str] = field(default_factory=dict)
    cited_evidence: List[EvaluatedEvidence] = field(default_factory=list)
    evidence_index: dict[str, EvaluatedEvidence] = field(default_factory=dict)
    key_findings: List[GroundedFinding] = field(default_factory=list)
    industry_chain_findings: List[GroundedFinding] = field(default_factory=list)
    demand_supply_drivers: List[GroundedFinding] = field(default_factory=list)
    technology_findings: List[GroundedFinding] = field(default_factory=list)
    catalysts: List[GroundedFinding] = field(default_factory=list)
    company_findings: List[GroundedFinding] = field(default_factory=list)
    risks: List[GroundedFinding] = field(default_factory=list)
    evidence_gaps: List[GroundedFinding] = field(default_factory=list)
    synthesizer_source: str = "fallback"  # llm | fallback


@dataclass
class ReportSection:
    """A section of the structured research report (Writer output)."""

    title: str
    content: str


@dataclass
class ResearchReport:
    """Complete structured research report produced by the Writer."""

    topic: str
    depth: ResearchDepth
    sections: List[ReportSection] = field(default_factory=list)
    writer_source: str = "fallback"  # llm | fallback

    def get_section(self, title: str) -> ReportSection | None:
        """Return a section by title, or None if not found."""
        for section in self.sections:
            if section.title == title:
                return section
        return None


@dataclass
class ResearchResult:
    """Full output of a research pipeline run.

    Retains ``plan``, ``sources``, and ``report`` for the Streamlit UI,
    plus intermediate artifacts for debugging and future agent tooling.
    """

    plan: ResearchPlan
    sources: List[Source]
    report: ResearchReport
    analyzed_query: AnalyzedQuery | None = None
    documents: List[EvidenceDocument] = field(default_factory=list)
    evidence: List[EvaluatedEvidence] = field(default_factory=list)
    synthesis: SynthesisBrief | None = None
    search_warning: str | None = None
    planner_warning: str | None = None
    search_diagnostics: dict | None = None
    synthesizer_warning: str | None = None
    synthesizer_diagnostics: dict | None = None
    writer_warning: str | None = None
    writer_diagnostics: dict | None = None
    evaluator_diagnostics: dict | None = None
