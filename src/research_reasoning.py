"""Explicit hypotheses, bounded financial reflection and lightweight evidence graph."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import copy
import json
import re

from src.financial_analysis import identity, number
from src.models import ResearchPlanStep
from src.evidence_strategy import attach_evidence_strategies
from src.verifier import citation_ids, verify_report
from src.observability import traced_tool


def normalized_query(query):
    return re.sub(r'\s+', ' ', str(query)).strip().casefold()


def query_is_new(state, query):
    return normalized_query(query) not in {normalized_query(q) for q in state.diagnostics.get('agent', {}).get('queries', [])}


def _hypothesis(content, criterion, key, origin='agent'):
    return {'id': identity(key, 'H'), 'content': content, 'criterion': criterion, 'origin': origin,
            'supporting': [], 'contrary': [], 'questions': ['尚无独立核验的证据判断'],
            'judgment': 'open', 'uncertainty': 'high', 'semantic_support': 'unknown', 'history': []}


def initialize_hypotheses(state):
    hypotheses = state.diagnostics.setdefault('hypotheses', [])
    ids = {h['id'] for h in hypotheses}
    agent = state.diagnostics.get('agent', {})
    symbol = agent.get('stock_symbol') or state.diagnostics.get('financial_analysis', {}).get('symbol') or state.topic
    for previous in agent.get('prior_hypotheses', []):
        if previous['id'] not in ids:
            remembered = copy.deepcopy(previous)
            remembered['previous_judgment'] = previous['judgment']
            remembered.update(supporting=[], contrary=[], judgment='open', uncertainty='high',
                              questions=['历史判断需用本轮证据重新验证，不自动沿用过往支持或反例'])
            hypotheses.append(remembered)
            ids.add(remembered['id'])
    if state.plan:
        proposals = agent.get('planned_hypotheses', {})
        for step in state.plan.steps:
            proposal = proposals.get(step.title, {})
            item = _hypothesis(proposal.get('content') or f'待验证：{step.title}',
                               proposal.get('criterion') or step.description,
                               [symbol, 'task', step.title])
            item['task'] = step.title
            if item['id'] not in ids:
                hypotheses.append(item)
                ids.add(item['id'])
    for thesis in agent.get('stock_theses', []):
        item = _hypothesis(thesis['thesis'], thesis.get('invalidation', ''), [symbol, 'user', thesis['id']], 'user_view')
        item['questions'] = ['用户观点保留，尚未独立验证；不会自动修改原投资复盘']
        if item['id'] not in ids:
            hypotheses.append(item)
            ids.add(item['id'])
    if state.diagnostics.get('financial_analysis'):
        for rule, content, criterion in [
            ('revenue_profit_alignment', '营收增长能够伴随利润增长', '同期间同口径营收同比为正时，利润同比也应为正；背离是反例，不推断原因'),
            ('profit_cash_alignment', '利润增长能获得经营现金流改善支撑', '同期间同口径利润同比为正时，经营现金流同比也应为正；背离是反例'),
        ]:
            item = _hypothesis(content, criterion, [symbol, rule])
            item['rule'] = rule
            if item['id'] not in ids:
                hypotheses.append(item)
                ids.add(item['id'])
    return hypotheses


def _financial_pairs(state, first_metrics, second_metrics):
    groups = {}
    for c in state.diagnostics.get('financial_analysis', {}).get('computations', []):
        if c['kind'] != 'yoy' or c['status'] != 'ok':
            continue
        key = tuple(c.get(k) for k in ('symbol', 'period_end', 'basis', 'currency', 'scope'))
        groups.setdefault(key, {}).setdefault(c['metric'], []).append(c)
    for key in sorted(groups, key=lambda k: (k[1], k[2] == 'cumulative'), reverse=True):
        group = groups[key]
        left = next((group[m][0] for m in first_metrics if m in group and len(group[m]) == 1), None)
        right = next((group[m][0] for m in second_metrics if m in group and len(group[m]) == 1), None)
        if left and right:
            return left, right
    return None


def update_hypotheses(state):
    hypotheses = initialize_hypotheses(state)
    for h in hypotheses:
        rule = h.get('rule')
        if not rule:
            h['context_source_ids'] = [d.source.source_id for d in state.documents
                                       if h.get('task') and d.source.source_id and d.source.research_task == h['task'] and d.read_status == 'success']
            continue
        before = {k: h[k] for k in ('judgment', 'supporting', 'contrary', 'questions', 'uncertainty')}
        pair = _financial_pairs(state, ('revenue', 'total_revenue'), ('attributable_net_profit', 'net_profit')) if rule == 'revenue_profit_alignment' else _financial_pairs(state, ('attributable_net_profit', 'net_profit'), ('operating_cash_flow',))
        h.update(supporting=[], contrary=[], questions=['缺少同期间、同币种和同报表范围的可比同比数据'], judgment='open', uncertainty='high')
        if pair:
            first, second = pair
            observation = {'period': first['period_end'], 'basis': first['basis'], 'currency': first['currency'],
                           'scope': first['scope'], 'evidence_ids': [first['id'], second['id']],
                           'input_ids': first['input_ids'] + second['input_ids'],
                           'values': {first['metric']: first['value'], second['metric']: second['value']},
                           'method': 'deterministic_direction_comparison'}
            h['questions'] = ['该方向比较不能证明因果或未来持续性']
            if number(first['value']) > 0 and number(second['value']) <= 0:
                h.update(contrary=[observation], judgment='contradicted_by_data', uncertainty='medium')
                h['questions'] = ['需要核对毛利率、费用率、业务结构或现金流变化原因；尚不能断言原因']
            elif number(first['value']) > 0 and number(second['value']) > 0:
                h.update(supporting=[observation], judgment='direction_supported', uncertainty='medium')
            else:
                h['questions'] = ['前提未满足，不能确认该假设；需核对业绩变化原因']
        after = {k: h[k] for k in before}
        if before != after:
            h['history'].append({'at': datetime.now(timezone.utc).isoformat(), 'before': before, 'after': after})
    return hypotheses


@traced_tool('research.reflect')
def reflect_plan(state):
    """Revise the plan once per explicit trigger; never add search budget."""
    hypotheses = update_hypotheses(state)
    if state.plan is None:
        return []
    agent = state.diagnostics.setdefault('agent', {})
    revisions = agent.setdefault('automatic_revisions', [])
    if len(revisions) >= agent.get('max_automatic_revisions', 2):
        return []
    applied = {r['trigger'] for r in revisions}
    changes = []
    for h in hypotheses:
        rule = h.get('rule')
        if h['judgment'] != 'contradicted_by_data' or not rule or rule in applied:
            continue
        prior = asdict(state.plan)
        additions = ['毛利率变化', '费用率变化', '业务结构变化'] if rule == 'revenue_profit_alignment' else ['经营现金流与利润差异', '应收账款与存货变化']
        symbol = agent.get('stock_symbol') or state.diagnostics.get('financial_analysis', {}).get('symbol') or state.topic
        period = h['contrary'][0]['period']
        pending = agent.setdefault('reflection_pending', [])
        for title in additions:
            existing = next((s for s in state.plan.steps if title in s.title), None)
            query = f'{symbol} {period} {title} 年报 公告 原始数据'
            if not existing:
                existing = ResearchPlanStep(len(state.plan.steps) + 1, title,
                    '由同期间财务背离触发；寻找解释与反例，统一单位和口径，不预设原因。', [query])
                state.plan.steps.append(existing)
            if query_is_new(state, query) and not any(normalized_query(p['query']) == normalized_query(query) for p in pending):
                pending.append({'action': 'search', 'task': existing.title, 'query': query,
                                'reason': f'财务反思：{h["content"]} 出现同期间数据反例，补查{title}',
                                'trigger_hypothesis': h['id']})
        attach_evidence_strategies(state.plan, state.analyzed_query)
        revision = {'at': datetime.now(timezone.utc).isoformat(), 'trigger': rule, 'hypothesis_id': h['id'],
                    'evidence': h['contrary'], 'before': prior, 'after': asdict(state.plan)}
        revisions.append(revision)
        changes.append(revision)
        applied.add(rule)
        if len(revisions) >= agent.get('max_automatic_revisions', 2):
            break
    initialize_hypotheses(state)
    return changes


def build_evidence_graph(state):
    """Derived SQLite-compatible adjacency lists; IDs are namespaced by run."""
    nodes, edges = {}, []
    prefix = state.run_id + ':'
    def node(kind, key, **fields):
        nid = prefix + kind + ':' + str(key)
        nodes[nid] = {'id': nid, 'kind': kind, **fields}
        return nid
    def edge(source, target, relation, **fields):
        edges.append({'source': source, 'target': target, 'relation': relation, **fields})
    analysis = state.diagnostics.get('financial_analysis', {})
    for r in analysis.get('records', []) + analysis.get('quarter_records', []) + analysis.get('ttm_records', []):
        nid = node('financial_input', r['id'], metric=r['metric'], period=r['period_end'], value=r['value'],
                   status=r['status'], updated_at=r['fetched_at'])
        if r['source_url']:
            origin = node('source', r['source_url'], url=r['source_url'])
            edge(nid, origin, 'sourced_from')
        for parent in r['input_ids']:
            edge(nid, prefix + 'financial_input:' + parent, 'derived_from')
    for c in analysis.get('computations', []):
        nid = node('calculation', c['id'], metric=c['metric'], value=c['value'], formula=c['formula'], status=c['status'])
        for parent in c['input_ids']:
            edge(nid, prefix + 'financial_input:' + parent, 'derived_from')
    market = analysis.get('market_input')
    if market:
        mid = node('market_input', market['id'], value=market.get('value'), as_of=market.get('as_of'))
        if market.get('source_url'):
            edge(mid, node('source', market['source_url'], url=market['source_url']), 'sourced_from')
        for v in analysis.get('valuations', []):
            if v['status'] == 'ok':
                vid = node('valuation', v['id'], value=v['value'], formula=v['formula'])
                edge(vid, mid, 'derived_from')
                edge(vid, prefix + 'financial_input:' + v['input_ids'][1], 'derived_from')
    for d in state.documents:
        sid = node('source', d.source.url, url=d.source.url, published_at=d.source.published_date)
        eid = node('document', d.source.source_id or identity(d.source.url), title=d.source.title, read_status=d.read_status)
        edge(eid, sid, 'sourced_from')
    for h in state.diagnostics.get('hypotheses', []):
        hid = node('hypothesis', h['id'], content=h['content'], judgment=h['judgment'], uncertainty=h['uncertainty'])
        for side in ('supporting', 'contrary'):
            for observation in h[side]:
                for eid in observation['evidence_ids']:
                    edge(hid, prefix + 'calculation:' + eid, 'supported_by' if side == 'supporting' else 'opposed_by')
        for sid in h.get('context_source_ids', []):
            edge(hid, prefix + 'document:' + sid, 'has_context', semantic_support='unknown')
    if state.synthesis:
        from src.synthesizer import CONTENT_SECTIONS
        for eid, item in state.synthesis.evidence_index.items():
            enode = node('evidence', eid, title=item.source.title, updated_at=item.source.published_date)
            did = prefix + 'document:' + str(item.source.source_id or identity(item.source.url))
            edge(enode, did, 'extracted_from')
        for section in CONTENT_SECTIONS:
            for finding in getattr(state.synthesis, section) or []:
                cid = node('conclusion', identity([section, finding.finding]), text=finding.finding, type=finding.finding_type)
                for eid in finding.evidence_ids:
                    if eid in state.synthesis.evidence_index:
                        edge(cid, prefix + 'evidence:' + eid, 'cites', semantic_support='unknown')
                        task = state.synthesis.evidence_index[eid].source.research_task
                        for h in state.diagnostics.get('hypotheses', []):
                            numeric_ids = [cid for side in ('supporting', 'contrary') for o in h[side] for cid in o['evidence_ids']]
                            if h.get('task') == task or any(cid in state.synthesis.evidence_index[eid].document.extracted_text for cid in numeric_ids):
                                edge(cid, prefix + 'hypothesis:' + h['id'], 'addresses')
    if state.report and state.synthesis:
        for claim in verify_report(state.report, state.synthesis)['claims']:
            cid = node('report_claim', claim['id'], text=claim['text'], section=claim['section'],
                       status=claim['status'], semantic_support=claim['semantic_support'])
            for reference in claim['references']:
                relation = {'supports': 'matches_statement', 'contradicts': 'conflicts_with',
                            'mixed': 'conflicting_statements'}.get(reference['status'], 'cites_unverified')
                edge(cid, prefix + 'evidence:' + reference['evidence_id'], relation,
                     excerpts=reference['excerpts'])
    # Missing IDs are visible diagnostics, not invented source nodes.
    dangling = [e for e in edges if e['source'] not in nodes or e['target'] not in nodes]
    graph = {'run_id': state.run_id, 'nodes': list(nodes.values()), 'edges': edges, 'dangling_edges': dangling}
    state.diagnostics['evidence_graph'] = graph
    return graph


@traced_tool('research.critic')
def critic_review(state):
    """Independent deterministic role; conservative semantic result is unknown."""
    report_check = verify_report(state.report, state.synthesis) if state.report and state.synthesis else {'passed': False, 'reason': 'no_report'}
    warnings = []
    cited = set().union(*(citation_ids(s.content) for s in state.report.sections)) if state.report else set()
    cited_text = '\n'.join(state.synthesis.evidence_index[e].document.extracted_text for e in cited
                           if state.synthesis and e in state.synthesis.evidence_index)
    for h in state.diagnostics.get('hypotheses', []):
        if h['contrary'] and not all(eid in cited_text for o in h['contrary'] for eid in o['evidence_ids']):
            warnings.append({'code': 'counterevidence_not_in_report_citations', 'hypothesis_id': h['id']})
    for code, statuses in [('claim_source_conflict', {'contradicted', 'mixed'}),
                           ('claim_support_unresolved', {'insufficient_evidence'})]:
        ids = [c['id'] for c in report_check.get('claims', []) if c['status'] in statuses]
        if ids:
            warnings.append({'code': code, 'claim_ids': ids})
    review = {'role': 'deterministic_critic', 'passed': report_check['passed'], 'report_check': report_check,
              'warnings': warnings, 'semantic_support': 'unknown',
              'claim_summary': report_check.get('claim_summary'),
              'limitations': '编号、摘录、有限方向/数值规则可验证；一般语义、因果和证据穷尽性未被证明。'}
    state.diagnostics['critic'] = review
    return review
