"""Configurable soft penalties for domains that repeatedly fail Reader extraction.

Penalties demote ranking during Searcher candidate allocation. They never hard-ban
a domain — results may still be retained when no better evidence exists.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

# Default soft multipliers applied to Source.relevance (lower = stronger demotion).
DEFAULT_DOMAIN_PENALTIES: dict[str, float] = {
    "zhuanlan.zhihu.com": 0.45,
    "fortunebusinessinsights.com": 0.50,
    "gminsights.com": 0.50,
}

_ENV_KEY = "RESEARCHPILOT_DOMAIN_PENALTIES"


def load_domain_penalties() -> dict[str, float]:
    """Load domain → relevance multiplier map.

    Override via env ``RESEARCHPILOT_DOMAIN_PENALTIES`` as comma-separated
    ``domain:multiplier`` pairs (e.g. ``zhuanlan.zhihu.com:0.4,gminsights.com:0.5``).
    Empty string disables all penalties.
    """
    raw = os.environ.get(_ENV_KEY)
    if raw is None:
        return dict(DEFAULT_DOMAIN_PENALTIES)
    text = raw.strip()
    if not text:
        return {}
    if text.lower() in {"none", "off", "0"}:
        return {}

    penalties: dict[str, float] = {}
    for part in text.split(","):
        piece = part.strip()
        if not piece:
            continue
        if ":" not in piece:
            continue
        domain, mult_s = piece.rsplit(":", 1)
        domain = domain.strip().lower()
        if domain.startswith("www."):
            domain = domain[4:]
        try:
            mult = float(mult_s.strip())
        except ValueError:
            continue
        penalties[domain] = max(0.05, min(1.0, mult))
    return penalties


def domain_of(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or "unknown"


def penalty_for_url(url: str, penalties: dict[str, float] | None = None) -> tuple[float, str | None]:
    """Return ``(multiplier, matched_domain_or_None)`` for a URL."""
    table = DEFAULT_DOMAIN_PENALTIES if penalties is None else penalties
    host = domain_of(url)
    if host in table:
        return table[host], host
    # Suffix match so subdomains inherit parent rules when listed as apex.
    for domain, mult in table.items():
        if host == domain or host.endswith("." + domain):
            return mult, domain
    return 1.0, None


def apply_relevance_penalty(
    relevance: float,
    url: str,
    *,
    penalties: dict[str, float] | None = None,
) -> tuple[float, str | None, bool]:
    """Return ``(adjusted_relevance, matched_domain, applied)``."""
    mult, matched = penalty_for_url(url, penalties)
    if matched is None or mult >= 0.999:
        return float(relevance), None, False
    return float(relevance) * mult, matched, True
