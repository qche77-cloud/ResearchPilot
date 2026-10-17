"""User-facing hypotheses, plan changes and inspectable evidence relations."""
import json
import streamlit as st

JUDGMENTS = {'open': '待验证', 'direction_supported': '数据方向支持（不证明因果）',
             'contradicted_by_data': '发现数据反例'}


def render_reasoning(state):
    hypotheses = state.diagnostics.get('hypotheses', [])
    with st.expander('研究假设：支持、反例与待验证问题'):
        if not hypotheses:
            st.caption('这份历史研究未保存研究假设记录。')
        for h in hypotheses:
            st.write(h['content'])
            st.caption(JUDGMENTS.get(h['judgment'], h['judgment']) + ' · 不确定性 ' + h['uncertainty'])
            st.caption('验证依据：' + h['criterion'])
            for side, label in [('supporting', '支持数据'), ('contrary', '反面数据')]:
                if h[side]:
                    st.write(label)
                    st.json(h[side])
            for question in h['questions']:
                st.caption('待验证：' + question)
            if h.get('origin') == 'user_view':
                st.caption('这是用户投资观点，自动研究不会覆盖原复盘。')
    with st.expander('自主计划调整'):
        changes = state.diagnostics.get('agent', {}).get('automatic_revisions', [])
        for change in changes:
            st.caption(change['at'] + ' · ' + change['trigger'])
            before = {s['title'] for s in change['before']['steps']}
            st.write('追加：' + '、'.join(s['title'] for s in change['after']['steps'] if s['title'] not in before))
            st.json(change['evidence'])
        if not changes:
            st.caption('尚无满足触发条件的自动计划修订。')
    with st.expander('结论—假设—证据—来源关联'):
        graph = state.diagnostics.get('evidence_graph', {})
        nodes = graph.get('nodes', [])
        if nodes:
            options = [n for n in nodes if n['kind'] in {'conclusion', 'hypothesis'}]
            if options:
                chosen = st.selectbox('查看结论或假设的关联', options,
                    format_func=lambda n: n.get('text') or n.get('content') or n['id'], key='reason_graph_' + state.run_id)
                # Follow only explicit relations, showing type and provenance.
                visited, frontier, relations = set(), [chosen['id']], []
                while frontier:
                    current = frontier.pop()
                    if current in visited:
                        continue
                    visited.add(current)
                    for edge in graph['edges']:
                        if edge['source'] == current:
                            relations.append(edge)
                            frontier.append(edge['target'])
                labels = {n['id']: n.get('url') or n.get('text') or n.get('content') or n.get('title') or n.get('metric') or n['id'] for n in nodes}
                st.dataframe([dict(e, source=labels.get(e['source'], e['source']), target=labels.get(e['target'], e['target'])) for e in relations], hide_index=True)
            st.download_button('下载证据关系图', json.dumps(graph, ensure_ascii=False, indent=2), 'evidence-graph.json', key='graph_dl_' + state.run_id)
        else:
            st.caption('研究综合后生成关联图；不为旧报告虚构假设关系。')
    critic = state.diagnostics.get('critic')
    if critic:
        with st.expander('结论验证与遗漏检查'):
            st.caption('完整性检查：' + ('通过' if critic['passed'] else '未通过') + '；资料是否足以支持结论，仍需核对。')
            for warning in critic['warnings']:
                if warning['code'] == 'counterevidence_not_in_report_citations':
                    st.warning('反面证据可能未进入报告引用：' + warning['hypothesis_id'])
                else:
                    st.warning(('结论与来源存在冲突：' if warning['code'] == 'claim_source_conflict' else
                                '结论依据仍需核对：') + str(len(warning.get('claim_ids', []))) + ' 条')
            for claim in critic['report_check'].get('claims', []):
                st.write(claim['label'] + '：' + claim['text'])
                for reference in claim['references']:
                    st.caption(reference['evidence_id'] + ' · ' + reference.get('title', '引用不存在'))
                    for excerpt in reference['excerpts']:
                        st.text(excerpt['text'])
            st.json(critic)
    diff = state.diagnostics.get('research_diff')
    if diff:
        from src.research_memory import diff_markdown
        with st.expander('研究版本差异：新增信息、失效假设与待验证问题', expanded=True):
            st.caption(f'新增结论 {len(diff["new_conclusions"])} · 假设变化 {len(diff["hypothesis_changes"])} · '
                       f'新财务记录 {len(diff["new_financial_records"])} · 同期间修订 {len(diff["changed_financial_values"])}')
            st.markdown(diff_markdown(diff))
            st.caption('同一链接采集文本发生变化：' + '、'.join(diff['changed_source_urls']))
            st.download_button('下载新旧研究差异', diff_markdown(diff), 'research-diff.md', key='diff_dl_' + state.run_id)
            st.download_button('下载详细差异数据', json.dumps(diff, ensure_ascii=False, indent=2), 'research-diff.json', key='diff_json_' + state.run_id)
