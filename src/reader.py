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

Diagnostics (v1.1.2 pass)
-------------------------
Each source is classified into exactly one primary ``extraction_status``.
Search snippets never count as FULL_TEXT / PARTIAL_TEXT.
"""

from __future__ import annotations

import logging
import os
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Any

import requests
from bs4 import BeautifulSoup

from src.domain_penalty import domain_of as _domain_of_url
from src.freshness import extract_date_from_html, extract_date_from_text
from src.models import EvidenceDocument, Source

logger = logging.getLogger(__name__)

# Statuses eligible for a cheap replacement search (pipeline-owned).
REPLACEABLE_EXTRACTION_STATUSES = frozenset(
    {
        "EMPTY_CONTENT",
        "JS_OR_SHORT_CONTENT",
        "HTTP_403",
        "PDF_UNSUPPORTED",
    }
)


def _request_timeout_seconds() -> float:
    """Bounded HTTP timeout; overridable for diagnostic runs via env."""
    import os

    raw = (os.environ.get("RESEARCHPILOT_READER_TIMEOUT") or "").strip()
    if not raw:
        return 12.0
    try:
        return max(3.0, min(30.0, float(raw)))
    except ValueError:
        return 12.0


REQUEST_TIMEOUT_SECONDS = 12  # default; runtime uses _request_timeout_seconds()
MAX_EXTRACTED_CHARS = 12_000
MIN_USEFUL_CHARS = 80
MAX_PDF_PAGES = 8
MAX_PDF_CHARS = 12_000
USER_AGENT = (
    "Mozilla/5.0 (compatible; ResearchPilot/0.1; +https://github.com/researchpilot) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# Conservative domain-aware article selectors (fallback after weak generic extract).
_DOMAIN_CONTENT_SELECTORS: dict[str, tuple[str, ...]] = {
    "eastmoney.com": (
        "#ContentBody",
        ".txtinfos",
        ".article-body",
        ".newsContent",
        ".content",
        "div[class*='article']",
    ),
    "finance.eastmoney.com": (
        "#ContentBody",
        ".txtinfos",
        ".article-body",
        ".newsContent",
    ),
    "emcreative.eastmoney.com": (
        ".article-body",
        ".txtinfos",
        "#ContentBody",
        ".content",
    ),
    "cloud.tencent.com": (
        ".mod-article-content",
        ".tea-article-content",
        "article",
        ".com-markdown-body",
        ".content-detail",
    ),
}

# Primary extraction outcomes (exactly one per source).
EXTRACTION_STATUSES = (
    "FULL_TEXT",
    "PARTIAL_TEXT",
    "SNIPPET_FALLBACK",
    "PDF_UNSUPPORTED",
    "HTTP_403",
    "HTTP_OTHER_ERROR",
    "JS_OR_SHORT_CONTENT",
    "CONNECTION_ERROR",
    "ENCODING_ERROR",
    "EMPTY_CONTENT",
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

_MOJIBAKE_MARKERS = (
    "Ã",
    "Â",
    "â€",
    "ï¿½",
    "Ã©",
    "Ã¨",
    "Ã ",
    "äº",
    "å¤",
    "æ˜",
    "çš",
    "è®",
    "æ˜¯",
)


@dataclass
class _FetchMeta:
    html: str = ""
    content_type: str | None = None
    http_status: int | None = None
    encoding: str | None = None
    content_bytes: bytes = b""
    is_pdf: bool = False


class Reader:
    """Read and extract content from candidate sources (HTML + text PDFs)."""

    def __init__(self) -> None:
        self.last_diagnostics: dict[str, Any] = {}
        self._pdf_attempts = 0
        self._pdf_successes = 0
        self._domain_extract_used = 0

    def read(self, sources: list[Source]) -> list[EvidenceDocument]:
        """Fetch and extract readable text for each source.

        One failed URL does not stop the batch. Failures fall back to the
        search snippet and set ``read_status="fallback"``.

        Args:
            sources: Candidate sources from the Searcher.

        Returns:
            One EvidenceDocument per source, in the same order.
        """
        self._pdf_attempts = 0
        self._pdf_successes = 0
        self._domain_extract_used = 0
        documents = [self._read_one(source) for source in sources]
        self.last_diagnostics = build_reader_diagnostics(
            documents,
            pdf_attempts=self._pdf_attempts,
            pdf_successes=self._pdf_successes,
            domain_extract_used=self._domain_extract_used,
        )
        return documents

    def _read_one(self, source: Source) -> EvidenceDocument:
        """Read a single source URL with isolated error handling."""
        snippet = (source.snippet or "").strip()
        snippet_chars = len(snippet)
        meta = _FetchMeta()

        try:
            meta = self._fetch(source.url)
            if meta.is_pdf:
                self._pdf_attempts += 1
                text = self._extract_pdf_text(meta.content_bytes)
                if not text.strip() or len(text) < MIN_USEFUL_CHARS:
                    raise ValueError("unsupported content type: application/pdf")
                self._pdf_successes += 1
            else:
                text = self._extract_main_text(meta.html, url=source.url)
                if not text.strip():
                    raise ValueError("empty extracted content")
                if len(text) < MIN_USEFUL_CHARS:
                    raise ValueError(
                        f"extracted text too short ({len(text)} chars); "
                        "page may be JS-rendered or blocked"
                    )

            truncated = _truncate(text, MAX_EXTRACTED_CHARS)
            was_truncated = len(text) > MAX_EXTRACTED_CHARS
            if _looks_like_mojibake(truncated):
                # Diagnostic classification only — do not change fallback behavior yet.
                status = "ENCODING_ERROR"
                error_message = (
                    "encoding/mojibake detected in extracted text "
                    f"(encoding={meta.encoding or 'unknown'})"
                )
            else:
                status = "PARTIAL_TEXT" if was_truncated else "FULL_TEXT"
                error_message = None
            _enrich_source_date(
                source,
                html=meta.html if not meta.is_pdf else "",
                text=truncated,
            )
            return EvidenceDocument(
                source=source,
                extracted_text=truncated,
                word_count=_word_count(truncated),
                read_status="success",
                error_message=error_message,
                key_excerpts=_excerpts(truncated),
                extraction_status=status,
                content_type=meta.content_type,
                http_status=meta.http_status,
                encoding=meta.encoding,
                extracted_char_count=len(truncated),
                snippet_char_count=snippet_chars,
                snippet_fallback=False,
                extraction_truncated=was_truncated,
            )
        except Exception as exc:  # noqa: BLE001 — per-URL isolation
            reason = str(exc).strip() or exc.__class__.__name__
            status = classify_extraction_failure(exc, meta=meta, reason=reason)
            logger.warning("Failed to read %s: %s [%s]", source.url, reason, status)
            fallback = snippet or (source.title or "").strip()
            if not fallback:
                status = "EMPTY_CONTENT"
            _enrich_source_date(source, html="", text=fallback)
            return EvidenceDocument(
                source=source,
                extracted_text=fallback,
                word_count=_word_count(fallback),
                read_status="fallback",
                error_message=reason,
                key_excerpts=[fallback[:240]] if fallback else [],
                extraction_status=status,
                content_type=meta.content_type,
                http_status=meta.http_status,
                encoding=meta.encoding,
                extracted_char_count=len(fallback),
                snippet_char_count=snippet_chars,
                snippet_fallback=True,
                extraction_truncated=False,
            )

    def _fetch(self, url: str) -> _FetchMeta:
        """HTTP GET with timeout; detect HTML vs PDF bodies."""
        meta = _FetchMeta()
        try:
            response = requests.get(
                url,
                timeout=_request_timeout_seconds(),
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": (
                        "text/html,application/xhtml+xml,application/pdf;"
                        "q=0.9,*/*;q=0.8"
                    ),
                    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                },
                allow_redirects=True,
            )
        except requests.RequestException:
            raise

        meta.http_status = int(response.status_code)
        meta.content_type = (
            (response.headers.get("Content-Type") or "").split(";")[0].strip() or None
        )
        meta.encoding = response.apparent_encoding or response.encoding or None
        meta.content_bytes = response.content or b""

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            exc._rp_meta = meta  # type: ignore[attr-defined]
            raise

        content_type = (response.headers.get("Content-Type") or "").lower()
        url_l = (url or "").lower()
        looks_pdf = (
            "application/pdf" in content_type
            or url_l.endswith(".pdf")
            or "/pdf" in url_l
            or meta.content_bytes[:5] == b"%PDF-"
        )
        if looks_pdf:
            meta.is_pdf = True
            meta.content_type = meta.content_type or "application/pdf"
            return meta

        if "html" not in content_type and "text/plain" not in content_type and content_type:
            body_prefix = meta.content_bytes[:200].decode("utf-8", errors="ignore").lower()
            if "<html" not in body_prefix and "<!doctype" not in body_prefix:
                raise ValueError(f"unsupported content type: {content_type}")

        response.encoding = response.apparent_encoding or response.encoding or "utf-8"
        meta.encoding = response.encoding
        meta.html = response.text
        return meta

    # Back-compat alias for older callers / tests.
    def _fetch_html(self, url: str) -> _FetchMeta:
        return self._fetch(url)

    def _extract_pdf_text(self, content: bytes) -> str:
        """Extract text from a text-based PDF (no OCR)."""
        if not content:
            return ""
        try:
            from io import BytesIO

            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("unsupported content type: application/pdf") from exc

        try:
            reader = PdfReader(BytesIO(content))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("unsupported content type: application/pdf") from exc

        parts: list[str] = []
        total = 0
        for page in reader.pages[:MAX_PDF_PAGES]:
            try:
                page_text = page.extract_text() or ""
            except Exception:  # noqa: BLE001 — page-level isolation
                page_text = ""
            page_text = re.sub(r"\s+", " ", page_text).strip()
            if not page_text:
                continue
            parts.append(page_text)
            total += len(page_text)
            if total >= MAX_PDF_CHARS:
                break
        text = " ".join(parts).strip()
        return _truncate(text, MAX_PDF_CHARS) if text else ""

    def _extract_main_text(self, html: str, *, url: str = "") -> str:
        """Strip chrome and return the main readable article text.

        Tries generic extraction first; if weak, applies conservative
        domain-aware selectors for known finance/news shells.
        """
        generic = self._extract_generic_text(html)
        if len(generic) >= MIN_USEFUL_CHARS:
            return generic

        domain_text = self._extract_domain_text(html, url=url)
        if domain_text and len(domain_text) > len(generic):
            self._domain_extract_used += 1
            return domain_text
        return generic

    def _extract_generic_text(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        self._strip_chrome(soup)
        root = (
            soup.find("article")
            or soup.find("main")
            or soup.find(attrs={"role": "main"})
            or soup.find("body")
            or soup
        )
        text = root.get_text(separator=" ", strip=True)
        return re.sub(r"\s+", " ", text).strip()

    def _extract_domain_text(self, html: str, *, url: str) -> str:
        host = _domain_of_url(url)
        selectors: tuple[str, ...] = ()
        for domain, sels in _DOMAIN_CONTENT_SELECTORS.items():
            if host == domain or host.endswith("." + domain):
                selectors = sels
                break
        if not selectors:
            # Soft match eastmoney / tencent cloud subdomains.
            if "eastmoney.com" in host:
                selectors = _DOMAIN_CONTENT_SELECTORS["eastmoney.com"]
            elif "cloud.tencent.com" in host or host.endswith("tencent.com"):
                selectors = _DOMAIN_CONTENT_SELECTORS["cloud.tencent.com"]
        if not selectors:
            return ""

        soup = BeautifulSoup(html, "html.parser")
        self._strip_chrome(soup)
        chunks: list[str] = []
        for selector in selectors:
            for node in soup.select(selector):
                piece = node.get_text(separator=" ", strip=True)
                piece = re.sub(r"\s+", " ", piece).strip()
                if piece and len(piece) >= MIN_USEFUL_CHARS:
                    chunks.append(piece)
        if not chunks:
            return ""
        # Prefer the longest matching node.
        best = max(chunks, key=len)
        return best

    @staticmethod
    def _strip_chrome(soup: BeautifulSoup) -> None:
        for tag_name in _STRIP_TAGS:
            for node in soup.find_all(tag_name):
                node.decompose()
        for selector in _NOISE_SELECTORS:
            for node in soup.select(selector):
                node.decompose()


def classify_extraction_failure(
    exc: BaseException,
    *,
    meta: _FetchMeta | None = None,
    reason: str | None = None,
) -> str:
    """Map a Reader exception to exactly one primary extraction status."""
    meta = meta or _FetchMeta()
    attached = getattr(exc, "_rp_meta", None)
    if isinstance(attached, _FetchMeta):
        meta = attached

    msg = (reason or str(exc) or "").lower()
    status_code = meta.http_status
    if status_code is None and isinstance(exc, requests.HTTPError) and exc.response is not None:
        status_code = int(exc.response.status_code)

    content_type = (meta.content_type or "").lower()
    if getattr(meta, "is_pdf", False) or "pdf" in content_type or "application/pdf" in msg or (
        "unsupported content type" in msg and "pdf" in msg
    ):
        return "PDF_UNSUPPORTED"

    if status_code == 403 or "403" in msg or "forbidden" in msg:
        return "HTTP_403"

    if isinstance(exc, requests.HTTPError) or (
        status_code is not None and status_code >= 400
    ):
        return "HTTP_OTHER_ERROR"
    if re.search(r"\b(4\d\d|5\d\d)\b", msg) and "too short" not in msg:
        return "HTTP_OTHER_ERROR"

    if isinstance(
        exc,
        (
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.ProxyError,
            requests.exceptions.SSLError,
            requests.exceptions.ChunkedEncodingError,
        ),
    ):
        return "CONNECTION_ERROR"
    if any(
        token in msg
        for token in (
            "connection",
            "proxy",
            "timed out",
            "timeout",
            "max retries",
            "ssl",
            "name or service not known",
            "failed to resolve",
        )
    ):
        return "CONNECTION_ERROR"

    if isinstance(exc, UnicodeError) or "mojibake" in msg or "encoding" in msg:
        return "ENCODING_ERROR"

    if "too short" in msg or "js-rendered" in msg or "js rendered" in msg:
        return "JS_OR_SHORT_CONTENT"

    if "empty extracted" in msg or "empty content" in msg:
        return "EMPTY_CONTENT"

    if "unsupported content type" in msg:
        # Non-PDF binary / odd types — treat as other HTTP/content failure.
        return "HTTP_OTHER_ERROR"

    return "SNIPPET_FALLBACK"


def _looks_like_mojibake(text: str) -> bool:
    """Heuristic: common UTF-8-as-Latin1 / replacement patterns."""
    if not text or len(text) < 40:
        return False
    sample = text[:4000]
    hits = sum(sample.count(marker) for marker in _MOJIBAKE_MARKERS)
    # Also count replacement chars.
    hits += sample.count("\ufffd")
    return hits >= 3


def domain_of(url: str) -> str:
    return _domain_of_url(url)


def build_reader_diagnostics(
    documents: list[EvidenceDocument],
    *,
    pdf_attempts: int = 0,
    pdf_successes: int = 0,
    domain_extract_used: int = 0,
    replacement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate per-source and domain-level Reader diagnostics."""
    per_source: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    failure_reasons: Counter[str] = Counter()
    extracted_lengths: list[int] = []

    for doc in documents:
        source = doc.source
        status = doc.extraction_status or "EMPTY_CONTENT"
        if status not in EXTRACTION_STATUSES:
            status = "SNIPPET_FALLBACK"
        status_counts[status] += 1
        if (
            doc.snippet_fallback
            or doc.read_status != "success"
            or status == "ENCODING_ERROR"
        ):
            failure_reasons[doc.error_message or status] += 1
        if doc.extraction_status in {"FULL_TEXT", "PARTIAL_TEXT"}:
            extracted_lengths.append(int(doc.extracted_char_count or 0))

        per_source.append(
            {
                "source_id": source.source_id,
                "research_task": source.research_task,
                "title": (source.title or "")[:120],
                "domain": domain_of(source.url),
                "url": source.url,
                "content_type": doc.content_type,
                "http_status": doc.http_status,
                "extraction_status": status,
                "read_status": doc.read_status,
                "extracted_char_count": doc.extracted_char_count,
                "extracted_word_count": doc.word_count,
                "snippet_char_count": doc.snippet_char_count,
                "snippet_fallback": bool(doc.snippet_fallback),
                "encoding": doc.encoding,
                "extraction_truncated": bool(doc.extraction_truncated),
                "failure_reason": doc.error_message,
            }
        )

    by_domain: dict[str, dict[str, int]] = {}
    for row in per_source:
        domain = row["domain"]
        bucket = by_domain.setdefault(
            domain,
            {
                "sources": 0,
                "FULL_TEXT": 0,
                "PARTIAL_TEXT": 0,
                "SNIPPET_FALLBACK": 0,
                "PDF_UNSUPPORTED": 0,
                "HTTP_403": 0,
                "HTTP_OTHER_ERROR": 0,
                "JS_OR_SHORT_CONTENT": 0,
                "CONNECTION_ERROR": 0,
                "ENCODING_ERROR": 0,
                "EMPTY_CONTENT": 0,
            },
        )
        bucket["sources"] += 1
        st = row["extraction_status"]
        if st in bucket:
            bucket[st] += 1
        else:
            bucket["SNIPPET_FALLBACK"] += 1

    domain_rows = [
        {"domain": domain, **counts}
        for domain, counts in sorted(
            by_domain.items(),
            key=lambda kv: (-kv[1]["sources"], kv[0]),
        )
    ]

    sent = len(documents)
    full = int(status_counts.get("FULL_TEXT", 0))
    partial = int(status_counts.get("PARTIAL_TEXT", 0))
    readable = full + partial
    snippet_like = sent - readable
    fallback_count = sum(1 for d in documents if d.snippet_fallback)

    funnel = {
        "sources_sent_to_reader": sent,
        "FULL_TEXT": full,
        "PARTIAL_TEXT": partial,
        "readable_full_or_partial": readable,
        "snippet_fallback_count": fallback_count,
        "failed_extraction_count": snippet_like,
        "full_partial_rate_pct": round(100.0 * readable / max(sent, 1), 1),
        "fallback_rate_pct": round(100.0 * fallback_count / max(sent, 1), 1),
        "median_extracted_chars_readable": (
            int(statistics.median(extracted_lengths)) if extracted_lengths else 0
        ),
        "status_counts": {k: int(status_counts.get(k, 0)) for k in EXTRACTION_STATUSES},
        "pdf_extraction_attempts": int(pdf_attempts),
        "pdf_extraction_successes": int(pdf_successes),
        "pdf_extraction_success_rate_pct": round(
            100.0 * pdf_successes / max(pdf_attempts, 1), 1
        )
        if pdf_attempts
        else 0.0,
        "domain_specific_extract_used": int(domain_extract_used),
    }

    top_failures = sorted(failure_reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:12]

    result: dict[str, Any] = {
        "funnel": funnel,
        "per_source": per_source,
        "by_domain": domain_rows,
        "top_failure_reasons": [
            {"reason": reason, "count": count} for reason, count in top_failures
        ],
    }
    if replacement:
        result["replacement"] = replacement
    return result


