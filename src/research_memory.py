"""Versioned research comparisons; textual differences are not semantic proof."""
from __future__ import annotations
import hashlib
import json
import re


def financial_snapshot(analysis):
    fields = ('id', 'symbol', 'metric', 'period_start', 'period_end', 'basis', 'currency', 'scope', 'unit', 'value', 'status', 'issues', 'source_url', 'fetched_at', 'published_at', 'available_at')
    return {'records': [{k: r.get(k) for k in fields} for r in analysis.get('records', [])],
            'calculations': analysis.get('computations', []), 'valuations': analysis.get('valuations', []),
            'fetched_at': analysis.get('fetched_at'), 'as_of': analysis.get('as_of')}


def compare_snapshots(previous, current):
    previous, current = previous or {}, current or {}
    def findings(snapshot):
        return {re.sub(r'\s+', ' ', f.get('text', '')).strip(): f for f in snapshot.get('findings', []) if f.get('kind') != 'gap'}
    old, new = findings(previous), findings(current)
    old_h = {h['id']: h for h in previous.get('hypotheses', [])}
    new_h = {h['id']: h for h in current.get('hypotheses', [])}
    hypotheses, invalidated = [], []
    for hid in old_h.keys() & new_h.keys():
        before, after = old_h[hid], new_h[hid]
        if before['judgment'] != after['judgment']:
            change = {'id': hid, 'content': after['content'], 'before': before['judgment'], 'after': after['judgment'],
                      'evidence': after.get('contrary') or after.get('supporting') or [], 'questions': after.get('questions', [])}
            hypotheses.append(change)
            if before['judgment'] == 'direction_supported' and after['judgment'] == 'contradicted_by_data':
                invalidated.append(change)
    def financial_rows(snapshot):
        rows = snapshot.get('financial_analysis', {}).get('records', [])
        return {tuple(r.get(k) for k in ('symbol', 'metric', 'period_start', 'period_end', 'basis', 'currency', 'scope', 'unit')): r
                for r in rows if r.get('status') == 'ok'}
    old_rows, new_rows = financial_rows(previous), financial_rows(current)
    changed = [{'before': old_rows[k], 'after': new_rows[k]} for k in old_rows.keys() & new_rows.keys()
               if old_rows[k]['value'] != new_rows[k]['value']]
    def sources(snapshot):
        by_url = {}
        for item in snapshot.get('evidence', {}).values():
            if item.get('url'):
                by_url.setdefault(item['url'], set()).add(item.get('text', ''))
        return {url: hashlib.sha256('\n'.join(sorted(texts)).encode()).hexdigest() for url, texts in by_url.items()}
    old_sources, new_sources = sources(previous), sources(current)
    return {'baseline_as_of': previous.get('as_of'), 'current_as_of': current.get('as_of'),
            'new_conclusions': [new[t] for t in sorted(new.keys() - old.keys())],
            'removed_conclusions': [old[t] for t in sorted(old.keys() - new.keys())],
            'hypothesis_changes': sorted(hypotheses, key=lambda h: h['id']), 'invalidated_hypotheses': invalidated,
            'new_financial_records': [new_rows[k] for k in sorted(new_rows.keys() - old_rows.keys(), key=str)],
            'changed_financial_values': changed,
            'new_source_urls': sorted(new_sources.keys() - old_sources.keys()),
            'changed_source_urls': sorted(url for url in old_sources.keys() & new_sources.keys() if old_sources[url] != new_sources[url]),
            'unresolved_questions': [{'hypothesis_id': h['id'], 'question': q} for h in current.get('hypotheses', []) for q in h.get('questions', [])],
            'comparison_policy': '结论比较为文字差异；财务数值仅比较同范围同期间；来源文本变化不等于新公告或事实变化。'}


def finalize_research_memory(state):
    from src.report_links import snapshot_report
    version = snapshot_report(state)
    if not version:
        return None
    agent = state.diagnostics['agent']
    prior = agent.get('baseline', {}).get('snapshot')
    if prior:
        diff = compare_snapshots(prior, agent['report_versions'][version])
        diff['baseline_version'] = agent['baseline'].get('version')
        diff['current_version'] = version
        state.diagnostics['research_diff'] = diff
        return diff
    return None


def diff_markdown(diff):
    lines = ['# 研究版本差异', f'基线：{diff.get("baseline_as_of") or "未知"}；本轮：{diff.get("current_as_of") or "未知"}',
             '结论变化按文字比较，新增来源不代表已确认的新公告；用户原复盘未被自动修改。']
    for title, findings in [('新增结论', diff.get('new_conclusions', [])), ('不再出现在本轮的结论', diff.get('removed_conclusions', []))]:
        lines.extend(['', '## ' + title])
        lines.extend('- ' + f['text'] for f in findings)
        if not findings:
            lines.append('- 无')
    lines.extend(['', '## 假设变化'])
    lines.extend(f'- {h["content"]}：{h["before"]} → {h["after"]}' for h in diff.get('hypothesis_changes', []))
    lines.extend(['', '## 新财报期与修订值', f'- 新记录 {len(diff.get("new_financial_records", []))} 条；同期间修订值 {len(diff.get("changed_financial_values", []))} 条。'])
    for row in diff.get('changed_financial_values', []):
        before, after = row['before'], row['after']
        lines.append(f'- {after["metric"]} {after["period_end"]}：{before["value"]} → {after["value"]} {after["currency"]} {after["unit"]}；来源 {after["source_url"]}')
    lines.extend(['', '## 待验证问题'])
    lines.extend('- ' + q['question'] for q in diff.get('unresolved_questions', []))
    return '\n'.join(lines)


def snapshot_changes(previous, current):
    old_daily, new_daily = previous.get('daily') or [], current.get('daily') or []
    price_changed = bool(old_daily and new_daily and old_daily[-1].get('日期') != new_daily[-1].get('日期'))
    old_finance, new_finance = previous.get('finance'), current.get('finance')
    canonical = lambda rows: sorted(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows)
    finance_changed = bool(old_finance and new_finance and canonical(old_finance) != canonical(new_finance))
    return {'price_changed': price_changed, 'finance_changed': finance_changed, 'finance_unavailable': not bool(new_finance),
            'provider': current.get('provider', 'unknown'), 'fetched_at': current.get('fetched_at')}
