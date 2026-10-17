"""Conservative, offline claim-to-source checks, never general entailment proof.

A supported result means a complete source statement matches verbatim. Narrow
percentage/direction conflicts require an otherwise identical statement. Neither
rule certifies source truth, causality, freshness or independent corroboration.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import re

from src.verifier import CITATION, citation_ids, text_conflicts

METHOD = 'claim_source_rules_v1'
LABELS = {'supported': '原文陈述匹配', 'contradicted': '发现直接冲突',
          'mixed': '引用间存在冲突', 'insufficient_evidence': '证据不足'}
SKIP_SECTIONS = {'Sources', '证据缺口', '研究健康度', 'Research Health'}
BOUNDARY = re.compile(r'[。！？!?；;\n]+|(?<!\d)\.(?!\d)')


def statement_spans(text):
    """Yield original text offsets; decimal points remain inside statements."""
    at = 0
    for match in BOUNDARY.finditer(text):
        end = match.end()
        value = text[at:end]
        if value.strip():
            yield at, end, value
        at = end
    if text[at:].strip():
        yield at, len(text), text[at:]


def _clean(text):
    text = CITATION.sub('', text).strip()
    text = re.sub(r'^\s*(?:[-*>]\s+|\d+[.)]\s+|#{1,6}\s+)', '', text)
    # Formatting markers only; qualifiers, entity, period and units are preserved.
    return text.replace('**', '').strip().strip('。！？!?；;. \t\r\n')


def _canonical(text):
    return re.sub(r'\s+', ' ', _clean(text)).casefold()


def _template(text):
    value = _canonical(text)
    value = re.sub(r'[-+]?\d+(?:\.\d+)?\s*[%％]', '<percent>', value)
    return re.sub(r'增长|上升|增加|提升|下降|下滑|减少|降低|increased|decreased|grew|fell|rose|declined',
                  '<direction>', value)


def report_claims(report):
    """Sentence-level units, not an LLM claim extractor. Compound claims abstain."""
    for si, section in enumerate(report.sections):
        if section.title in SKIP_SECTIONS or '健康' in section.title:
            continue
        # Writers may place references after punctuation. Attach those to the
        # preceding statement rather than silently dropping a citation-only span.
        content = re.sub(r'([。！？!?;；]|(?<!\d)\.(?!\d))([ \t]*(?:\[E\d+\][ \t]*)+)',
                         r'\2\1', section.content, flags=re.I)
        content = re.sub(r'(?m)^\s*\d+\.\s+', '', content)
        for ordinal, (_, _, span) in enumerate(statement_spans(content)):
            text = _clean(span)
            if not text or re.fullmatch(r'[-:|\s]+', text) or span.lstrip().startswith('#'):
                continue
            key = f'{si}:{ordinal}:{span}'
            yield {'id': 'C' + hashlib.sha256(key.encode()).hexdigest()[:16],
                   'section': section.title, 'section_index': si, 'text': text, 'citation_ids': sorted(citation_ids(span)),
                   'raw': span.strip()}


def _reference(claim, eid, item):
    if item is None:
        return {'evidence_id': eid, 'status': 'unresolved', 'reason': 'invalid_citation', 'excerpts': []}
    source = item.source
    doc = item.document
    text = doc.extracted_text or ''
    eligible = doc.read_status == 'success' and not doc.snippet_fallback and item.keep
    from src.stock_research import is_listing_source
    eligible = eligible and not is_listing_source(source.url)
    candidates = []
    for start, end, excerpt in statement_spans(text):
        relation, reason = 'unknown', 'no_deterministic_match'
        if eligible and len(_canonical(claim)) >= 8 and _canonical(claim) == _canonical(excerpt):
            relation, reason = 'supports', 'complete_statement_match'
        elif eligible and _template(claim) == _template(excerpt):
            conflicts = text_conflicts(claim, excerpt)
            if conflicts:
                relation, reason = 'contradicts', ','.join(conflicts)
        candidates.append({'text': excerpt, 'start': start, 'end': end,
                           'relation': relation, 'reason': reason})
    relevant = [c for c in candidates if c['relation'] != 'unknown']
    relations = {c['relation'] for c in relevant}
    status = ('mixed' if len(relations) > 1 else 'supports' if 'supports' in relations else
              'contradicts' if 'contradicts' in relations else 'unknown')
    # Never truncate a matching statement: offsets always resolve the exact quote.
    return {'evidence_id': eid, 'source_id': source.source_id, 'title': source.title,
            'url': source.url, 'published_at': source.published_at or source.published_date,
            'date_source': source.date_source, 'date_confidence': source.date_confidence,
            'read_status': doc.read_status, 'eligible': eligible, 'status': status,
            'reason': 'checked_saved_document' if eligible else 'source_not_eligible',
            'excerpts': relevant or candidates[:1]}


def verify_claims(report, synthesis):
    claims = []
    for claim in report_claims(report):
        references = [_reference(claim['text'], eid, synthesis.evidence_index.get(eid))
                      for eid in claim['citation_ids']]
        support = any(r['status'] in {'supports', 'mixed'} for r in references)
        conflict = any(r['status'] in {'contradicts', 'mixed'} for r in references)
        unresolved = any(r['status'] == 'unresolved' for r in references)
        status = ('mixed' if support and conflict else 'contradicted' if conflict else
                  'supported' if support and not unresolved else 'insufficient_evidence')
        issues = []
        if not references:
            issues.append('missing_citation')
        if unresolved:
            issues.append('invalid_citation')
        if not support and not conflict:
            issues.append('no_deterministic_support')
        if conflict:
            issues.append('direct_source_conflict')
        claims.append({**claim, 'status': status, 'label': LABELS[status], 'issues': issues,
                       'references': references, 'method': METHOD,
                       'semantic_support': 'verbatim_only' if status == 'supported' else 'unknown'})
    counts = {status: 0 for status in LABELS}
    counts.update(Counter(c['status'] for c in claims))
    return {'method': METHOD, 'claims': claims,
            'claim_summary': {'total': len(claims), **counts,
                              'statement_match_rate': counts['supported'] / len(claims) if claims else None},
            'all_claims_matched': bool(claims) and all(c['status'] == 'supported' for c in claims),
            'limitations': ['Complete-statement matches establish attribution to saved text, not source truth.',
                            'Paraphrases, causality, freshness and unstated context require independent review.',
                            'Conflicts require matching entity/period/unit text apart from direction and percentages.',
                            'Only cited documents are checked; uncited counterevidence may remain undiscovered.']}
