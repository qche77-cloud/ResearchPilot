"""Research conversation presentation; background commands use the existing runner."""
from urllib.parse import urlsplit
import streamlit as st
from src.evidence_cards import render_cards
from src.reasoning_ui import render_reasoning
from src.stock_research import update_brief
from src.trace_ui import render_trace
from src.ui_theme import page_intro, status_strip, summary_tiles, section_label, empty_state


def render_conversation(state, active, service, store, start_research, show_snapshot):
    run_id = state.run_id
    a = state.diagnostics.get('agent', {})
    outcome = a.get('outcome')
    label = '后台执行中' if active else ('执行失败' if state.status == 'failed' else
        ('部分完成' if outcome == 'partial' else ('已完成' if state.status == 'completed' else '已暂停 / 待恢复')))
    # Keep live headers static: polling must not replay the page entrance animation.
    page_intro(state.topic, '以原始资料为依据，保留反例与尚待验证的问题。', animate=False)
    summary_tiles([('研究状态', label, '后台任务与对话独立运行'),
                   ('检索预算', f'{a.get("searches", 0)} / {a.get("budget", 2)}', '已成功检索 / 本轮上限'),
                   ('来源记录', len(state.sources), '来源数量不等于有效证据数量')])
    if active:
        status_strip('正在核查资料 · 可以继续追问，也可以切换到个股工作台')
    if state.error:
        st.error(state.error)
    chat, report, evidence, reasoning = st.tabs(['研究对话', '研究报告', '证据与来源', '假设与验证'])

    with chat:
        with st.expander('任务控制', expanded=False):
            controls = st.columns(3)
            with controls[0]:
                if active:
                    if st.button('暂停研究', key='pause', use_container_width=True):
                        service.submit(run_id, 'pause')
                        st.info('暂停请求已入队，当前工具结束后生效。')
                elif state.status != 'completed':
                    if st.button('恢复研究', key='resume', use_container_width=True):
                        service.submit(run_id, 'resume')
            with controls[1]:
                if st.button('增加 3 次搜索预算', key='more', use_container_width=True):
                    service.submit(run_id, 'budget')
            with controls[2]:
                if a.get('stock_symbol') and st.button('基于档案更新研究', key='update_bound_stock', disabled=active, use_container_width=True):
                    start_research(f'更新 A 股 {a["stock_symbol"]} 的研究，对照上次结论核查新增信息。', symbol=a['stock_symbol'], update=True)
            st.caption('关闭浏览器不影响后台任务；重启本地服务后需手动恢复。')
        messages = a.get('messages', [])
        if not messages:
            empty_state('研究记录已加载', '恢复研究或继续追问，新的消息会显示在这里。')
        for number, message in enumerate(messages):
            with st.chat_message(message['role']):
                st.markdown(message.get('display_summary', message['content']))
                if message.get('original_content'):
                    with st.expander('原回答'):
                        st.markdown(message['original_content'])
                for field in ('provenance_note', 'citation_check'):
                    if message.get(field):
                        st.caption(message[field])
                version = message.get('report_version')
                snapshot = a.get('report_versions', {}).get(version)
                if snapshot:
                    b1, b2 = st.columns(2)
                    if b1.button('查看报告 →', key=f'r_{number}'):
                        show_snapshot(snapshot, 'report', version)
                    if b2.button('查看证据 →', key=f'e_{number}'):
                        show_snapshot(snapshot, 'evidence', version)
        for command in store.pending(run_id):
            if command['kind'] == 'chat':
                st.info('待处理消息：' + command['content'])
        draft_key, widget_key = 'draft_' + run_id, 'draft_widget_' + run_id
        if widget_key not in st.session_state:
            st.session_state[widget_key] = st.session_state.get(draft_key, '')

        def remember_draft():
            st.session_state[draft_key] = st.session_state[widget_key]

        def send_draft():
            incoming = st.session_state.get(widget_key, '').strip()
            if incoming:
                service.submit(run_id, 'chat', incoming)
                st.session_state[draft_key] = ''
                st.session_state[widget_key] = ''

        with st.container(key='conversation_composer'):
            st.text_area('继续追问（切换页面后保留草稿）', key=widget_key, on_change=remember_draft,
                         placeholder='追问一条结论，或让 Agent 寻找反面证据…', height=90)
            hint, action = st.columns([4, 1])
            hint.caption('当前会话保留草稿 · 消息会加入后台处理队列')
            action.button('发送追问', key='send_' + run_id, type='primary', on_click=send_draft, use_container_width=True)

    with report:
        if state.report:
            title, download = st.columns([4, 1])
            with title:
                section_label('当前研究报告', '持续追问后可能更新')
            download.download_button('下载报告', '\n\n'.join(f'## {s.title}\n{s.content}' for s in state.report.sections),
                                     'research.md', use_container_width=True)
            for section in state.report.sections:
                st.subheader(section.title)
                st.markdown(section.content)
            st.caption('部分完成表示仍有证据缺口或模型降级；引用校验不代表投资判断正确。')
        else:
            empty_state('报告尚未生成', '资料核查与综合完成后，研究报告会显示在这里。')
        baseline = a.get('baseline')
        if baseline:
            with st.expander('与上次研究对照'):
                st.caption('上次研究时间：' + baseline['as_of'])
                st.write(baseline['summary'])
                st.write(update_brief(state))
                if baseline.get('snapshot') and st.button('查看基线报告版本', key='baseline_version'):
                    show_snapshot(baseline['snapshot'], 'report', baseline['version'])
                if st.button('打开上次研究', key='baseline_open'):
                    st.session_state.run_id = baseline['run_id']
                    st.rerun()

    with evidence:
        section_label('原始资料与引用', '优先核对来源，再判断结论')
        if state.sources:
            st.dataframe([{'来源': s.title, '公告/来源日期': s.published_date or '未知', '链接': s.url}
                          for s in state.sources], hide_index=True, use_container_width=True)
            # Only show excerpts from an actual saved report snapshot.
            snapshots = a.get('report_versions', {})
            latest = next(reversed(snapshots.values())) if snapshots else None
            if latest:
                render_cards(latest)
            else:
                for index, source in enumerate(state.sources):
                    with st.expander(source.title):
                        st.caption('公告/来源日期：' + (source.published_date or '未知'))
                        if urlsplit(source.url).scheme in {'http', 'https'}:
                            st.link_button('打开原始来源 ↗', source.url)
        else:
            empty_state('等待第一条来源', '研究开始检索后，可在这里核对资料出处与日期。')
        with st.expander('数据时点与口径'):
            if a.get('freshness'):
                st.json(a['freshness'])
            else:
                st.caption('尚无结构化数据时点，不能确认资料为最新。')
            st.caption('来源日期为采集元数据，可能不准确；财报期间不等于公告日期。')

    with reasoning:
        section_label('研究过程检查', '假设 · 反例 · 计划 · 执行')
        render_reasoning(state)
        with st.expander('研究计划与证据缺口'):
            if state.plan:
                for step in state.plan.steps:
                    st.write(step.title)
                    st.caption(step.description)
            else:
                st.caption('尚无研究计划。')
            for gap in a.get('evidence_gaps', []):
                st.caption(gap['task'] + '：' + gap['issue'])
        with st.expander('工具执行记录与用量'):
            render_trace(state)
            for item in a.get('events', []):
                st.write(f'**{item["tool"]}** · {item["reason"]}')
                st.caption(item['result'])