def format_reader_diagnostics_report(diag: dict[str, Any], *, topic: str = "") -> str:
    """Human-readable Reader diagnostic report."""
    funnel = diag.get("funnel") or {}
    parts = [
        f"# Reader diagnostic — {topic}" if topic else "# Reader diagnostic",
        "",
        "## 1. Reader funnel summary",
        f"- sources sent to Reader: {funnel.get('sources_sent_to_reader')}",
        f"- FULL_TEXT: {funnel.get('FULL_TEXT')}",
        f"- PARTIAL_TEXT: {funnel.get('PARTIAL_TEXT')}",
        f"- full/partial rate: {funnel.get('full_partial_rate_pct')}%",
        f"- snippet fallback: {funnel.get('snippet_fallback_count')} "
        f"({funnel.get('fallback_rate_pct')}%)",
        f"- failed extraction: {funnel.get('failed_extraction_count')}",
        f"- median extracted chars (readable): "
        f"{funnel.get('median_extracted_chars_readable')}",
        f"- PDF attempts/success: {funnel.get('pdf_extraction_attempts')}/"
        f"{funnel.get('pdf_extraction_successes')} "
        f"({funnel.get('pdf_extraction_success_rate_pct')}%)",
        f"- domain-specific extract used: {funnel.get('domain_specific_extract_used')}",
        "",
        "## Status counts",
    ]
    for status, count in (funnel.get("status_counts") or {}).items():
        parts.append(f"- {status}: {count}")

    parts.extend(["", "## 2. Per-source extraction table"])
    parts.append(
        "| ID | Domain | Status | HTTP | Chars | SnippetFB | Reason |"
    )
    parts.append("|---|---|---|---:|---:|---|---|")
    for row in diag.get("per_source") or []:
        reason = (row.get("failure_reason") or "")[:60].replace("|", "/")
        parts.append(
            "| "
            + " | ".join(
                [
                    str(row.get("source_id") or ""),
                    str(row.get("domain") or ""),
                    str(row.get("extraction_status") or ""),
                    str(row.get("http_status") if row.get("http_status") is not None else ""),
                    str(row.get("extracted_char_count") or 0),
                    "Y" if row.get("snippet_fallback") else "N",
                    reason,
                ]
            )
            + " |"
        )

    parts.extend(["", "## 3. Domain-level outcomes"])
    parts.append(
        "| Domain | Sources | Full | Partial | Snippet | PDF | 403 | "
        "OtherHTTP | JS/Short | Conn | Enc | Empty |"
    )
    parts.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in diag.get("by_domain") or []:
        parts.append(
            "| "
            + " | ".join(
                [
                    str(row.get("domain")),
                    str(row.get("sources", 0)),
                    str(row.get("FULL_TEXT", 0)),
                    str(row.get("PARTIAL_TEXT", 0)),
                    str(row.get("SNIPPET_FALLBACK", 0)),
                    str(row.get("PDF_UNSUPPORTED", 0)),
                    str(row.get("HTTP_403", 0)),
                    str(row.get("HTTP_OTHER_ERROR", 0)),
                    str(row.get("JS_OR_SHORT_CONTENT", 0)),
                    str(row.get("CONNECTION_ERROR", 0)),
                    str(row.get("ENCODING_ERROR", 0)),
                    str(row.get("EMPTY_CONTENT", 0)),
                ]
            )
            + " |"
        )

    parts.extend(["", "## 4. Top failure reasons"])
    for i, item in enumerate(diag.get("top_failure_reasons") or [], start=1):
        parts.append(f"{i}. {item.get('reason')} ({item.get('count')})")

    yield_block = diag.get("evidence_yield") or {}
    if yield_block:
        parts.extend(["", "## 5. Evidence-yield summary"])
        for key, value in yield_block.items():
            parts.append(f"- {key}: {value}")

    return "\n".join(parts)


def _enrich_source_date(source: Source, *, html: str, text: str) -> None:
    """Fill published_at on source when a higher-confidence date is found.

    Never invents dates. Prefers existing high/medium confidence values.
    """
    conf_rank = {"high": 3, "medium": 2, "low": 1, "none": 0}
    current = conf_rank.get(source.date_confidence or "none", 0)

    candidates = []
    if html:
        candidates.append(extract_date_from_html(html))
    if text:
        candidates.append(extract_date_from_text(text))

    best_dt = None
    best_source = "none"
    best_conf = "none"
    best_rank = current
    for dt, dsrc, dconf in candidates:
        rank = conf_rank.get(dconf, 0)
        if dt and rank > best_rank:
            best_dt, best_source, best_conf, best_rank = dt, dsrc, dconf, rank

    if best_dt is None:
        return

    source.published_at = best_dt.isoformat()
    source.published_date = best_dt.date().isoformat()
    source.date_source = best_source
    source.date_confidence = best_conf


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
