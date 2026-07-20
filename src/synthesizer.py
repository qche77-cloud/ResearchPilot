"""Synthesizer — turn evaluated evidence into grounded A-share research findings.

Responsibility
--------------
Own *only* analytical synthesis. Given a research plan and evaluated
evidence, produce a ``SynthesisBrief`` with evidence-linked findings and
verbatim supporting excerpts. Does not write the final report (Writer)
and must not invent facts beyond the supplied evidence.

Uses OpenAI (``OPENAI_API_KEY``, ``LLM_MODEL``) when available. On failure,
falls back without inventing synthesis content.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Iterable

from src.env import load_env
from src.models import (
    EvaluatedEvidence,
    GroundedFinding,
    ResearchPlan,
    SupportingExcerpt,
    SynthesisBrief,
)

logger = logging.getLogger(__name__)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_LLM_MODEL = "gpt-4o-mini"
OPENAI_TIMEOUT_SECONDS = 90
MAX_EVIDENCE_ITEMS = 20
MAX_EVIDENCE_CHARS = 1800
MAX_EXCERPT_CHARS = 220

CONTENT_SECTIONS: tuple[str, ...] = (
    "key_findings",
    "industry_chain_findings",
    "demand_supply_drivers",
    "technology_findings",
    "catalysts",
    "company_findings",
    "risks",
)

STRUCTURED_SECTIONS: tuple[str, ...] = CONTENT_SECTIONS + ("evidence_gaps",)

_SECTION_GAP_HINTS: dict[str, str] = {
    "key_findings": "缺少可用于总览判断的直接证据摘要",
    "industry_chain_findings": "缺少可核验的上中下游产业链拆解证据",
    "demand_supply_drivers": "缺少供需/景气驱动的直接证据",
    "technology_findings": "缺少关键技术路径或瓶颈的直接证据",
    "catalysts": "缺少涨价/扩产/订单/政策等近期催化的直接证据",
    "company_findings": "缺少可映射到A股公司的直接证据",
    "risks": "缺少可核验的风险表述证据",
}


class Synthesizer:
    """Synthesize evaluated evidence into grounded research findings."""

    def __init__(self) -> None:
        self.last_warning: str | None = None
        self.last_diagnostics: dict = {}
        load_env()

    def synthesize(
        self,
        plan: ResearchPlan,
        evidence: list[EvaluatedEvidence],
    ) -> SynthesisBrief:
        """Build a grounded synthesis brief from plan + evaluated evidence."""
        self.last_warning = None
        self.last_diagnostics = {}
        load_env()

        retained = [e for e in evidence if e.keep] or list(evidence)
        retained = sorted(retained, key=lambda e: e.final_score, reverse=True)
        truncated_by_cap = max(0, len(retained) - MAX_EVIDENCE_ITEMS)
        retained = retained[:MAX_EVIDENCE_ITEMS]
        evidence_index = {f"E{i}": item for i, item in enumerate(retained, start=1)}

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            self.last_warning = (
                "API key not found. OPENAI_API_KEY missing; synthesizer fallback "
                "emits evidence_gaps only (no invented findings)."
            )
            brief = self._fallback_brief(plan, retained, evidence_index, reason="API key not found")
            self._set_diagnostics(
                brief, evidence_index, source="fallback", truncated_by_cap=truncated_by_cap
            )
            return brief

        try:
            brief = self._llm_synthesize(plan, retained, evidence_index, api_key)
            self.last_warning = None
            self._set_diagnostics(
                brief, evidence_index, source="llm", truncated_by_cap=truncated_by_cap
            )
            return brief
        except Exception as exc:  # noqa: BLE001
            reason = _classify_openai_error(exc)
            self.last_warning = (
                f"{reason}. Synthesizer fallback used — no invented findings."
            )
            logger.warning("Synthesizer fallback: %s | detail=%s", reason, exc)
            brief = self._fallback_brief(plan, retained, evidence_index, reason=reason)
            self._set_diagnostics(
                brief, evidence_index, source="fallback", truncated_by_cap=truncated_by_cap
            )
            return brief

    def _set_diagnostics(
        self,
        brief: SynthesisBrief,
        evidence_index: dict[str, EvaluatedEvidence],
        *,
        source: str,
        truncated_by_cap: int = 0,
    ) -> None:
        finding_count = sum(len(getattr(brief, key)) for key in STRUCTURED_SECTIONS)
        excerpt_count = sum(
            len(f.supporting_excerpts)
            for key in STRUCTURED_SECTIONS
            for f in getattr(brief, key)
        )
        id_map = {}
        sent_per_task: dict[str, int] = {}
        for eid, item in evidence_index.items():
            sid = item.source.source_id
            id_map[eid] = {
                "source_id": sid,
                "url": item.source.url,
                "research_task": item.source.research_task,
                "final_score": item.final_score,
                "read_status": item.document.read_status,
            }
            task = (item.source.research_task or "unknown").strip() or "unknown"
            sent_per_task[task] = sent_per_task.get(task, 0) + 1

        findings_per_evidence: dict[str, int] = {eid: 0 for eid in evidence_index}
        findings_per_task: dict[str, int] = {}
        for key in STRUCTURED_SECTIONS:
            for finding in getattr(brief, key) or []:
                if key != "evidence_gaps" and finding.finding_type != "gap":
                    tasks_hit: set[str] = set()
                    for eid in finding.evidence_ids or []:
                        if eid in findings_per_evidence:
                            findings_per_evidence[eid] += 1
                        meta = id_map.get(eid) or {}
                        task = meta.get("research_task") or "unknown"
                        tasks_hit.add(str(task))
                    for task in tasks_hit or {"unknown"}:
                        findings_per_task[task] = findings_per_task.get(task, 0) + 1

        unused_evidence = [
            eid for eid, count in findings_per_evidence.items() if count == 0
        ]

        self.last_diagnostics = {
            "synthesizer_source": source,
            "evidence_items_sent": len(evidence_index),
            "truncated_by_max_evidence_items": truncated_by_cap,
            "max_evidence_items": MAX_EVIDENCE_ITEMS,
            "generated_findings": finding_count,
            "supporting_excerpts": excerpt_count,
            "synthesizer_warning": self.last_warning,
            "evidence_ids": list(evidence_index.keys()),
            "evidence_id_map": id_map,
            "sent_per_research_task": dict(sorted(sent_per_task.items())),
            "findings_per_research_task": dict(sorted(findings_per_task.items())),
            "findings_per_evidence_id": findings_per_evidence,
            "unused_evidence_ids": unused_evidence,
        }

    def _llm_synthesize(
        self,
        plan: ResearchPlan,
        retained: list[EvaluatedEvidence],
        evidence_index: dict[str, EvaluatedEvidence],
        api_key: str,
    ) -> SynthesisBrief:
        model = os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL).strip() or DEFAULT_LLM_MODEL
        analyzed = plan.analyzed_query
        objective = plan.research_objective or plan.research_goal or f"Research {plan.topic}"

        payload = {
            "model": model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {
                    "role": "user",
                    "content": _user_prompt(plan, analyzed, objective, evidence_index),
                },
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
        return self._brief_from_llm_json(plan, retained, evidence_index, parsed)

    def _brief_from_llm_json(
        self,
        plan: ResearchPlan,
        retained: list[EvaluatedEvidence],
        evidence_index: dict[str, EvaluatedEvidence],
        data: dict,
    ) -> SynthesisBrief:
        sections: dict[str, list[GroundedFinding]] = {}
        auto_gaps: list[GroundedFinding] = []

        for key in CONTENT_SECTIONS:
            raw_items = data.get(key) or []
            grounded = _parse_and_ground_findings(raw_items, evidence_index, section=key)
            sections[key] = grounded
            if not grounded:
                auto_gaps.append(
                    GroundedFinding(
                        finding=_SECTION_GAP_HINTS.get(
                            key, f"缺少可用于 {key} 的直接证据"
                        ),
                        evidence_ids=[],
                        finding_type="gap",
                        supporting_excerpts=[],
                    )
                )

        gap_items = _parse_and_ground_findings(
            data.get("evidence_gaps") or [],
            evidence_index,
            section="evidence_gaps",
            allow_uncited=True,
        )
        # Merge model gaps + auto gaps; de-dupe by finding text.
        seen_gap_text: set[str] = set()
        merged_gaps: list[GroundedFinding] = []
        for item in gap_items + auto_gaps:
            text_key = item.finding.strip()
            if not text_key or text_key in seen_gap_text:
                continue
            seen_gap_text.add(text_key)
            merged_gaps.append(item)

        brief = SynthesisBrief(
            topic=plan.topic,
            depth=plan.depth,
            cited_evidence=retained,
            evidence_index=evidence_index,
            key_findings=sections["key_findings"],
            industry_chain_findings=sections["industry_chain_findings"],
            demand_supply_drivers=sections["demand_supply_drivers"],
            technology_findings=sections["technology_findings"],
            catalysts=sections["catalysts"],
            company_findings=sections["company_findings"],
            risks=sections["risks"],
            evidence_gaps=merged_gaps,
            synthesizer_source="llm",
        )
        brief.findings = _legacy_findings_from_structured(brief)
        return brief

    def _fallback_brief(
        self,
        plan: ResearchPlan,
        retained: list[EvaluatedEvidence],
        evidence_index: dict[str, EvaluatedEvidence],
        *,
        reason: str,
    ) -> SynthesisBrief:
        """Fallback: empty content sections + explicit evidence_gaps only."""
        gaps = [
            GroundedFinding(
                finding=(
                    f"LLM synthesis unavailable ({reason}); no model knowledge was used "
                    "to invent findings. Re-run after fixing synthesizer access."
                ),
                evidence_ids=[],
                finding_type="gap",
                supporting_excerpts=[],
            )
        ]
        for key in CONTENT_SECTIONS:
            gaps.append(
                GroundedFinding(
                    finding=_SECTION_GAP_HINTS[key],
                    evidence_ids=[],
                    finding_type="gap",
                    supporting_excerpts=[],
                )
            )

        brief = SynthesisBrief(
            topic=plan.topic,
            depth=plan.depth,
            cited_evidence=retained,
            evidence_index=evidence_index,
            key_findings=[],
            industry_chain_findings=[],
            demand_supply_drivers=[],
            technology_findings=[],
            catalysts=[],
            company_findings=[],
            risks=[],
            evidence_gaps=gaps,
            synthesizer_source="fallback",
        )
        brief.findings = _legacy_findings_from_structured(brief)
        return brief


def _system_prompt() -> str:
    return """You are ResearchPilot's evidence synthesizer for China A-share research.

