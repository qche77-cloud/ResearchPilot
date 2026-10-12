import streamlit as st
from src.judgments import propose, VERDICTS
from src.evidence_cards import render_cards
from src.stock_research import stock_history


def render_judgment(store, repo, code, thesis):
    st.caption('核查建议：仅使用已有报告；生成一次会调用模型，不追加搜索。')
    history = [s for s in stock_history(store, repo, code) if s.report and s.status == 'completed']
    if history:
        chosen = st.selectbox('选择核查报告', history, format_func=lambda s: s.created_at[:10] + ' · ' + s.topic[:40], key='judge_report_' + thesis['id'])
        if st.button('生成假设核查建议', key='judge_' + thesis['id']):
            try:
                with st.spinner('核对已有证据，生成待确认建议…'):
                    version, payload = propose(chosen, thesis)
                    store.save_proposal(code, thesis['id'], chosen.run_id, version, payload)
                st.success('已保存为待确认建议，原判断未修改。')
            except Exception as exc:
                st.error(str(exc) if isinstance(exc, ValueError) else '模型请求失败，未修改原判断；请稍后重试。')
    else:
        st.info('需要先完成一次该公司的研究。')
    for item in [p for p in store.proposals(code) if p['thesis_id'] == thesis['id']]:
        p = item['payload']
        with st.expander(f'{item["status"]} · 建议{p["verdict"]} · {item["created"][:16]}'):
            st.write('模型推断（待人工核实）：' + p['reason'])
            st.write('证据缺口：' + (p['gaps'] or '模型未列出缺口，不等于不存在。'))
            for side, label in [('supporting', '支持证据'), ('contrary', '反面证据')]:
                quotes = [q for q in p['quotes'] if q['side'] == side]
                st.markdown('**' + label + '**')
                if not quotes:
                    st.caption('未找到可校验摘录；不能解释为不存在。')
                for q in quotes:
                    st.caption(f'[{q["eid"]}] {q["title"]} · 日期 {q["date"] or "未知"}')
                    st.text(q['quote'])
            with st.expander('核对该建议的固定证据版本'):
                render_cards(p['snapshot'])
            if item['status'] == 'pending':
                with st.form('confirm_' + item['id']):
                    verdict = st.selectbox('我的判断', VERDICTS, index=VERDICTS.index(p['verdict']))
                    reason = st.text_area('确认理由（可修改）', p['reason'])
                    checked = st.checkbox('我已核对来源，确认将上述判断写入复盘历史')
                    if st.form_submit_button('确认并保存新版本'):
                        if not checked:
                            st.warning('请先核对来源并勾选确认。')
                        else:
                            try:
                                store.confirm_proposal(item['id'], verdict, reason)
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))
                if st.button('不采纳该建议', key='reject_' + item['id']):
                    store.reject_proposal(item['id'])
                    st.rerun()
    with st.expander('判断与复盘版本历史'):
        for version in store.review_history(thesis['id']):
            st.caption(version['created'] + (' · 已确认模型建议' if version['proposal_id'] else ' · 手动复盘'))
            st.write('之前：' + version['before']['status'] + ' · ' + (version['before']['review'] or '暂无复盘'))
            st.write('之后：' + version['after']['status'] + ' · ' + version['after']['review'])
