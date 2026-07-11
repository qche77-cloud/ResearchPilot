"""Writer — format a grounded SynthesisBrief into the final research report.

Responsibility
--------------
Own *only* report composition and presentation. Given a research plan and
``SynthesisBrief``, produce a Chinese A-share ``ResearchReport``. Does not
plan, search, or invent analytical claims beyond the Synthesizer output.

Uses OpenAI (``OPENAI_API_KEY``, ``LLM_MODEL``) when available. On failure,
falls back to a deterministic formatting of the grounded brief — never the
old mocked report and never fictional companies/facts.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request

from src.env import load_env
from src.models import (
    GroundedFinding,
    ReportSection,
    ResearchPlan,
    ResearchReport,
    SynthesisBrief,
)

logger = logging.getLogger(__name__)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_LLM_MODEL = "gpt-4o-mini"
OPENAI_TIMEOUT_SECONDS = 90

PREFERRED_SECTIONS: tuple[str, ...] = (
    "核心结论",
    "行业/主题概览",
    "产业链拆解",
    "供需驱动",
    "技术趋势",
    "近期催化",
    "A股相关公司",
    "风险与不确定性",
    "证据缺口",
    "Sources",
)

BRIEF_TO_REPORT: tuple[tuple[str, str], ...] = (
    ("key_findings", "核心结论"),
    ("industry_chain_findings", "产业链拆解"),
    ("demand_supply_drivers", "供需驱动"),
    ("technology_findings", "技术趋势"),
    ("catalysts", "近期催化"),
    ("company_findings", "A股相关公司"),
    ("risks", "风险与不确定性"),
    ("evidence_gaps", "证据缺口"),
)

CONTENT_BRIEF_KEYS: tuple[str, ...] = (
    "key_findings",
    "industry_chain_findings",
    "demand_supply_drivers",
    "technology_findings",
    "catalysts",
    "company_findings",
    "risks",
    "evidence_gaps",
)

_FICTIONAL_MARKERS = (
    "Alpha Corp",
    "NovaTech",
    "Beta Industries",
    "Example Corp",
    "示例公司A",
    "虚构公司",
)

_GAP_HINT_SNIPPETS = (
    "缺少可核验",
    "缺少可用于",
    "缺少供需",
    "缺少关键技术",
    "缺少涨价",
    "缺少可映射",
    "证据不足",
    "evidence is insufficient",
    "无 grounded findings",
)


class Writer:
    """Write the final structured research report from a grounded synthesis brief."""

    def __init__(self) -> None:
        self.last_warning: str | None = None
        self.last_diagnostics: dict = {}
        load_env()

    def write(
        self,
        plan: ResearchPlan,
        synthesis: SynthesisBrief,
    ) -> ResearchReport:
        """Compose the user-facing research report from plan + grounded brief."""
        self.last_warning = None
        self.last_diagnostics = {}
        load_env()

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            self.last_warning = (
                "API key not found. OPENAI_API_KEY missing; writer fallback "
                "formats SynthesisBrief directly (no invented content)."
            )
            report = self._fallback_report(plan, synthesis, reason="API key not found")
            self._set_diagnostics(report, synthesis, source="fallback")
            return report

        try:
            report = self._llm_write(plan, synthesis, api_key)
            self.last_warning = None
            self._set_diagnostics(report, synthesis, source="llm")
            return report
        except Exception as exc:  # noqa: BLE001
            reason = _classify_openai_error(exc)
            self.last_warning = (
                f"{reason}. Writer fallback used — SynthesisBrief formatted "
                "directly; no invented companies or facts."
            )
            logger.warning("Writer fallback: %s | detail=%s", reason, exc)
            report = self._fallback_report(plan, synthesis, reason=reason)
            self._set_diagnostics(report, synthesis, source="fallback")
            return report

    def _set_diagnostics(
        self,
        report: ResearchReport,
        synthesis: SynthesisBrief,
        *,
        source: str,
    ) -> None:
        cited = _collect_cited_evidence_ids(report)
        self.last_diagnostics = {
            "writer_source": source,
            "grounded_findings_received": _count_grounded_findings(synthesis),
            "evidence_sources_cited": len(cited),
            "cited_evidence_ids": sorted(cited),
            "sections_written": [s.title for s in report.sections],
            "writer_warning": self.last_warning,
        }
        report.writer_source = source

    def _llm_write(
        self,
        plan: ResearchPlan,
        synthesis: SynthesisBrief,
        api_key: str,
    ) -> ResearchReport:
        model = os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL).strip() or DEFAULT_LLM_MODEL
        payload = {
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": _user_prompt(plan, synthesis)},
            ],
        }

        request = urllib.request.Request(
            OPENAI_CHAT_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=OPENAI_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")

        data = json.loads(body)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("invalid response format") from exc

        parsed = _parse_llm_json(content)
        return self._report_from_llm_json(plan, synthesis, parsed)

    def _report_from_llm_json(
        self,
        plan: ResearchPlan,
        synthesis: SynthesisBrief,
        data: dict,
    ) -> ResearchReport:
        valid_ids = set(synthesis.evidence_index.keys())
        raw_sections = data.get("sections") or []
        if not isinstance(raw_sections, list):
            raise RuntimeError("invalid response format: sections must be a list")

        by_title: dict[str, str] = {}
        orphan_gaps: list[str] = []

        for item in raw_sections:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            content = str(item.get("content") or "").strip()
            if not title or not content:
                continue
            if title == "Sources":
                continue
            if _contains_fictional_marker(content):
                raise RuntimeError("LLM output contained fictional placeholder companies")

            content = _sanitize_citations(content, valid_ids)
            content = _strip_trailing_gap_notes(content)
            if not content:
                continue

            if title != "证据缺口" and _is_gap_placeholder_content(content):
                orphan_gaps.append(content)
                continue

            by_title[title] = content

        sections: list[ReportSection] = []
        used_titles: set[str] = set()
        for title in PREFERRED_SECTIONS:
            if title == "Sources":
                continue
            content = by_title.pop(title, "").strip()
            if content:
                sections.append(ReportSection(title=title, content=content))
                used_titles.add(title)

        for title, content in by_title.items():
            if content.strip():
                sections.append(ReportSection(title=title, content=content.strip()))
                used_titles.add(title)

        # Backfill any brief sections the LLM omitted (content findings only).
        for brief_key, title in BRIEF_TO_REPORT:
            if title in used_titles:
                continue
            items: list[GroundedFinding] = getattr(synthesis, brief_key) or []
            if not items:
                continue
            # Skip content sections that only have gap-typed items.
            if brief_key != "evidence_gaps":
                items = [i for i in items if i.finding_type != "gap"]
            if not items:
                continue
            body = _format_findings_section(items, is_gap=(brief_key == "evidence_gaps"))
            if body.strip() and not (
                title != "证据缺口" and _is_gap_placeholder_content(body)
            ):
                sections.append(ReportSection(title=title, content=body))
                used_titles.add(title)

        # Merge orphan gap notes into 证据缺口.
        if orphan_gaps:
            existing = ""
            kept: list[ReportSection] = []
            for sec in sections:
                if sec.title == "证据缺口":
                    existing = sec.content
                else:
                    kept.append(sec)
            sections = kept
            gap_lines = []
            if existing:
                gap_lines.append(existing)
            for note in orphan_gaps:
                cleaned = note.strip().lstrip("- ").strip()
                if cleaned and cleaned not in "\n".join(gap_lines):
                    gap_lines.append(f"- {cleaned}")
            # Also include brief evidence_gaps if not already present.
            brief_gaps = _format_findings_section(
                getattr(synthesis, "evidence_gaps") or [], is_gap=True
            )
            if brief_gaps and brief_gaps not in "\n".join(gap_lines):
                gap_lines.append(brief_gaps)
            sections.append(ReportSection(title="证据缺口", content="\n".join(gap_lines)))
            used_titles.add("证据缺口")
        elif "证据缺口" not in used_titles and (synthesis.evidence_gaps or []):
            body = _format_findings_section(synthesis.evidence_gaps, is_gap=True)
            if body.strip():
                sections.append(ReportSection(title="证据缺口", content=body))

        order = {t: i for i, t in enumerate(PREFERRED_SECTIONS)}
        sections.sort(key=lambda s: order.get(s.title, 1000))

        # Prune evidence_gaps that contradict sections already written.
        present = {s.title for s in sections if s.title not in {"证据缺口", "Sources"}}
        pruned: list[ReportSection] = []
        for sec in sections:
            if sec.title == "证据缺口":
                cleaned = _prune_contradicted_gaps(sec.content, present)
                if cleaned:
                    pruned.append(ReportSection(title="证据缺口", content=cleaned))
            else:
                pruned.append(sec)
        sections = pruned

        if not sections:
            return self._fallback_report(plan, synthesis, reason="empty LLM sections")

        sections.append(
            ReportSection(title="Sources", content=_format_sources_section(synthesis))
        )

        return ResearchReport(
            topic=synthesis.topic,
            depth=synthesis.depth,
            sections=sections,
            writer_source="llm",
        )

    def _fallback_report(
        self,
        plan: ResearchPlan,
        synthesis: SynthesisBrief,
        *,
        reason: str,
    ) -> ResearchReport:
        """Deterministic formatting of the grounded brief — no invented facts."""
        sections: list[ReportSection] = []

        overview_bits = []
        analyzed = plan.analyzed_query
        if analyzed and analyzed.research_goal:
            overview_bits.append(f"研究目标：{analyzed.research_goal}")
        if plan.research_objective:
            overview_bits.append(f"研究目的：{plan.research_objective}")
        if overview_bits:
            sections.append(
                ReportSection(
                    title="行业/主题概览",
                    content=(
                        "\n\n".join(overview_bits)
                        + f"\n\n（报告由 SynthesisBrief 直接整理；Writer fallback：{reason}）"
                    ),
                )
            )

        for brief_key, title in BRIEF_TO_REPORT:
            items: list[GroundedFinding] = getattr(synthesis, brief_key) or []
            if not items:
                continue
            if brief_key != "evidence_gaps":
                items = [i for i in items if i.finding_type != "gap"]
            if not items:
                continue
            body = _format_findings_section(items, is_gap=(brief_key == "evidence_gaps"))
            if body.strip():
                sections.append(ReportSection(title=title, content=body))

        if not any(s.title not in {"行业/主题概览", "证据缺口"} for s in sections):
            sections.insert(
                0,
                ReportSection(
                    title="核心结论",
                    content=(
                        "当前 SynthesisBrief 无可写的 grounded findings；"
                        "请查看「证据缺口」与 Sources。"
                    ),
                ),
            )
            if not any(s.title == "证据缺口" for s in sections):
                sections.append(
                    ReportSection(
                        title="证据缺口",
                        content=f"- Writer fallback（{reason}）；无 grounded findings available.",
                    )
                )

        sections.append(
            ReportSection(title="Sources", content=_format_sources_section(synthesis))
        )

        return ResearchReport(
            topic=synthesis.topic,
            depth=synthesis.depth,
            sections=sections,
            writer_source="fallback",
        )


_SECTION_GAP_FILTER: dict[str, tuple[str, ...]] = {
    "核心结论": ("缺少可用于总览", "缺少可用于总览判断"),
    "产业链拆解": ("缺少可核验的上中下游", "缺少.*产业链"),
    "供需驱动": ("缺少供需",),
    "技术趋势": ("缺少关键技术",),
    "近期催化": ("缺少涨价", "缺少.*催化"),
    "A股相关公司": ("缺少可映射到A股", "缺少.*公司"),
    "风险与不确定性": ("缺少可核验的风险",),
}


def _prune_contradicted_gaps(
    gap_content: str,
    present_content_titles: set[str],
) -> str:
    """Drop gap bullets that contradict sections already written with evidence."""
    if not gap_content.strip():
        return gap_content
    lines = gap_content.splitlines()
    kept: list[str] = []
    for line in lines:
        drop = False
        for title, patterns in _SECTION_GAP_FILTER.items():
            if title not in present_content_titles:
                continue
            if any(re.search(p, line) for p in patterns):
                drop = True
                break
        if not drop:
            kept.append(line)
    return "\n".join(kept).strip()


def _count_grounded_findings(synthesis: SynthesisBrief) -> int:
    return sum(len(getattr(synthesis, key) or []) for key in CONTENT_BRIEF_KEYS)


def _format_findings_section(
    items: list[GroundedFinding],
    *,
    is_gap: bool = False,
) -> str:
    lines: list[str] = []
    for item in items:
        text = (item.finding or "").strip()
        if not text:
            continue
        if is_gap or item.finding_type == "gap":
            lines.append(f"- {text}")
            continue

        ids = "".join(f"[{eid}]" for eid in item.evidence_ids) or ""
        if item.finding_type == "inference":
            clean = re.sub(r"^\[Inference\]\s*", "", text).strip()
            if not clean.startswith("基于现有证据推断"):
                clean = f"基于现有证据推断，{clean}"
            lines.append(f"- {clean}{ids}")
        else:
            lines.append(f"- {text}{ids}")
    return "\n".join(lines)


def _format_sources_section(synthesis: SynthesisBrief) -> str:
    """Build Sources from evidence_index (preferred) or cited_evidence."""
    lines: list[str] = []
    index = synthesis.evidence_index or {}
    if index:

        def _eid_key(eid: str) -> tuple[int, str]:
            m = re.match(r"^E(\d+)$", eid, flags=re.IGNORECASE)
            return (int(m.group(1)), eid) if m else (10**9, eid)

        for eid in sorted(index.keys(), key=_eid_key):
            source = index[eid].source
            lines.append(f"[{eid}] {source.title} — {source.url}")
        return "\n".join(lines)

    for i, item in enumerate(synthesis.cited_evidence, start=1):
        source = item.source
        lines.append(f"[E{i}] {source.title} — {source.url}")
    return "\n".join(lines) if lines else "_No sources retained._"


def _serialize_brief_for_prompt(synthesis: SynthesisBrief) -> str:
    payload: dict = {}
    for key in CONTENT_BRIEF_KEYS:
        items: list[GroundedFinding] = getattr(synthesis, key) or []
        payload[key] = [
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
            for f in items
        ]

    evidence_map = {}
    for eid, item in (synthesis.evidence_index or {}).items():
        evidence_map[eid] = {
            "title": item.source.title,
            "url": item.source.url,
            "source_type": item.source.source_type,
            "published_date": item.source.published_date,
            "final_score": item.final_score,
        }
    payload["evidence_index"] = evidence_map
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _system_prompt() -> str:
    return """You are ResearchPilot's report Writer for China A-share research.