You receive evidence items labeled E1, E2, E3 with their full text.
Produce GROUNDED findings only.

Hard rules:
1. Use ONLY supplied evidence. Do NOT invent companies, figures, dates, policies, orders, or catalysts.
2. For each finding, return evidence_ids AND candidate_excerpts.
3. candidate_excerpts MUST be short VERBATIM copies copied from the evidence text (no paraphrase).
4. finding_type:
   - "supported_fact" only if an excerpt directly supports the claim
   - "inference" if support is only indirect; still cite evidence_ids and excerpts
5. If a section has no supportable findings, return [] for that section.
   Do NOT write fake items like "Evidence is insufficient...".
   Put missing needs into evidence_gaps instead.
6. Prefer Chinese when the user query is Chinese.
7. Distribute findings across sections; key_findings is a short summary only.

Return ONLY valid JSON:
{
  "key_findings": [
    {
      "finding": "...",
      "finding_type": "supported_fact",
      "evidence_ids": ["E1"],
      "candidate_excerpts": [{"evidence_id": "E1", "excerpt": "verbatim text from E1"}]
    }
  ],
  "industry_chain_findings": [],
  "demand_supply_drivers": [],
  "technology_findings": [],
  "catalysts": [],
  "company_findings": [],
  "risks": [],
  "evidence_gaps": [{"finding": "缺少...的直接证据", "evidence_ids": [], "candidate_excerpts": []}]
}
"""


def _user_prompt(plan, analyzed, objective: str, evidence_index: dict[str, EvaluatedEvidence]) -> str:
    query_type = plan.query_type.value if plan.query_type else "industry"
    raw_query = analyzed.raw_query if analyzed else plan.topic
    strategy = plan.research_strategy or ""

    evidence_blocks = []
    for eid, item in evidence_index.items():
        source = item.source
        text = (item.document.extracted_text or source.snippet or "")[:MAX_EVIDENCE_CHARS]
        evidence_blocks.append(
            "\n".join(
                [
                    f"[{eid}]",
                    f"title: {source.title}",
                    f"url: {source.url}",
                    f"task: {source.research_task or ''}",
                    f"query: {source.search_query or ''}",
                    f"date: {source.published_date or 'unknown'}",
                    f"scores: final={item.final_score}",
                    f"text: {text}",
                ]
            )
        )

    plan_tasks = [
        f"- {step.title}: {', '.join(step.search_queries[:3])}" for step in plan.steps
    ]

    return (
        f"User query: {raw_query}\n"
        f"Normalized topic: {plan.topic}\n"
        f"Query type: {query_type}\n"
        f"Research objective: {objective}\n"
        f"Research strategy: {strategy}\n"
        f"Plan tasks:\n" + "\n".join(plan_tasks) + "\n\n"
        f"Evidence corpus ({len(evidence_index)} items):\n"
        + "\n\n".join(evidence_blocks)
        + "\n\nReturn grounded JSON. candidate_excerpts must be verbatim substrings of evidence text."
    )


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _evidence_text(item: EvaluatedEvidence) -> str:
    return item.document.extracted_text or item.source.snippet or ""


def _find_verbatim_excerpt(source_text: str, candidate: str) -> str | None:
    """Return a verbatim excerpt from source_text if candidate matches (flex whitespace)."""
    source = source_text or ""
    cand = _normalize_ws(candidate)
    if not source or not cand or len(cand) < 8:
        return None

    # Exact substring first.
    if cand in source:
        return cand[:MAX_EXCERPT_CHARS]

    # Whitespace-flexible search.
    pattern = re.escape(cand)
    pattern = pattern.replace(r"\ ", r"\s+")
    match = re.search(pattern, source, flags=re.IGNORECASE)
    if match:
        return _normalize_ws(match.group(0))[:MAX_EXCERPT_CHARS]

    return None


def _auto_excerpt_from_evidence(finding: str, source_text: str) -> str | None:
    """Pick a short verbatim window from evidence overlapping finding tokens."""
    text = _normalize_ws(source_text)
    if len(text) < 12:
        return None

    tokens = [
        t
        for t in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,}", finding.lower())
        if t not in {"the", "and", "for", "with", "from", "that", "this"}
    ]
    if not tokens:
        return text[:MAX_EXCERPT_CHARS]

    # Prefer sentence-like chunks.
    chunks = re.split(r"(?<=[。！？；;.!?])\s*", text)
    best = None
    best_score = 0
    for chunk in chunks:
        chunk_l = chunk.lower()
        score = sum(1 for t in tokens if t in chunk_l)
        if score > best_score and len(chunk.strip()) >= 12:
            best_score = score
            best = chunk.strip()

    if best and best_score > 0:
        return best[:MAX_EXCERPT_CHARS]

    # Fallback: window around first matched token.
    lower = text.lower()
    for token in tokens:
        idx = lower.find(token)
        if idx >= 0:
            start = max(0, idx - 40)
            end = min(len(text), idx + 160)
            return text[start:end][:MAX_EXCERPT_CHARS]
    return None


def _build_supporting_excerpts(
    *,
    evidence_ids: list[str],
    candidate_excerpts: list[dict],
    finding_text: str,
    evidence_index: dict[str, EvaluatedEvidence],
) -> list[SupportingExcerpt]:
    """Build verified verbatim excerpts only (never paraphrased)."""
    excerpts: list[SupportingExcerpt] = []
    used_ids: set[str] = set()

    for raw in candidate_excerpts:
        if not isinstance(raw, dict):
            continue
        eid = str(raw.get("evidence_id") or "").strip().upper()
        if eid not in evidence_index:
            continue
        candidate = str(raw.get("excerpt") or "").strip()
        item = evidence_index[eid]
        source_text = _evidence_text(item)
        verified = _find_verbatim_excerpt(source_text, candidate)
        if not verified:
            continue
        excerpts.append(
            SupportingExcerpt(
                evidence_id=eid,
                excerpt=verified,
                source_title=item.source.title,
                source_url=item.source.url,
            )
        )
        used_ids.add(eid)

    # For cited IDs still missing a verified excerpt, extract a verbatim window.
    for eid in evidence_ids:
        if eid in used_ids or eid not in evidence_index:
            continue
        item = evidence_index[eid]
        auto = _auto_excerpt_from_evidence(finding_text, _evidence_text(item))
        if not auto:
            continue
        # Ensure auto excerpt is literally in the source text.
        if _find_verbatim_excerpt(_evidence_text(item), auto) is None and auto not in _evidence_text(item):
            # If whitespace differed, try normalize containment via finder on a slice.
            continue
        verified = _find_verbatim_excerpt(_evidence_text(item), auto) or (
            auto if auto in _evidence_text(item) else None
        )
        if not verified:
            continue
        excerpts.append(
            SupportingExcerpt(
                evidence_id=eid,
                excerpt=verified,
                source_title=item.source.title,
                source_url=item.source.url,
            )
        )
        used_ids.add(eid)

    return excerpts


def _parse_and_ground_findings(
    raw_items: object,
    evidence_index: dict[str, EvaluatedEvidence],
    *,
    section: str,
    allow_uncited: bool = False,
) -> list[GroundedFinding]:
    if not isinstance(raw_items, list):
        return []

    valid_ids = set(evidence_index.keys())
    findings: list[GroundedFinding] = []

    for item in raw_items:
        if isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            if section != "evidence_gaps" and not allow_uncited:
                # Do not accept bare strings as supported facts.
                continue
            findings.append(
                GroundedFinding(
                    finding=text,
                    evidence_ids=[],
                    finding_type="gap" if section == "evidence_gaps" else "inference",
                    supporting_excerpts=[],
                )
            )
            continue

        if not isinstance(item, dict):
            continue

        text = str(item.get("finding") or item.get("text") or "").strip()
        if not text:
            continue

        # Reject fake insufficient placeholders in content sections.
        lower = text.lower()
        if section != "evidence_gaps" and (
            "evidence is insufficient" in lower
            or "证据不足" in text
            or "不足以支持" in text
        ):
            continue

        raw_ids = item.get("evidence_ids") or item.get("evidenceIds") or []
        if isinstance(raw_ids, str):
            raw_ids = [raw_ids]
        evidence_ids = []
        for eid in raw_ids:
            token = str(eid).strip().upper()
            if token.lower().startswith("e") and not token.startswith("E"):
                token = token.upper()
            if token in valid_ids and token not in evidence_ids:
                evidence_ids.append(token)

        finding_type = str(
            item.get("finding_type") or item.get("kind") or "supported_fact"
        ).strip().lower()
        if finding_type not in {"supported_fact", "inference"}:
            finding_type = "supported_fact"

        candidates = item.get("candidate_excerpts") or item.get("supporting_excerpts") or []
        if not isinstance(candidates, list):
            candidates = []

        excerpts = _build_supporting_excerpts(
            evidence_ids=evidence_ids,
            candidate_excerpts=candidates,
            finding_text=text,
            evidence_index=evidence_index,
        )

        # Keep evidence_ids aligned to excerpts when possible.
        excerpt_ids = []
        for ex in excerpts:
            if ex.evidence_id not in excerpt_ids:
                excerpt_ids.append(ex.evidence_id)
        if excerpt_ids:
            evidence_ids = excerpt_ids

        # Gaps are missing-evidence notes, never supported_fact claims.
        if section == "evidence_gaps" or allow_uncited:
            findings.append(
                GroundedFinding(
                    finding=text,
                    evidence_ids=evidence_ids,
                    finding_type="gap",
                    supporting_excerpts=excerpts,
                )
            )
            continue

        if not evidence_ids:
            continue

        if finding_type == "supported_fact" and not excerpts:
            # Cannot claim supported_fact without a verbatim excerpt.
            finding_type = "inference"
            # Still need at least one excerpt for inference grounding; try harder.
            excerpts = _build_supporting_excerpts(
                evidence_ids=evidence_ids,
                candidate_excerpts=[],
                finding_text=text,
                evidence_index=evidence_index,
            )
            if not excerpts:
                continue

        if finding_type == "inference":
            if not excerpts:
                continue
            if not text.startswith("[Inference]") and "推断" not in text[:6]:
                text = f"[Inference] {text}"

        if finding_type == "supported_fact" and not excerpts:
            continue

        findings.append(
            GroundedFinding(
                finding=text,
                evidence_ids=evidence_ids,
                finding_type=finding_type,
                supporting_excerpts=excerpts,
            )
        )

    return findings


def _format_findings_markdown(items: Iterable[GroundedFinding]) -> str:
    lines: list[str] = []
    for item in items:
        if item.finding_type == "gap":
            lines.append(f"- {item.finding}")
            continue
        ids = ", ".join(item.evidence_ids) if item.evidence_ids else "none"
        prefix = "**Inference** — " if item.finding_type == "inference" else ""
        lines.append(f"- {prefix}{item.finding} _(evidence: {ids})_")
        for ex in item.supporting_excerpts:
            lines.append(f"  - excerpt `{ex.evidence_id}`: \"{ex.excerpt}\"")
    return "\n".join(lines) if lines else "_No grounded findings for this section._"


def _legacy_findings_from_structured(brief: SynthesisBrief) -> dict[str, str]:
    mapped = {
        "Executive Summary": _format_findings_markdown(brief.key_findings),
        "Key Drivers": _format_findings_markdown(brief.demand_supply_drivers),
        "Industry Value Chain": _format_findings_markdown(brief.industry_chain_findings),
        "Technology and Competition": _format_findings_markdown(brief.technology_findings),
        "Major Companies": _format_findings_markdown(brief.company_findings),
        "Recent Developments": _format_findings_markdown(brief.catalysts),
        "Risks and Uncertainties": _format_findings_markdown(brief.risks),
    }
    gaps = _format_findings_markdown(brief.evidence_gaps)
    mapped["Executive Summary"] = (
        mapped["Executive Summary"] + "\n\n**Evidence gaps**\n" + gaps
    )
    return mapped


def _parse_llm_json(content: str) -> dict:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise RuntimeError("invalid response format")
    return data


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
    if "json" in message or "invalid response" in message:
        return "invalid response format"
    return f"synthesizer error ({exc.__class__.__name__})"
