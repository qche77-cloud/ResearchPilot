"""Immutable report/evidence snapshots referenced by chat messages."""
import hashlib
import json
import copy


def snapshot_report(state):
    from src.stock_research import is_listing_source
    if not state.report:
        return None
    evidence = {}
    if state.synthesis:
        for eid, item in state.synthesis.evidence_index.items():
            evidence[eid] = {'title': item.source.title, 'url': item.source.url,
                             'date': item.source.published_date, 'text': item.document.extracted_text,
                             'read_status': item.document.read_status,
                             'listing_page': is_listing_source(item.source.url),
                             'date_source': item.source.date_source, 'date_confidence': item.source.date_confidence}
    findings = []
    if state.synthesis:
        from src.synthesizer import CONTENT_SECTIONS
        for section in CONTENT_SECTIONS:
            for f in getattr(state.synthesis, section, []) or []:
                findings.append({'text': f.finding, 'kind': f.finding_type, 'evidence_ids': f.evidence_ids,
                                 'excerpts': [{'evidence_id': q.evidence_id, 'text': q.excerpt} for q in f.supporting_excerpts]})
    payload = {'sections': [{'title': s.title, 'content': s.content} for s in state.report.sections],
               'evidence': evidence, 'findings': findings}
    if state.diagnostics.get('hypotheses'):
        payload['hypotheses'] = copy.deepcopy(state.diagnostics['hypotheses'])
    if state.diagnostics.get('financial_analysis'):
        from src.research_memory import financial_snapshot
        payload['financial_analysis'] = copy.deepcopy(financial_snapshot(state.diagnostics['financial_analysis']))
    if state.diagnostics.get('evidence_graph'):
        payload['evidence_graph'] = copy.deepcopy(state.diagnostics['evidence_graph'])
    version = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    agent = state.diagnostics.setdefault('agent', {'budget': 2, 'searches': 0, 'events': [], 'queries': [], 'instructions': [], 'empty_searches': 0})
    # Reading an unchanged report must not create versions from a new timestamp.
    payload['as_of'] = agent.get('report_as_of') or state.updated_at
    agent.setdefault('report_versions', {}).setdefault(version, payload)
    return version


def brief_report(state):
    if state.diagnostics.get('agent', {}).get('update_mode'):
        from src.stock_research import update_brief
        return update_brief(state)
    findings = state.synthesis.key_findings if state.synthesis else []
    summary = '；'.join(f.finding for f in findings[:2])
    if not summary:
        return '研究结果已整理，完整结论及其证据请通过下方入口查看。'
    return summary[:220] + ('…' if len(summary) > 220 else '')


def normalize_history(state):
    """Normalize legacy presentation without deleting reports or original messages."""
    a = state.diagnostics.get('agent')
    initialized = not isinstance(a, dict)
    if not isinstance(a, dict):
        a = {'budget': 2, 'searches': 0, 'events': [], 'queries': [],
             'instructions': [], 'empty_searches': 0}
        state.diagnostics['agent'] = a
    version = snapshot_report(state)
    if not version:
        return initialized
    messages = a.setdefault('messages', [{'role': 'user', 'content': state.topic}])
    changed = False
    legacy = '\n\n'.join(f'### {s.title}\n{s.content}' for s in state.report.sections)
    for message in messages:
        if message.get('role') != 'assistant':
            continue
        content = message.get('content', '')
        original = message.get('original_content')
        linked = a.get('report_versions', {}).get(message.get('report_version'))
        if original and linked:
            linked_text = '\n\n'.join(f'### {s["title"]}\n{s["content"]}' for s in linked['sections'])
            if original != linked_text and not message.get('citation_check'):
                # Early migrations linked arbitrary old long replies to the latest
                # report. Do not keep a provenance claim we cannot reconstruct.
                message.pop('report_version', None)
                message['provenance_note'] = '旧回答的报告版本无法核实，仅保留原文。'
                changed = True
        if not message.get('structured_summary') and not message.get('display_summary') and (content == legacy or len(content) > 350):
            message.setdefault('original_content', content)
            message['display_summary'] = brief_report(state) if content == legacy else content[:180].rstrip() + '…'
            if content == legacy:
                message.setdefault('report_version', version)
            else:
                message['provenance_note'] = '旧回答缺少可验证的版本信息，仅保留原文。'
            changed = True
    if not any(m.get('report_version') == version for m in messages):
        messages.append({'role': 'assistant', 'content': brief_report(state), 'report_version': version,
                         'structured_summary': bool(a.get('update_mode'))})
        changed = True
    a['report_in_chat'] = True
    return changed
