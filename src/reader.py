"""Reader — fetch and extract readable content from discovered sources.

Responsibility
--------------
Own *only* content extraction. Given ``Source`` metadata, produce
``EvidenceDocument`` objects with extracted text, word counts, and
read status. Does not decide which sources to keep (EvidenceEvaluator)
or invent narrative (Synthesizer / Writer).

Interface
---------
``Reader.read(sources) -> list[EvidenceDocument]`` is the stable entry
point. Future PDF / announcement readers can plug in behind the same
method or as specialized subclasses without changing the pipeline.

Implementation
--------------
Uses ``requests`` + BeautifulSoup to fetch HTML, strip chrome (nav, ads,
scripts, styles), and extract main article text. Per-URL failures fall
back to the search snippet and never abort the batch.
"""

from __future__ import annotations

import logging
import re

import requests
from bs4 import BeautifulSoup

from src.models import EvidenceDocument, Source

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 12
MAX_EXTRACTED_CHARS = 12_000
MIN_USEFUL_CHARS = 80
USER_AGENT = (
    "Mozilla/5.0 (compatible; ResearchPilot/0.1; +https://github.com/researchpilot) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_STRIP_TAGS = (
    "script",
    "style",
    "noscript",
    "svg",
    "iframe",
    "canvas",
    "form",
    "nav",
    "footer",
    "header",
    "aside",
    "button",
    "input",
    "select",
    "textarea",
)

_NOISE_SELECTORS = (
    "[role='navigation']",
    "[role='banner']",
    "[role='contentinfo']",
    "[role='complementary']",
    ".nav",
    ".navbar",
    ".menu",
    ".sidebar",
    ".advertisement",
    ".ads",
    ".ad",
    ".cookie",
    ".cookie-banner",
    "#cookie",
    ".social-share",
    ".share-buttons",
    ".comments",
    "#comments",
)


class Reader:
    """Read and extract content from candidate sources (HTML pages today)."""

    def read(self, sources: list[Source]) -> list[EvidenceDocument]:
        """Fetch and extract readable text for each source.

        One failed URL does not stop the batch. Failures fall back to the
        search snippet and set ``read_status="fallback"``.

        Args:
            sources: Candidate sources from the Searcher.

        Returns:
            One EvidenceDocument per source, in the same order.
        """
        return [self._read_one(source) for source in sources]

    def _read_one(self, source: Source) -> EvidenceDocument:
        """Read a single source URL with isolated error handling."""
        try:
            html = self._fetch_html(source.url)
            text = self._extract_main_text(html)
            if len(text) < MIN_USEFUL_CHARS:
                raise ValueError(
                    f"extracted text too short ({len(text)} chars); page may be JS-rendered or blocked"
                )
            truncated = _truncate(text, MAX_EXTRACTED_CHARS)
            return EvidenceDocument(
                source=source,
                extracted_text=truncated,
                word_count=_word_count(truncated),
                read_status="success",
                error_message=None,
                key_excerpts=_excerpts(truncated),
            )
        except Exception as exc:  # noqa: BLE001 — per-URL isolation
            reason = str(exc).strip() or exc.__class__.__name__
            logger.warning("Failed to read %s: %s", source.url, reason)
            fallback = (source.snippet or "").strip() or source.title
            return EvidenceDocument(
                source=source,
                extracted_text=fallback,
                word_count=_word_count(fallback),
                read_status="fallback",
                error_message=reason,
                key_excerpts=[fallback[:240]] if fallback else [],
            )

    def _fetch_html(self, url: str) -> str:
        """HTTP GET with timeout and a realistic User-Agent."""
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            allow_redirects=True,
        )
        response.raise_for_status()

        content_type = (response.headers.get("Content-Type") or "").lower()
        if "html" not in content_type and "text/plain" not in content_type and content_type:
            # Some servers omit content-type; still try if body looks like HTML.
            body_prefix = response.content[:200].decode("utf-8", errors="ignore").lower()
            if "<html" not in body_prefix and "<!doctype" not in body_prefix:
                raise ValueError(f"unsupported content type: {content_type}")

        response.encoding = response.apparent_encoding or response.encoding or "utf-8"
        return response.text

    def _extract_main_text(self, html: str) -> str:
        """Strip chrome and return the main readable article text."""
        soup = BeautifulSoup(html, "html.parser")

        for tag_name in _STRIP_TAGS:
            for node in soup.find_all(tag_name):
                node.decompose()

        for selector in _NOISE_SELECTORS:
            for node in soup.select(selector):
                node.decompose()

        root = (
            soup.find("article")
            or soup.find("main")
            or soup.find(attrs={"role": "main"})
            or soup.find("body")
            or soup
        )

        text = root.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        return text


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to ``max_chars``, preferring a word boundary."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return (cut or text[:max_chars]).rstrip() + "…"


def _word_count(text: str) -> int:
    """Count whitespace-separated tokens."""
    return len(text.split()) if text.strip() else 0


def _excerpts(text: str, limit: int = 2, size: int = 220) -> list[str]:
    """Build short excerpts from the start of the extracted text."""
    if not text:
        return []
    chunks: list[str] = []
    remaining = text
    for _ in range(limit):
        if not remaining:
            break
        piece = remaining[:size].rsplit(" ", 1)[0] if len(remaining) > size else remaining
        chunks.append(piece.strip())
        remaining = remaining[len(piece) :].lstrip()
    return chunks
