"""QueryAnalyzer — interpret and classify the user's research query.

Responsibility
--------------
Own *only* query understanding. Given raw user text, produce an
``AnalyzedQuery`` with:

- ``query_type`` — industry | company | technology/theme
- ``normalized_topic`` — cleaned canonical topic string
- ``research_goal`` — short statement of what the research should achieve

Does not plan steps, search, or write reports.

Current implementation
----------------------
Rule-based mock classifier (no LLM). Replace later with an OpenAI call
that returns structured JSON classification.

Examples
--------
- ``"PCB industry chain"`` → industry
- ``"Shengquan Group"`` → company
- ``"AI glasses"`` → technology/theme
"""

from __future__ import annotations

import re

from src.freshness import detect_time_sensitive
from src.models import AnalyzedQuery, QueryType

# Explicit company aliases (lowercase key → display name).
_KNOWN_COMPANIES: dict[str, str] = {
    "shengquan group": "Shengquan Group",
    "shengquan": "Shengquan Group",
    "圣泉集团": "Shengquan Group",
    "圣泉": "Shengquan Group",
    "nvidia": "NVIDIA",
    "tsmc": "TSMC",
    "foxconn": "Foxconn",
    "byd": "BYD",
    "catl": "CATL",
    "huawei": "Huawei",
    "tencent": "Tencent",
    "alibaba": "Alibaba",
}

_COMPANY_SUFFIX_RE = re.compile(
    r"\b("
    r"group|corp(?:oration)?|inc(?:orporated)?|ltd|limited|"
    r"llc|plc|holdings?|company|co\.?"
    r")\b",
    re.IGNORECASE,
)

_COMPANY_CN_RE = re.compile(r"(集团|股份|有限公司|控股|科技)")

_INDUSTRY_HINTS = (
    "industry",
    "industry chain",
    "value chain",
    "sector",
    "market",
    "supply chain",
    "产业链",
    "行业",
    "板块",
    "赛道",
)

_TECHNOLOGY_HINTS = (
    "ai ",
    "ai-",
    "technology",
    "tech ",
    "theme",
    "concept",
    "glasses",
    "resin",
    "cooling",
    "液冷",
    "树脂",
    "覆铜板",
    "chip",
    "semiconductor",
    "llm",
    "robot",
    "battery",
    "sensor",
    "材料",
    "技术",
    "概念",
)


class QueryAnalyzer:
    """Classify and normalize a user research query (rule-based)."""

    def analyze(self, query: str) -> AnalyzedQuery:
        """Analyze a raw user query into a structured ``AnalyzedQuery``.

        Args:
            query: Free-text research topic from the user.

        Returns:
            AnalyzedQuery with type, normalized topic, and research goal.

        Raises:
            ValueError: If query is empty or whitespace-only.
        """
        raw = query.strip()
        if not raw:
            raise ValueError("Research topic cannot be empty.")

        normalized = _normalize_whitespace(raw)
        query_type = self._classify(normalized)
        topic = self._normalize_topic(normalized, query_type)
        goal = self._research_goal(topic, query_type)
        time_sensitive = detect_time_sensitive(raw)

        return AnalyzedQuery(
            raw_query=raw,
            query_type=query_type,
            normalized_topic=topic,
            research_goal=goal,
            time_sensitive=time_sensitive,
        )

    def _classify(self, text: str) -> QueryType:
        """Rule-based query type classification."""
        lower = text.lower()

        if lower in _KNOWN_COMPANIES or any(
            lower == alias or lower.startswith(alias + " ") for alias in _KNOWN_COMPANIES
        ):
            return QueryType.COMPANY

        if _COMPANY_SUFFIX_RE.search(text) or _COMPANY_CN_RE.search(text):
            return QueryType.COMPANY

        if any(hint in lower for hint in _INDUSTRY_HINTS):
            return QueryType.INDUSTRY

        if any(hint in lower for hint in _TECHNOLOGY_HINTS):
            return QueryType.TECHNOLOGY

        # Default: treat bare product/theme phrases as technology/theme;
        # multi-word "* industry" style already caught above.
        if len(text.split()) <= 3 and not any(h in lower for h in ("market", "sector")):
            return QueryType.TECHNOLOGY

        return QueryType.INDUSTRY

    def _normalize_topic(self, text: str, query_type: QueryType) -> str:
        """Produce a clean canonical topic string."""
        lower = text.lower()
        if lower in _KNOWN_COMPANIES:
            return _KNOWN_COMPANIES[lower]

        for alias, display in _KNOWN_COMPANIES.items():
            if lower.startswith(alias + " "):
                return display

        # Title-case short English topics; keep mixed/CJK as-is.
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 &\-/]*", text):
            if query_type == QueryType.COMPANY:
                return text.title() if text.upper() != text else text
            # Preserve common acronyms like PCB, AI
            return _title_preserve_acronyms(text)

        return text

    def _research_goal(self, topic: str, query_type: QueryType) -> str:
        """Build a short research goal statement for the Planner."""
        if query_type == QueryType.COMPANY:
            return (
                f"Build a company research profile of {topic}, covering business "
                f"segments, industry position, competitors, financial/operational "
                f"highlights, and key risks."
            )
        if query_type == QueryType.TECHNOLOGY:
            return (
                f"Assess the technology/theme '{topic}': adoption drivers, "
                f"application scenarios, competitive landscape, and commercialization outlook."
            )
        return (
            f"Map the {topic} industry: market structure, value chain, leading "
            f"players, technology trends, and major risks."
        )


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _title_preserve_acronyms(text: str) -> str:
    """Title-case words while keeping short ALL-CAPS tokens (e.g. PCB, AI)."""
    parts = []
    for word in text.split(" "):
        if word.isupper() and 1 < len(word) <= 5:
            parts.append(word)
        else:
            parts.append(word.capitalize())
    return " ".join(parts)