Your job is PRESENTATION and ORGANIZATION only — not independent research.

Hard rules:
1. Use ONLY information in the supplied SynthesisBrief (findings + excerpts + evidence IDs).
2. Do NOT introduce new facts, companies, financial figures, dates, policies, orders, catalysts, or market events absent from the brief.
3. Do NOT use model knowledge to fill evidence gaps.
4. Write a concise analytical Chinese A-share research report.
5. Cite evidence inline with IDs, e.g. …构成。[E1] or …构成。[E1][E2]
6. For finding_type=inference, use wording like “基于现有证据推断……”
7. Omit sections with no grounded findings. Do NOT write “缺少…证据” inside content sections — put those only under 证据缺口.
8. Avoid generic boilerplate unless the brief directly supports it.
9. Never invent placeholder companies (Alpha Corp, NovaTech, etc.).
10. Do NOT write the Sources section yourself — the system will append it.

Return ONLY valid JSON:
{
  "sections": [
    {"title": "核心结论", "content": "……[E1]"},
    {"title": "产业链拆解", "content": "……"}
  ]
}

Preferred titles (include only when supported by the brief):
核心结论, 行业/主题概览, 产业链拆解, 供需驱动, 技术趋势, 近期催化, A股相关公司, 风险与不确定性, 证据缺口
"""


def _user_prompt(plan: ResearchPlan, synthesis: SynthesisBrief) -> str:
    analyzed = plan.analyzed_query
    raw_query = analyzed.raw_query if analyzed else plan.topic
    query_type = (
        (analyzed.query_type.value if analyzed and analyzed.query_type else None)
        or (plan.query_type.value if plan.query_type else "industry")
    )
    objective = plan.research_objective or plan.research_goal or ""
    strategy = plan.research_strategy or ""

    return (
        f"User query: {raw_query}\n"
        f"Normalized topic: {plan.topic}\n"
        f"Query type: {query_type}\n"
        f"Research objective: {objective}\n"
        f"Research strategy: {strategy}\n\n"
        f"Grounded SynthesisBrief JSON:\n"
        f"{_serialize_brief_for_prompt(synthesis)}\n\n"
        "Write the Chinese research report JSON now. "
        "Every factual claim must be traceable to evidence_ids in the brief. "
        "Omit empty content sections; list missing areas only under 证据缺口."
    )


def _parse_llm_json(content: str) -> dict:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise RuntimeError("invalid response format")
    return data


def _is_gap_placeholder_content(content: str) -> bool:
    """True when a section body is only an insufficient-evidence note."""
    text = (content or "").strip()
    if not text:
        return True
    compact = re.sub(r"^[\-\*\s]+", "", text, flags=re.MULTILINE).strip()
    lower = compact.lower()
    if any(s.lower() in lower for s in _GAP_HINT_SNIPPETS):
        if "[" not in compact or len(compact) < 80:
            return True
        lines = [ln.strip(" -•\t") for ln in compact.splitlines() if ln.strip()]
        if lines and all(any(s in ln for s in _GAP_HINT_SNIPPETS) for ln in lines):
            return True
    return False


def _strip_trailing_gap_notes(content: str) -> str:
    """Remove appended gap-hint sentences from otherwise valid section bodies."""
    text = (content or "").strip()
    if not text:
        return text
    parts = re.split(r"(?<=[。；\n])", text)
    kept: list[str] = []
    for part in parts:
        if not part.strip():
            continue
        if any(s in part for s in _GAP_HINT_SNIPPETS) and "[" not in part:
            continue
        kept.append(part)
    return "".join(kept).strip()


def _sanitize_citations(content: str, valid_ids: set[str]) -> str:
    """Drop citation markers that are not in the evidence index."""

    def _repl(match: re.Match[str]) -> str:
        eid = match.group(1).upper()
        return f"[{eid}]" if eid in valid_ids else ""

    return re.sub(r"\[(E\d+)\]", _repl, content, flags=re.IGNORECASE)


def _contains_fictional_marker(text: str) -> bool:
    lower = text.lower()
    for marker in _FICTIONAL_MARKERS:
        if marker.lower() in lower or marker in text:
            return True
    return False


def _collect_cited_evidence_ids(report: ResearchReport) -> set[str]:
    cited: set[str] = set()
    for section in report.sections:
        if section.title == "Sources":
            continue
        for match in re.finditer(r"\[(E\d+)\]", section.content or "", flags=re.IGNORECASE):
            cited.add(match.group(1).upper())
    return cited


def _classify_openai_error(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        try:
            detail = exc.read().decode("utf-8", errors="replace").lower()
        except Exception:  # noqa: BLE001
            detail = str(exc.reason or "").lower()
        if code in (401, 403):
            return "authentication error"
        if code == 404 or "model_not_found" in detail:
            return "model unavailable"
        if code == 429 or "insufficient_quota" in detail or "billing" in detail:
            return "quota/billing error"
        return f"API request failed (HTTP {code})"
    if isinstance(exc, urllib.error.URLError):
        return f"network error ({exc.reason})"
    message = str(exc).lower()
    if "api key" in message:
        return "API key not found"
    if "json" in message or "invalid response" in message or "fictional" in message:
        return "invalid response format"
    return f"writer error ({exc.__class__.__name__})"
