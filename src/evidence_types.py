"""A-share evidence type taxonomy and rule-based source classification.

Isolated and extensible. Classification is best-effort — imperfect labels are OK.
"""

from __future__ import annotations

from enum import Enum
from urllib.parse import urlparse


class EvidenceType(str, Enum):
    GOVERNMENT_POLICY = "GOVERNMENT_POLICY"
    EXCHANGE_ANNOUNCEMENT = "EXCHANGE_ANNOUNCEMENT"
    COMPANY_FILING = "COMPANY_FILING"
    COMPANY_IR = "COMPANY_IR"
    BROKER_RESEARCH = "BROKER_RESEARCH"
    INDUSTRY_ASSOCIATION = "INDUSTRY_ASSOCIATION"
    ACADEMIC_RESEARCH = "ACADEMIC_RESEARCH"
    FINANCIAL_NEWS = "FINANCIAL_NEWS"
    INDUSTRY_MEDIA = "INDUSTRY_MEDIA"
    MARKET_DATA = "MARKET_DATA"
    GENERAL_WEB = "GENERAL_WEB"


# Preferred domains by evidence type (ranking hints, never hard bans).
PREFERRED_DOMAINS: dict[EvidenceType, tuple[str, ...]] = {
    EvidenceType.GOVERNMENT_POLICY: (
        "gov.cn",
        "miit.gov.cn",
        "ndrc.gov.cn",
        "mofcom.gov.cn",
        "cac.gov.cn",
        "pbc.gov.cn",
    ),
    EvidenceType.EXCHANGE_ANNOUNCEMENT: (
        "cninfo.com.cn",
        "sse.com.cn",
        "szse.cn",
        "bse.cn",
    ),
    EvidenceType.COMPANY_FILING: (
        "cninfo.com.cn",
        "sse.com.cn",
        "szse.cn",
        "bse.cn",
        "eastmoney.com",
    ),
    EvidenceType.COMPANY_IR: (
        "cninfo.com.cn",
        "eastmoney.com",
    ),
    EvidenceType.BROKER_RESEARCH: (
        "dfcfw.com",
        "eastmoney.com",
        "hibor.com.cn",
        "r.lianzi.com",
    ),
    EvidenceType.FINANCIAL_NEWS: (
        "stcn.com",
        "cls.cn",
        "finance.sina.com.cn",
        "sina.com.cn",
        "jwview.com",
        "yicai.com",
        "caixin.com",
        "wallstreetcn.com",
        "jrj.com.cn",
    ),
    EvidenceType.INDUSTRY_MEDIA: (
        "c114.com.cn",
        "ofweek.com",
        "chyxx.com",
        "askci.com",
        "chinabaogao.com",
    ),
    EvidenceType.ACADEMIC_RESEARCH: (
        "cnki.net",
        "spacejournal.cn",
        "ieee.org",
        "arxiv.org",
    ),
    EvidenceType.INDUSTRY_ASSOCIATION: (
        "ccia.org.cn",
        "caict.ac.cn",
    ),
    EvidenceType.MARKET_DATA: (
        "eastmoney.com",
        "sina.com.cn",
        "stcn.com",
        "cls.cn",
    ),
    EvidenceType.GENERAL_WEB: (),
}

_DOMAIN_TYPE_RULES: tuple[tuple[tuple[str, ...], EvidenceType], ...] = (
    (("miit.gov.cn", "ndrc.gov.cn", "mofcom.gov.cn", "gov.cn"), EvidenceType.GOVERNMENT_POLICY),
    (("cninfo.com.cn", "sse.com.cn", "szse.cn", "bse.cn"), EvidenceType.EXCHANGE_ANNOUNCEMENT),
    (("stcn.com", "cls.cn", "jwview.com", "yicai.com", "caixin.com", "wallstreetcn.com", "jrj.com.cn"), EvidenceType.FINANCIAL_NEWS),
    (("finance.sina.com.cn", "sina.com.cn", "eastmoney.com", "caifuhao.eastmoney.com"), EvidenceType.FINANCIAL_NEWS),
    (("cnki.net", "arxiv.org", "ieee.org", "spacejournal.cn"), EvidenceType.ACADEMIC_RESEARCH),
    (("caict.ac.cn", "ccia.org.cn"), EvidenceType.INDUSTRY_ASSOCIATION),
    (("chyxx.com", "askci.com", "chinabaogao.com", "ofweek.com", "c114.com.cn"), EvidenceType.INDUSTRY_MEDIA),
    (("dfcfw.com", "hibor.com.cn"), EvidenceType.BROKER_RESEARCH),
)


def domain_of(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or "unknown"


def classify_evidence_type(
    url: str,
    *,
    title: str = "",
    snippet: str = "",
) -> EvidenceType:
    """Rule-based evidence type for a URL/title/snippet."""
    host = domain_of(url)
    blob = f"{title} {snippet} {url}".lower()

    for domains, etype in _DOMAIN_TYPE_RULES:
        for d in domains:
            if host == d or host.endswith("." + d):
                # Filings vs IR nuance for exchange hosts.
                if etype == EvidenceType.EXCHANGE_ANNOUNCEMENT:
                    if any(
                        k in blob
                        for k in (
                            "年报",
                            "年度报告",
                            "半年报",
                            "季报",
                            "annual",
                            "报告全文",
                            "filing",
                        )
                    ):
                        return EvidenceType.COMPANY_FILING
                    if any(k in blob for k in ("投资者关系", "调研", "ir ", "路演")):
                        return EvidenceType.COMPANY_IR
                return etype

    if any(
        k in blob
        for k in ("年报", "年度报告", "半年报", "招股说明书", "定期报告", "annual report")
    ):
        return EvidenceType.COMPANY_FILING
    if any(k in blob for k in ("投资者关系", "机构调研", "业绩说明会")):
        return EvidenceType.COMPANY_IR
    if any(k in blob for k in ("研报", "券商", "broker", "深度报告")):
        return EvidenceType.BROKER_RESEARCH
    if any(k in blob for k in ("政策", "通知", "指导意见", "工信部", "发改委")):
        return EvidenceType.GOVERNMENT_POLICY
    if any(k in blob for k in ("公告", "中标", "扩产", "订单")) and (
        "cninfo" in host or "sse." in host or "szse" in host
    ):
        return EvidenceType.EXCHANGE_ANNOUNCEMENT
    if host.endswith(".gov.cn") or host.endswith(".gov"):
        return EvidenceType.GOVERNMENT_POLICY
    if any(k in blob for k in ("协会", "alliance", "association")):
        return EvidenceType.INDUSTRY_ASSOCIATION
    return EvidenceType.GENERAL_WEB


def preference_boost(
    url: str,
    preferred_types: list[EvidenceType] | list[str],
    preferred_domains: list[str] | None = None,
) -> float:
    """Soft ranking boost in [0, 0.25] for preferred types/domains."""
    etype = classify_evidence_type(url)
    preferred = {
        (t.value if isinstance(t, EvidenceType) else str(t)).upper()
        for t in (preferred_types or [])
    }
    boost = 0.0
    if etype.value in preferred:
        boost += 0.12
    host = domain_of(url)
    domains = list(preferred_domains or [])
    for t in preferred:
        try:
            domains.extend(PREFERRED_DOMAINS.get(EvidenceType(t), ()))
        except ValueError:
            continue
    for d in domains:
        d = (d or "").lower().lstrip(".")
        if d and (host == d or host.endswith("." + d)):
            boost += 0.10
            break
    return min(0.25, boost)
