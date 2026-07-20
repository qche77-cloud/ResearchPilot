"""Task-aware freshness profiles, query augmentation, and date utilities.

Used by QueryAnalyzer (hot-topic intent), Searcher (query augmentation /
candidate ranking), Reader (date extraction), and Evaluator (weighted scoring).
Does not invent publication dates.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable


class FreshnessProfile(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    CURRENT = "CURRENT"
    RECENT = "RECENT"
    BREAKING = "BREAKING"


# Score-blend weights: credibility / relevance / freshness
PROFILE_WEIGHTS: dict[FreshnessProfile, tuple[float, float, float]] = {
    FreshnessProfile.STRUCTURAL: (0.40, 0.45, 0.15),
    FreshnessProfile.CURRENT: (0.30, 0.40, 0.30),
    FreshnessProfile.RECENT: (0.25, 0.35, 0.40),
    FreshnessProfile.BREAKING: (0.20, 0.30, 0.50),
}

_HOT_TOPIC_PATTERNS = (
    r"今天",
    r"今日",
    r"最新",
    r"最近",
    r"本周",
    r"近一周",
    r"近7日",
    r"为什么涨",
    r"为啥涨",
    r"突然上涨",
    r"大涨",
    r"涨停",
    r"热点",
    r"催化",
    r"today",
    r"this week",
    r"why .+ ris",
    r"surge",
)

_STRUCTURAL_HINTS = (
    "产业链",
    "industry chain",
    "value chain",
    "商业模式",
    "business model",
    "技术原理",
    "technology principle",
    "技术路径",
    "历史",
    "competitive structure",
    "竞争格局结构",
    "上中下游",
    "定义",
    "overview structure",
)

_RECENT_HINTS = (
    "催化",
    "catalyst",
    "政策",
    "policy",
    "涨价",
    "扩产",
    "中标",
    "订单",
    "招标",
    "公告",
    "announcement",
    "突破",
    "breakthrough",
    "近一年",
    "近半年",
    "近期",
)

_BREAKING_HINTS = (
    "今日",
    "今天",
    "最新",
    "突发",
    "盘中",
    "涨停",
    "为什么涨",
    "热点",
    "today",
    "breaking",
)

_CURRENT_HINTS = (
    "需求",
    "供给",
    "供需",
    "demand",
    "supply",
    "竞争",
    "competitive",
    "公司发展",
    "财务",
    "运营",
    "景气",
    "市场",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def detect_time_sensitive(query: str) -> bool:
    text = (query or "").strip().lower()
    if not text:
        return False
    for pattern in _HOT_TOPIC_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True
    return False


def classify_task_freshness(
    title: str,
    description: str = "",
    *,
    time_sensitive: bool = False,
) -> FreshnessProfile:
    """Infer freshness profile from task title/description (+ query intent)."""
    blob = f"{title} {description}".lower()

    if time_sensitive and (
        any(h.lower() in blob for h in _BREAKING_HINTS)
        or any(h.lower() in blob for h in _RECENT_HINTS[:8])
    ):
        return FreshnessProfile.BREAKING
    if any(h.lower() in blob for h in _BREAKING_HINTS):
        return FreshnessProfile.BREAKING
    if any(h.lower() in blob for h in _RECENT_HINTS):
        return FreshnessProfile.RECENT
    if any(h.lower() in blob for h in _STRUCTURAL_HINTS):
        # Hot-topic queries still keep structural background as STRUCTURAL.
        return FreshnessProfile.STRUCTURAL
    if any(h.lower() in blob for h in _CURRENT_HINTS):
        return FreshnessProfile.CURRENT

    if time_sensitive:
        # Unclassified tasks under hot-topic intent lean recent.
        return FreshnessProfile.RECENT
    return FreshnessProfile.CURRENT


def augment_queries_for_freshness(
    base_queries: Iterable[str],
    topic: str,
    profile: FreshnessProfile,
    *,
    time_sensitive: bool = False,
    now: datetime | None = None,
) -> list[str]:
    """Return base queries plus a few freshness-augmented variants (deduped)."""
    now = now or utc_now()
    year = now.year
    topic = (topic or "").strip() or "行业"
    seen: set[str] = set()
    out: list[str] = []

    def _add(q: str) -> None:
        text = " ".join((q or "").split()).strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(text)

    for q in base_queries or []:
        _add(str(q))

    extras: list[str] = []
    if profile == FreshnessProfile.BREAKING or (time_sensitive and profile != FreshnessProfile.STRUCTURAL):
        extras = [
            f"{topic} 今日 新闻",
            f"{topic} 最新 消息",
            f"{topic} 近7日 催化",
            f"{topic} A股 今日",
            f"{topic} {year} 最新",
        ]
    elif profile == FreshnessProfile.RECENT:
        extras = [
            f"{topic} 政策 {year}",
            f"{topic} 中标 近期",
            f"{topic} 扩产 近一年",
            f"{topic} 订单 {year}",
            f"{topic} 催化 近半年",
        ]
    elif profile == FreshnessProfile.CURRENT:
        extras = [
            f"{topic} 供需 {year}",
            f"{topic} 市场 近两年",
            f"{topic} 竞争格局 {year}",
        ]
    # STRUCTURAL: keep planner queries; optional light year hint only.
    elif profile == FreshnessProfile.STRUCTURAL:
        extras = [f"{topic} 产业链 图谱"]

    for q in extras[:3]:
        _add(q)
    return out


def score_freshness(
    published_at: datetime | None,
    profile: FreshnessProfile,
    *,
    now: datetime | None = None,
) -> tuple[int, int | None]:
    """Return (freshness_score 0–100, age_days or None)."""
    now = now or utc_now()
    if published_at is None:
        # Unknown date: neutral-low for time-sensitive profiles; OK for structural.
        defaults = {
            FreshnessProfile.STRUCTURAL: 60,
            FreshnessProfile.CURRENT: 45,
            FreshnessProfile.RECENT: 30,
            FreshnessProfile.BREAKING: 20,
        }
        return defaults[profile], None

    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_days = max(0, (now - published_at).days)

    if profile == FreshnessProfile.BREAKING:
        if age_days <= 1:
            score = 100
        elif age_days <= 7:
            score = 92
        elif age_days <= 30:
            score = 75
        elif age_days <= 90:
            score = 45
        elif age_days <= 365:
            score = 18
        else:
            score = 5
    elif profile == FreshnessProfile.RECENT:
        if age_days <= 30:
            score = 95
        elif age_days <= 90:
            score = 88
        elif age_days <= 180:
            score = 78
        elif age_days <= 365:
            score = 65
        elif age_days <= 730:
            score = 40
        else:
            score = 15
    elif profile == FreshnessProfile.CURRENT:
        if age_days <= 180:
            score = 90
        elif age_days <= 365:
            score = 80
        elif age_days <= 730:
            score = 65
        elif age_days <= 1825:
            score = 45
        else:
            score = 25
    else:  # STRUCTURAL — older authoritative sources remain acceptable
        if age_days <= 730:
            score = 80
        elif age_days <= 1825:
            score = 70
        elif age_days <= 3650:
            score = 60
        else:
            score = 50

    return score, age_days


def age_bucket(age_days: int | None) -> str:
    if age_days is None:
        return "unknown"
    if age_days <= 1:
        return "today"
    if age_days <= 7:
        return "7_days"
    if age_days <= 30:
        return "30_days"
    if age_days <= 90:
        return "90_days"
    if age_days <= 365:
        return "1_year"
    return "older"


def parse_date_best_effort(value: str | None) -> datetime | None:
    """Parse common date strings; return None if unreliable."""
    text = (value or "").strip()
    if not text:
        return None

    # ISO-like
    match = re.search(
        r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})",
        text,
    )
    if match:
        try:
            return datetime(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                tzinfo=timezone.utc,
            )
        except ValueError:
            pass

    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%Y/%m/%d",
    ):
        try:
            sample = text[:32]
            dt = datetime.strptime(sample, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    # Year-month only → mid-month (lower confidence callers should mark).
    ym = re.search(r"(20\d{2})[-/.年](\d{1,2})", text)
    if ym:
        try:
            return datetime(int(ym.group(1)), int(ym.group(2)), 15, tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def extract_date_from_html(html: str) -> tuple[datetime | None, str, str]:
    """Best-effort date from HTML meta tags / visible text.

    Returns (published_at, date_source, date_confidence).
    """
    if not html:
        return None, "none", "none"

    # Meta property patterns
    meta_patterns = [
        (r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']', "html_meta"),
        (r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']', "html_meta"),
        (r'<meta[^>]+name=["\']pubdate["\'][^>]+content=["\']([^"\']+)["\']', "html_meta"),
        (r'<meta[^>]+name=["\']publishdate["\'][^>]+content=["\']([^"\']+)["\']', "html_meta"),
        (r'<meta[^>]+itemprop=["\']datePublished["\'][^>]+content=["\']([^"\']+)["\']', "html_meta"),
        (r'"datePublished"\s*:\s*"([^"]+)"', "json_ld"),
        (r'<time[^>]+datetime=["\']([^"\']+)["\']', "html_time"),
    ]
    for pattern, source in meta_patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            dt = parse_date_best_effort(match.group(1))
            if dt:
                return dt, source, "high"

    # Visible Chinese / numeric date in early body text
    text = re.sub(r"<[^>]+>", " ", html[:8000])
    text = re.sub(r"\s+", " ", text)
    dt = parse_date_best_effort(text)
    if dt:
        return dt, "page_text", "medium"
    return None, "none", "none"


def extract_date_from_text(text: str) -> tuple[datetime | None, str, str]:
    dt = parse_date_best_effort((text or "")[:2000])
    if dt:
        return dt, "article_text", "low"
    return None, "none", "none"
