"""Deterministic integrity checks. Semantic entailment remains explicitly unknown."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

CITATION = re.compile(r'\[(E\d+)\]', re.I)
METRICS = {
    'revenue': ('营业收入', '营收', '收入', 'revenue'),
    'profit': ('净利润', '利润', 'profit'),
    'cash_flow': ('现金流', 'cash flow'),
    'gross_margin': ('毛利率', 'gross margin'),
}


def citation_ids(text):
    return {m.upper() for m in CITATION.findall(text)}


def _compact(text):
    return re.sub(r'\s+', '', text or '')


def _metrics(text):
    lowered = text.casefold()
    return {key for key, terms in METRICS.items() if any(term in lowered for term in terms)}


def _direction(text):
    up = bool(re.search(r'增长|上升|增加|提升|improv|increas|grow|rose', text, re.I))
    down = bool(re.search(r'下降|下滑|减少|降低|declin|decreas|fell', text, re.I))
    if re.search(r'不|未|没有|可能|预计|预期|not|may|expect', text, re.I) or up == down:
        return None
    return 'up' if up else 'down'


def text_conflicts(claim, quote):
    """Only narrow same-metric/period directional and percentage comparisons.

    Multiple metrics, periods or values are ambiguous, never proof of conflict.
    This does not certify semantic support when no conflict is detected.
    """
    issues = []
    cm, qm = _metrics(claim), _metrics(quote)
    years_claim = set(re.findall(r'(?<!\d)20\d{2}(?!\d)', claim))
    years_quote = set(re.findall(r'(?<!\d)20\d{2}(?!\d)', quote))
    if len(cm) != 1 or cm != qm or years_claim != years_quote:
        return issues
    # Different explicit periods must not be called a contradiction.
    periods = r'Q[1-4]|H[12]|[一二三四]季度|上半年|下半年|全年|TTM|同比|环比|yoy|qoq'
    if set(re.findall(periods, claim, re.I)) != set(re.findall(periods, quote, re.I)):
        return issues
    cd, qd = _direction(claim), _direction(quote)
    if cd and qd and cd != qd:
        issues.append('direction_conflict')
    cp = re.findall(r'([-+]?\d+(?:\.\d+)?)\s*[%％]', claim)
    qp = re.findall(r'([-+]?\d+(?:\.\d+)?)\s*[%％]', quote)
    if cd and qd and len(cp) == len(qp) == 1 and abs(Decimal(cp[0])) != abs(Decimal(qp[0])):
        issues.append('numeric_mismatch')
    return issues


def validate_answer(data, evidence):
    """Return structured findings; do not silently repair or erase model output."""
    text = data.get('answer', '')
    supports = data.get('supports') if isinstance(data.get('supports'), dict) else {}
    issues = []
    resolved = {}
    cited = citation_ids(text)
    markers = re.findall(r'\[(E[^\]]*)\]', text, re.I)
    if any(not re.fullmatch(r'E\d+', m, re.I) for m in markers):
        issues.append({'code': 'invalid_citation'})
    for eid in sorted(cited):
        item = evidence.get(eid)
        quote = supports.get(eid)
        if item and isinstance(quote, str):
            quote = item.get('quotes', {}).get(quote, quote)
        if not item:
            issues.append({'code': 'invalid_citation', 'evidence_id': eid})
        elif not isinstance(quote, str) or len(quote.strip()) < 8 or _compact(quote) not in _compact(item.get('text', '')):
            issues.append({'code': 'quote_mismatch', 'evidence_id': eid})
        else:
            resolved[eid] = quote
    # Only supported local claim spans can be compared. A multi-citation span is
    # not rejected merely because one source states the opposite side of a debate.
    for span in re.split(r'[。！？\n;；]|(?<!\d)\.(?!\d)', text):
        ids = citation_ids(span)
        if len(ids) == 1:
            eid = next(iter(ids))
            if eid in resolved:
                issues.extend({'code': code, 'evidence_id': eid} for code in text_conflicts(span, resolved[eid]))
        if data.get('action') != 'research' and not ids and _metrics(span) and (
            _direction(span) or re.search(r'\d+(?:\.\d+)?\s*[%％亿元万]', span)
        ):
            if not re.search(r'未知|不足|无法|待核|不能确认|不知道|unknown|insufficient|cannot', span, re.I):
                issues.append({'code': 'missing_citation'})
    return {'passed': not issues, 'issues': issues, 'cited_ids': sorted(cited),
            'semantic_support': 'unknown', 'method': 'deterministic_integrity_v1'}


def verify_report(report, synthesis):
    evidence = {eid: {'text': item.document.extracted_text} for eid, item in synthesis.evidence_index.items()}
    results = []
    for section in report.sections:
        if section.title in {'Sources', '证据缺口', '研究健康度', 'Research Health'} or '健康' in section.title:
            continue
        supports = {eid: evidence[eid]['text'] for eid in citation_ids(section.content) if eid in evidence}
        result = validate_answer({'action': 'answer', 'answer': section.content, 'supports': supports}, evidence)
        results.append({'section': section.title, **result})
    return {'passed': all(r['passed'] for r in results), 'sections': results, 'semantic_support': 'unknown'}


def compare_observations(claim, fact):
    """Compare typed facts only when scope, unit and financial basis match."""
    scope = ('entity', 'metric', 'period', 'currency', 'unit', 'basis')
    if any(not claim.get(k) or not fact.get(k) or claim[k] != fact[k] for k in scope):
        return {'status': 'unknown', 'reason': 'incomparable_scope'}
    try:
        left, right = Decimal(str(claim['value'])), Decimal(str(fact['value']))
        if not left.is_finite() or not right.is_finite():
            raise InvalidOperation()
    except (KeyError, InvalidOperation, ValueError):
        return {'status': 'unknown', 'reason': 'missing_or_invalid_value'}
    return {'status': 'consistent' if left == right else 'conflict', 'reason': 'exact_decimal_comparison'}


def evaluate_case(case):
    """Standard offline evaluation contract; unknown denominators stay visible."""
    evidence = case.get('evidence', {})
    checked = validate_answer(case.get('answer', {}), evidence)
    cited = set(checked['cited_ids'])
    omitted = [eid for eid, item in evidence.items() if item.get('relation') == 'contrary' and eid not in cited]
    if omitted:
        checked['issues'].append({'code': 'omitted_counterevidence', 'evidence_ids': sorted(omitted)})
        checked['passed'] = False
    observations = [compare_observations(p['claim'], p['fact']) for p in case.get('observations', [])]
    targets = set(case.get('required_tasks', []))
    covered = {e.get('task') for e in evidence.values() if e.get('read_status') == 'success' and not e.get('listing_page')}
    return {**checked, 'coverage': len(targets & covered) / len(targets) if targets else None,
            'observations': observations,
            'conflict_detected': any(i['code'] in {'direction_conflict', 'numeric_mismatch'} for i in checked['issues'])
                                 or any(o['status'] == 'conflict' for o in observations)}
