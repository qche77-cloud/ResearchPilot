"""ResearchPilot — Streamlit application entry point."""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

import streamlit as st

from src.env import load_env
from src.models import ResearchDepth
from src.pipeline import run_research

# Load project-root .env before any research run.
load_env()

if TYPE_CHECKING:
    from src.models import (
        EvidenceDocument,
        EvaluatedEvidence,
        ResearchPlan,
        ResearchReport,
        ResearchResult,
        Source,
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_STAGES: list[tuple[str, str]] = [
    ("planning", "🧠 Planning research..."),
    ("searching", "🔍 Searching multiple sources..."),
    ("reading", "📖 Reading evidence..."),
    ("analyzing", "📊 Analyzing industry information..."),
    ("writing", "✍️ Writing research report..."),
]

STAGE_DELAY = 1.0
EVIDENCE_REVEAL_DELAY = 0.55

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="ResearchPilot",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1.25rem;
            padding-bottom: 2rem;
            max-width: 820px;
        }
        header[data-testid="stHeader"] { background: transparent; }
        .rp-hero {
            margin-bottom: 1.75rem;
        }
        .rp-hero-badge {
            display: inline-block;
            font-size: 0.72rem;
            font-weight: 600;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: #6b7280;
            background: #f3f4f6;
            border-radius: 4px;
            padding: 0.2rem 0.55rem;
            margin-bottom: 0.75rem;
        }
        .rp-hero-title {
            font-size: 1.85rem;
            font-weight: 700;
            letter-spacing: -0.03em;
            color: #111827;
            margin: 0 0 0.5rem 0;
            line-height: 1.2;
        }
        .rp-hero-value {
            font-size: 1rem;
            color: #4b5563;
            margin: 0 0 1.25rem 0;
            line-height: 1.55;
            max-width: 560px;
        }
        .rp-cta-panel {
            background: #fafafa;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 1.15rem 1.25rem 0.5rem;
            margin-bottom: 1.75rem;
        }
        .rp-cta-label {
            font-size: 0.78rem;
            font-weight: 600;
            color: #374151;
            margin: 0 0 0.75rem 0;
            letter-spacing: 0.01em;
        }
        .rp-workflow-banner {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.35rem;
            padding: 0.85rem 1rem;
            background: #fff;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            margin-bottom: 1.75rem;
            overflow-x: auto;
        }
        .rp-wf-step {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 0.3rem;
            min-width: 4.5rem;
            flex-shrink: 0;
        }
        .rp-wf-icon {
            width: 2rem;
            height: 2rem;
            border-radius: 8px;
            background: #f3f4f6;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.85rem;
            color: #374151;
        }
        .rp-wf-label {
            font-size: 0.72rem;
            font-weight: 500;
            color: #6b7280;
            white-space: nowrap;
        }
        .rp-wf-arrow {
            color: #d1d5db;
            font-size: 0.85rem;
            flex-shrink: 0;
            padding-bottom: 1.1rem;
        }
        .rp-designed-label {
            font-size: 0.78rem;
            font-weight: 600;
            color: #9ca3af;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            margin: 0 0 0.75rem 0;
        }
        .rp-feature-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.65rem;
            margin-bottom: 0.5rem;
        }
        @media (max-width: 640px) {
            .rp-feature-grid { grid-template-columns: 1fr; }
        }
        .rp-feature-card {
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 0.9rem 1rem;
            background: #fff;
        }
        .rp-feature-card strong {
            display: block;
            font-size: 0.88rem;
            font-weight: 600;
            color: #111827;
            margin-bottom: 0.25rem;
        }
        .rp-feature-card span {
            font-size: 0.8rem;
            color: #6b7280;
            line-height: 1.45;
        }
        .rp-results-header {
            font-size: 0.82rem;
            font-weight: 600;
            color: #6b7280;
            margin-bottom: 1rem;
            letter-spacing: 0.02em;
        }
        .rp-brand {
            font-size: 1.35rem;
            font-weight: 600;
            letter-spacing: -0.02em;
            color: #111827;
            margin: 0 0 0.35rem 0;
        }
        .rp-subtitle {
            color: #6b7280;
            font-size: 0.95rem;
            margin: 0 0 2rem 0;
            line-height: 1.5;
        }
        .rp-input-panel {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2.5rem;
        }
        .rp-section {
            margin-bottom: 1.75rem;
        }
        .rp-section-head {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            margin-bottom: 1rem;
        }
        .rp-section-num {
            font-size: 0.8rem;
            font-weight: 600;
            color: #6b7280;
            background: #f3f4f6;
            border-radius: 6px;
            padding: 0.2rem 0.55rem;
            letter-spacing: 0.02em;
        }
        .rp-section-title {
            font-size: 1rem;
            font-weight: 600;
            color: #111827;
            margin: 0;
        }
        .rp-checklist {
            list-style: none;
            padding: 0;
            margin: 0;
        }
        .rp-check-item {
            display: flex;
            align-items: flex-start;
            gap: 0.75rem;
            padding: 0.85rem 0;
            border-bottom: 1px solid #f3f4f6;
        }
        .rp-check-item:last-child { border-bottom: none; }
        .rp-check-box {
            flex-shrink: 0;
            width: 1.1rem;
            height: 1.1rem;
            border-radius: 4px;
            margin-top: 0.15rem;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.7rem;
        }
        .rp-check-box.pending {
            border: 1.5px solid #d1d5db;
            background: #fff;
        }
        .rp-check-box.done {
            background: #111827;
            color: #fff;
            border: none;
        }
        .rp-check-text strong {
            display: block;
            color: #111827;
            font-size: 0.92rem;
            font-weight: 500;
            margin-bottom: 0.15rem;
        }
        .rp-check-text span {
            color: #6b7280;
            font-size: 0.85rem;
            line-height: 1.45;
        }
        .rp-agent-panel {
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 1.1rem 1.2rem;
            background: #fff;
            margin-bottom: 1.25rem;
        }
        .rp-agent-topic {
            font-size: 0.88rem;
            color: #374151;
            margin: 0 0 0.85rem 0;
        }
        .rp-agent-topic strong { color: #111827; }
        .rp-progress-track {
            height: 4px;
            background: #e5e7eb;
            border-radius: 2px;
            overflow: hidden;
            margin-bottom: 1rem;
        }
        .rp-progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #16a34a, #22c55e);
            border-radius: 2px;
            transition: width 0.4s ease;
        }
        .rp-progress-label {
            font-size: 0.75rem;
            color: #9ca3af;
            margin: -0.55rem 0 0.85rem 0;
            text-align: right;
        }
        .rp-agent-timeline {
            display: flex;
            flex-direction: column;
            gap: 0.15rem;
        }
        .rp-agent-stage {
            display: flex;
            align-items: center;
            gap: 0.65rem;
            padding: 0.55rem 0.4rem;
            border-radius: 8px;
            font-size: 0.9rem;
            transition: background 0.2s;
        }
        .rp-agent-stage.pending {
            color: #d1d5db;
        }
        .rp-agent-stage.active {
            color: #111827;
            background: #f9fafb;
        }
        .rp-agent-stage.done {
            color: #374151;
        }
        .rp-agent-status {
            width: 1.35rem;
            text-align: center;
            flex-shrink: 0;
            font-size: 0.9rem;
        }
        .rp-agent-stage.done .rp-agent-status {
            color: #16a34a;
            font-weight: 700;
        }
        .rp-agent-spinner {
            display: inline-block;
            width: 14px;
            height: 14px;
            border: 2px solid #e5e7eb;
            border-top-color: #111827;
            border-radius: 50%;
            animation: rp-spin 0.8s linear infinite;
        }
        @keyframes rp-spin {
            to { transform: rotate(360deg); }
        }
        .rp-agent-label { font-weight: 450; }
        .rp-panel-label {
            font-size: 0.78rem;
            font-weight: 600;
            color: #9ca3af;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin: 0 0 0.65rem 0;
        }
        .rp-evidence-card.new {
            animation: rp-fade-in 0.35s ease;
        }
        @keyframes rp-fade-in {
            from { opacity: 0; transform: translateY(6px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .rp-report-reveal {
            animation: rp-fade-in 0.5s ease;
        }
        .rp-evidence-card {
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 1rem 1.15rem;
            margin-bottom: 0.65rem;
            background: #fff;
        }
        .rp-evidence-card:last-child { margin-bottom: 0; }
        .rp-evidence-title {
            font-size: 0.92rem;
            font-weight: 500;
            color: #111827;
            margin: 0 0 0.35rem 0;
            line-height: 1.4;
        }
        .rp-evidence-meta {
            font-size: 0.78rem;
            color: #9ca3af;
            margin-bottom: 0.5rem;
        }
        .rp-evidence-meta a {
            color: #6b7280;
            text-decoration: none;
        }
        .rp-evidence-meta a:hover { text-decoration: underline; }
        .rp-evidence-summary {
            font-size: 0.85rem;
            color: #4b5563;
            line-height: 1.5;
            margin: 0;
        }
        .rp-read-status {
            font-size: 0.78rem;
            margin: 0 0 0.45rem 0;
        }
        .rp-read-ok {
            color: #15803d;
            font-weight: 500;
        }
        .rp-read-fallback {
            color: #b45309;
            font-weight: 500;
        }
        .rp-score-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem;
            margin: 0 0 0.45rem 0;
            font-size: 0.75rem;
        }
        .rp-score {
            background: #f3f4f6;
            color: #374151;
            border-radius: 4px;
            padding: 0.15rem 0.45rem;
            font-weight: 500;
        }
        .rp-score.final {
            background: #ecfdf5;
            color: #047857;
        }
        .rp-report-block {
            border-top: 1px solid #f3f4f6;
            padding-top: 1.25rem;
            margin-top: 1.25rem;
        }
        .rp-report-block:first-child {
            border-top: none;
            padding-top: 0;
            margin-top: 0;
        }
        .rp-report-heading {
            font-size: 0.95rem;
            font-weight: 600;
            color: #111827;
            margin: 0 0 0.6rem 0;
        }
        .rp-report-body {
            font-size: 0.88rem;
            color: #374151;
            line-height: 1.65;
        }
        div[data-testid="stButton"] button {
            background: #111827;
            color: #fff;
            border: none;
            border-radius: 8px;
            padding: 0.55rem 1.5rem;
            font-weight: 500;
            font-size: 0.9rem;
        }
        div[data-testid="stButton"] button:hover {
            background: #1f2937;
            color: #fff;
            border: none;
        }
        div[data-testid="stTextInput"] label,
        div[data-testid="stSelectbox"] label {
            font-size: 0.82rem;
            font-weight: 500;
            color: #374151;
        }
        .rp-cta-panel div[data-testid="stTextInput"],
        .rp-cta-panel div[data-testid="stSelectbox"] {
            margin-bottom: 0.35rem;
        }
        .rp-cta-panel div[data-testid="column"] {
            padding: 0 0.25rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

DESIGNED_FOR_CARDS: list[tuple[str, str]] = [
    (
        "A-share Industry Research",
        "Track sectors, themes, and listed companies across China's A-share market.",
    ),
    (
        "Industry Chain Analysis",
        "Map upstream suppliers, midstream manufacturers, and downstream applications.",
    ),
    (
        "Multi-source Evidence",
        "Collect and cite findings from reports, news, and analyst publications.",
    ),
    (
        "AI-powered Reports",
        "Generate structured reports with summaries, drivers, risks, and citations.",
    ),
]

LANDING_WORKFLOW: list[tuple[str, str]] = [
    ("📋", "Planning"),
    ("🔍", "Search"),
    ("📖", "Read"),
    ("📊", "Analyze"),
    ("📄", "Report"),
]

# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------



def render_plan_checklist(plan: ResearchPlan, checked: int | None = None) -> str:
    """Render research plan steps as an HTML checklist.

    Args:
        plan: The research plan to display.
        checked: Number of items to mark as done. None marks all as done.
    """
    total = len(plan.steps)
    done_count = total if checked is None else min(checked, total)

    items = []
    for step in plan.steps:
        is_done = step.order <= done_count
        box_class = "done" if is_done else "pending"
        box_content = "✓" if is_done else ""
        items.append(
            f'<li class="rp-check-item">'
            f'<div class="rp-check-box {box_class}">{box_content}</div>'
            f'<div class="rp-check-text">'
            f"<strong>{step.title}</strong>"
            f"<span>{step.description}</span>"
            f"</div></li>"
        )

    return (
        f'<ul class="rp-checklist">{"".join(items)}</ul>'
    )


def render_progress_bar(completed_stages: int, total_stages: int) -> str:
    """Render a horizontal progress bar for agent stages."""
    pct = int((completed_stages / total_stages) * 100) if total_stages else 0
    return (
        f'<div class="rp-progress-track">'
        f'<div class="rp-progress-fill" style="width:{pct}%;"></div>'
        f"</div>"
        f'<p class="rp-progress-label">{pct}% complete</p>'
    )


def render_agent_timeline(active_index: int) -> str:
    """Render the agent workflow timeline with checkmarks and active spinner.

    Args:
        active_index: Index of the active stage. -1 means all stages complete.
    """
    rows = []
    for i, (_, label) in enumerate(AGENT_STAGES):
        if active_index < 0 or i < active_index:
            state, status = "done", "✓"
        elif i == active_index:
            state, status = "active", '<span class="rp-agent-spinner"></span>'
        else:
            state, status = "pending", ""

        rows.append(
            f'<div class="rp-agent-stage {state}">'
            f'<span class="rp-agent-status">{status}</span>'
            f'<span class="rp-agent-label">{label}</span>'
            f"</div>"
        )

    return f'<div class="rp-agent-timeline">{"".join(rows)}</div>'


def render_agent_panel(topic: str, active_index: int, query_type: str | None = None) -> str:
    """Render the full agent progress panel."""
    total = len(AGENT_STAGES)
    completed = total if active_index < 0 else active_index
    type_part = f" · {query_type}" if query_type else ""
    return (
        f'<div class="rp-agent-panel">'
        f'<p class="rp-agent-topic">Researching <strong>{topic}</strong>{type_part}</p>'
        f"{render_progress_bar(completed, total)}"
        f"{render_agent_timeline(active_index)}"
        f"</div>"
    )


def render_evidence_cards(
    items: list[EvaluatedEvidence],
    highlight_last: bool = False,
) -> str:
    """Render evaluated evidence as cards with read status and quality scores."""
    if not items:
        return ""

    cards = []
    for i, item in enumerate(items):
        doc = item.document
        source = doc.source
        new_class = " new" if highlight_last and i == len(items) - 1 else ""
        date_part = f" · {source.published_date}" if source.published_date else ""

        if doc.read_status == "success":
            status_html = (
                f'<span class="rp-read-ok">Read · {doc.word_count} words</span>'
            )
        else:
            reason = doc.error_message or "fetch failed"
            status_html = (
                f'<span class="rp-read-fallback">Snippet fallback · {doc.word_count} words</span>'
                f'<span class="rp-read-error"> — {reason}</span>'
            )

        excerpt = (doc.extracted_text or source.snippet or "")[:280]
        if doc.extracted_text and len(doc.extracted_text) > 280:
            excerpt = excerpt.rsplit(" ", 1)[0] + "…"

        scores_html = (
            f'<div class="rp-score-row">'
            f'<span class="rp-score">Credibility {item.credibility_score}</span>'
            f'<span class="rp-score">Relevance {item.relevance_score}</span>'
            f'<span class="rp-score final">Final {item.final_score}</span>'
            f"</div>"
        )

        provenance = ""
        if source.research_task or source.search_query:
            provenance = (
                f'<p class="rp-evidence-meta">'
                f"task: {source.research_task or '—'} · "
                f"query: {source.search_query or '—'}"
                f"</p>"
            )

        cards.append(
            f'<div class="rp-evidence-card{new_class}">'
            f'<p class="rp-evidence-title">{source.title}</p>'
            f'<p class="rp-evidence-meta">'
            f"{source.source_type}{date_part} · "
            f'<a href="{source.url}" target="_blank">{source.url}</a>'
            f"</p>"
            f"{provenance}"
            f"{scores_html}"
            f'<p class="rp-read-status">{status_html}</p>'
            f'<p class="rp-evidence-summary">{excerpt}</p>'
            f"</div>"
        )

    return "".join(cards)


def _report_body_html(content: str) -> str:
    """Escape report markdown-ish text for safe HTML display."""
    import html as _html

    text = _html.escape(content or "")
    # Basic markdown-ish affordances used by the Writer.
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(
        r"\[(E\d+)\]",
        r'<span class="rp-cite">[\1]</span>',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        text,
    )
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return ""
    rendered = []
    for para in paragraphs:
        # Preserve single newlines / bullet lines inside a block.
        para = para.replace("\n", "<br>")
        rendered.append(f"<p>{para}</p>")
    return "".join(rendered)


def render_final_report(report: ResearchReport) -> str:
    """Render the structured research report as a document."""
    blocks = []
    for section in report.sections:
        blocks.append(
            f'<div class="rp-report-block">'
            f'<p class="rp-report-heading">{section.title}</p>'
            f'<div class="rp-report-body">{_report_body_html(section.content)}</div>'
            f"</div>"
        )

    return "".join(blocks)


def _sleep_remaining(start: float, minimum: float) -> None:
    """Sleep until at least `minimum` seconds have elapsed since `start`."""
    elapsed = time.time() - start
    if elapsed < minimum:
        time.sleep(minimum - elapsed)


def _format_grounded_findings(items, *, is_gap_section: bool = False) -> str:
    if not items:
        return (
            "_No evidence gaps recorded._"
            if is_gap_section
            else "_No grounded findings for this section (see evidence_gaps)._"
        )
    lines = []
    for item in items:
        ids = ", ".join(item.evidence_ids) if item.evidence_ids else "none"
        finding_type = getattr(item, "finding_type", None) or item.kind or "supported_fact"
        if is_gap_section or finding_type == "gap":
            lines.append(f"- {item.finding}")
        else:
            lines.append(f"- (`{finding_type}`) {item.finding} — evidence: `{ids}`")
            for ex in getattr(item, "supporting_excerpts", []) or []:
                lines.append(
                    f"  - `{ex.evidence_id}` · [{ex.source_title}]({ex.source_url})  \n"
                    f"    > {ex.excerpt}"
                )
    return "\n".join(lines)


def render_pipeline_warnings(result: ResearchResult) -> None:
    """Surface user-relevant fallback warnings without internal diagnostics."""
    for warning in (
        result.planner_warning,
        result.search_warning,
        result.synthesizer_warning,
        result.writer_warning,
    ):
        if warning:
            st.warning(warning)


def render_synthesis_brief(result: ResearchResult) -> None:
    """Show grounded SynthesisBrief sections before the final report."""
    synthesis = result.synthesis
    if synthesis is None:
        st.warning("SynthesisBrief unavailable.")
        return

    st.markdown('<p class="rp-panel-label">Synthesis Brief</p>', unsafe_allow_html=True)

    if synthesis.evidence_index:
        with st.expander("Evidence ID index", expanded=False):
            for eid, item in synthesis.evidence_index.items():
                src = item.source
                st.markdown(
                    f"- `{eid}` · score={item.final_score} · [{src.title}]({src.url})"
                )

    sections = [
        ("key_findings", synthesis.key_findings),
        ("industry_chain_findings", synthesis.industry_chain_findings),
        ("demand_supply_drivers", synthesis.demand_supply_drivers),
        ("technology_findings", synthesis.technology_findings),
        ("catalysts", synthesis.catalysts),
        ("company_findings", synthesis.company_findings),
        ("risks", synthesis.risks),
        ("evidence_gaps", synthesis.evidence_gaps),
    ]
    for title, items in sections:
        with st.expander(f"{title} ({len(items)})", expanded=(title == "key_findings")):
            st.markdown(
                _format_grounded_findings(items, is_gap_section=(title == "evidence_gaps"))
            )


def run_animated_workflow(topic: str, depth: ResearchDepth) -> ResearchResult:
    """Execute research with a progressive AI-agent-style UI workflow."""
    result = run_research(topic, depth)

    render_pipeline_warnings(result)

    query_type = (
        result.plan.query_type.value
        if getattr(result.plan, "query_type", None)
        else None
    )
    if result.analyzed_query and result.analyzed_query.research_goal:
        st.caption(result.analyzed_query.research_goal)

    agent_slot = st.empty()
    plan_slot = st.empty()
    evidence_slot = st.empty()
    report_slot = st.empty()

    sources_revealed = 0
    docs = result.documents or []
    evidence_items = result.evidence or []
    search_target = (len(evidence_items) + 1) // 2 if evidence_items else (len(docs) + 1) // 2
    reveal_total = len(evidence_items) if evidence_items else len(docs)

    for stage_index, (stage_key, _) in enumerate(AGENT_STAGES):
        stage_start = time.time()

        agent_slot.markdown(
            render_agent_panel(result.plan.topic, stage_index, query_type),
            unsafe_allow_html=True,
        )

        if stage_key == "planning":
            plan_slot.markdown(
                f'<p class="rp-panel-label">Research Plan</p>'
                f"{render_plan_checklist(result.plan)}",
                unsafe_allow_html=True,
            )
            _sleep_remaining(stage_start, STAGE_DELAY)

        elif stage_key == "searching":
            sources_revealed = min(search_target, reveal_total)
            subset = evidence_items[:sources_revealed] if evidence_items else []
            if evidence_items:
                evidence_slot.markdown(
                    f'<p class="rp-panel-label">Evidence · discovering sources...</p>'
                    f"{render_evidence_cards(subset)}",
                    unsafe_allow_html=True,
                )
            _sleep_remaining(stage_start, STAGE_DELAY)

        elif stage_key == "reading":
            while sources_revealed < reveal_total:
                sources_revealed += 1
                subset = (
                    evidence_items[:sources_revealed]
                    if evidence_items
                    else []
                )
                ok_count = sum(
                    1
                    for e in subset
                    if getattr(e.document, "read_status", "") == "success"
                )
                evidence_slot.markdown(
                    f'<p class="rp-panel-label">Evidence · {sources_revealed}/{reveal_total}'
                    f' · {ok_count} read</p>'
                    f"{render_evidence_cards(subset)}",
                    unsafe_allow_html=True,
                )
                time.sleep(EVIDENCE_REVEAL_DELAY)
            _sleep_remaining(stage_start, STAGE_DELAY)

        else:
            time.sleep(STAGE_DELAY)

        agent_slot.markdown(
            render_agent_panel(result.plan.topic, stage_index + 1, query_type),
            unsafe_allow_html=True,
        )

    agent_slot.markdown(
        render_agent_panel(result.plan.topic, -1, query_type),
        unsafe_allow_html=True,
    )

    plan_slot.markdown(
        f'<p class="rp-panel-label">Research Plan</p>'
        f"{render_plan_checklist(result.plan)}",
        unsafe_allow_html=True,
    )

    ok_count = sum(1 for d in docs if d.read_status == "success")
    evidence_slot.markdown(
        f'<p class="rp-panel-label">Evidence · {len(evidence_items)} sources · {ok_count} read · ranked by score</p>'
        f"{render_evidence_cards(evidence_items)}",
        unsafe_allow_html=True,
    )

    render_synthesis_brief(result)

    report_slot.markdown(
        f'<div class="rp-report-reveal">'
        f'<p class="rp-panel-label">Final Research Report</p>'
        f"{render_final_report(result.report)}"
        f"</div>",
        unsafe_allow_html=True,
    )

    return result


def render_workflow_banner() -> None:
    """Render the horizontal product workflow visual."""
    steps_html = []
    for i, (icon, label) in enumerate(LANDING_WORKFLOW):
        if i > 0:
            steps_html.append('<span class="rp-wf-arrow">→</span>')
        steps_html.append(
            f'<div class="rp-wf-step">'
            f'<div class="rp-wf-icon">{icon}</div>'
            f'<span class="rp-wf-label">{label}</span>'
            f"</div>"
        )

    st.markdown(
        f'<div class="rp-workflow-banner">{"".join(steps_html)}</div>',
        unsafe_allow_html=True,
    )


def render_designed_for() -> None:
    """Render the Designed For feature card grid."""
    cards = "".join(
        f'<div class="rp-feature-card"><strong>{title}</strong><span>{desc}</span></div>'
        for title, desc in DESIGNED_FOR_CARDS
    )
    st.markdown(
        f'<p class="rp-designed-label">Designed For</p>'
        f'<div class="rp-feature-grid">{cards}</div>',
        unsafe_allow_html=True,
    )


def render_hero_and_form() -> tuple[str, str, bool]:
    """Render hero, value proposition, and the research input form.

    Returns:
        Tuple of (topic, depth_label, submitted).
    """
    st.markdown(
        """
        <div class="rp-hero">
            <span class="rp-hero-badge">ResearchPilot · AI Industry Research Agent</span>
            <p class="rp-hero-title">Turn any industry topic into<br>a cited research report.</p>
            <p class="rp-hero-value">
                ResearchPilot autonomously plans your research, gathers multi-source
                evidence, and delivers structured industry analysis — so you spend
                less time searching and more time deciding.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="rp-cta-panel"><p class="rp-cta-label">Start a research task</p></div>',
        unsafe_allow_html=True,
    )

    with st.form("research_form", clear_on_submit=False):
        topic = st.text_input(
            "Research Topic",
            placeholder="e.g. liquid cooling, PCB industry chain, AI glasses",
            label_visibility="collapsed",
        )
        col1, col2 = st.columns([2, 1])
        with col1:
            depth_label = st.selectbox(
                "Research Depth",
                options=[d.value for d in ResearchDepth],
                index=1,
                label_visibility="collapsed",
            )
        with col2:
            submitted = st.form_submit_button("Start Research", use_container_width=True)

    return topic, depth_label, submitted


def render_landing_extras() -> None:
    """Render workflow visual and Designed For cards below the form."""
    render_workflow_banner()
    render_designed_for()


def render_completed_workflow(result: ResearchResult) -> None:
    """Render all sections in their completed state (no animation)."""
    render_pipeline_warnings(result)

    docs = result.documents or []
    evidence_items = result.evidence or []
    ok_count = sum(1 for d in docs if d.read_status == "success")
    query_type = (
        result.plan.query_type.value
        if getattr(result.plan, "query_type", None)
        else None
    )

    if result.analyzed_query and result.analyzed_query.research_goal:
        st.caption(result.analyzed_query.research_goal)

    st.markdown(
        render_agent_panel(result.plan.topic, -1, query_type),
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<p class="rp-panel-label">Research Plan</p>'
        f"{render_plan_checklist(result.plan)}",
        unsafe_allow_html=True,
    )

    st.markdown(
        f'<p class="rp-panel-label">Evidence · {len(evidence_items)} sources · {ok_count} read · ranked by score</p>'
        f"{render_evidence_cards(evidence_items)}",
        unsafe_allow_html=True,
    )

    render_synthesis_brief(result)

    st.markdown(
        f'<p class="rp-panel-label">Final Research Report</p>'
        f"{render_final_report(result.report)}",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Page routing
# ---------------------------------------------------------------------------

if "result" in st.session_state:
    st.markdown(
        '<p class="rp-results-header">ResearchPilot · Latest Results</p>',
        unsafe_allow_html=True,
    )
    render_completed_workflow(st.session_state["result"])
else:
    topic, depth_label, submitted = render_hero_and_form()

    if submitted:
        if not topic or not topic.strip():
            st.error("Please enter a research topic before starting.")
            render_landing_extras()
        else:
            depth = ResearchDepth(depth_label)
            try:
                st.markdown(
                    '<p class="rp-results-header">ResearchPilot · Research in Progress</p>',
                    unsafe_allow_html=True,
                )
                result = run_animated_workflow(topic.strip(), depth)
                st.session_state["result"] = result
            except ValueError as exc:
                st.error(str(exc))
                render_landing_extras()
    else:
        render_landing_extras()
