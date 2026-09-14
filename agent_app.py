"""Conversational A-share research workspace with background execution."""
from urllib.parse import urlsplit
import streamlit as st
from src.agent import create_agent
from src.background import Runner
from src.env import load_env
from src.report_links import normalize_history
from src.workbench_ui import render_workbench
from src.ui_theme import apply_theme, page_intro, status_strip, page_motion, welcome, starter_card

load_env()
st.set_page_config(page_title='ResearchPilot · 投研工作台', page_icon='◈', layout='wide')
apply_theme()


@st.cache_resource
def runner():
    service = Runner()
    service.start_monitors()
    return service


service = runner()
repo, store = service.repo, service.store


def start_research(topic):
    state = create_agent(topic, st.session_state.get('budget', 2))
    state.diagnostics['agent']['preferences'] = store.preferences()
    state.diagnostics['agent']['messages'] = [
        {'role': 'user', 'content': topic},
        {'role': 'assistant', 'content': '我会核查原始资料，区分已兑现的事实与仍需验证的判断。研究在后台运行，可以继续发消息。'}]
    repo.save_state(state)
    st.session_state.run_id = state.run_id
    st.session_state.page = '研究对话'
    service.submit(state.run_id, 'resume')
    st.rerun()


@st.dialog('研究详情', width='large')
def show_snapshot(snapshot, kind, version):
    st.caption('消息对应版本：' + version[:8])
    if kind == 'report':
        for section in snapshot['sections']:
            st.subheader(section['title'])
            st.markdown(section['content'])
    else:
        for eid, item in snapshot['evidence'].items():
            with st.expander(f'[{eid}] {item["title"]}'):
                st.caption('日期：' + str(item['date'] or '未知'))
                if urlsplit(item['url']).scheme in {'http', 'https'}:
                    st.link_button('原始来源 ↗', item['url'])
                st.text(item['text'])


with st.sidebar:
    st.markdown('<div class="rp-brand"><span>◈</span>ResearchPilot</div>', unsafe_allow_html=True)
    st.caption('把投资问题，变成有据可查的判断。')
    st.divider()
    page = st.session_state.get('page', '研究对话')
    if st.button('研究对话', use_container_width=True, type='primary' if page == '研究对话' else 'secondary'):
        st.session_state.page = '研究对话'
        st.rerun()
    if st.button('个股与自选', use_container_width=True, type='primary' if page == '个股与自选' else 'secondary'):
        st.session_state.page = '个股与自选'
        st.rerun()
    if st.button('＋ 新对话', use_container_width=True):
        st.session_state.pop('run_id', None)
        st.session_state.pop('research_draft', None)
        st.session_state.page = '研究对话'
        st.rerun()
    with st.expander('研究设置'):
        st.slider('新研究搜索预算', 2, 16, 2, key='budget')
        st.caption('默认 2 次；失败请求不占用成功搜索预算。')
        st.caption('关闭浏览器不影响后台任务；重启本地服务后需手动恢复。')
    st.divider()
    st.caption('最近研究 / HISTORY')
    for row in repo.list_runs(limit=20):
        if st.button(row.topic[:30], key=row.run_id, help=row.topic, use_container_width=True):
            st.session_state.run_id = row.run_id
            st.session_state.page = '研究对话'
            st.rerun()

page_motion((st.session_state.get('page', '研究对话'), st.session_state.get('run_id')))
if st.session_state.get('page') == '个股与自选':
    render_workbench(store, start_research)
    st.stop()

run_id = st.session_state.get('run_id')
if run_id:
    page_intro('研究对话', '持续追问 · 核查来源 · 修正判断')
if not run_id:
    welcome()
    suggestions = ['研究一家公司的现金流质量', '核查近期公告中的风险', '寻找推翻投资假设的证据']
    cards = [('01', '读懂一家公司', '从利润到现金流，核查业绩是否真正兑现。'), ('02', '追踪关键变化', '聚焦公告与新信息，分清事实和市场预期。'), ('03', '挑战投资判断', '寻找反例，检验你的假设还能否成立。')]
    for column, suggestion, card in zip(st.columns(3), suggestions, cards):
        with column:
            starter_card(*card)
            if st.button('从这里开始 ↗', key='starter_' + card[0], help=suggestion, use_container_width=True):
                st.session_state.research_draft = suggestion
    st.markdown('<div class="rp-footnote">A 股盘后研究 · 来源可追溯 · 记录保存在本地</div>', unsafe_allow_html=True)
    if st.session_state.get('research_draft'):
        with st.form('research_starter'):
            draft = st.text_area('补充股票名称、代码和关注的问题', st.session_state.research_draft)
            if st.form_submit_button('开始研究', type='primary') and draft.strip():
                start_research(draft.strip())
    with st.container():
        topic = st.chat_input('输入公司名称或代码，开始你的研究…')
    if topic:
        start_research(topic)
    st.stop()


@st.fragment(run_every='4s')
def conversation(run_id):
    state, active = service.read(run_id)
    if not state:
        st.error('未找到研究记录。')
        return
    a = state.diagnostics.get('agent', {})
    outcome = a.get('outcome')
    label = '后台执行中' if active else ('执行失败' if state.status == 'failed' else
        ('部分完成' if outcome == 'partial' else ('已完成' if state.status == 'completed' else '已暂停 / 待恢复')))
    status_strip(f'{label} · 搜索 {a.get("searches", 0)}/{a.get("budget", 2)} · 来源 {len(state.sources)}')
    with st.expander('研究控制与执行详情', expanded=False):
        if active:
            if st.button('暂停（当前工具结束后生效）', key='pause'):
                service.submit(run_id, 'pause')
                st.info('暂停请求已入队。')
        elif state.status != 'completed':
            if st.button('恢复研究', key='resume'):
                service.submit(run_id, 'resume')
        if st.button('增加 3 次搜索预算', key='more'):
            service.submit(run_id, 'budget')
        with st.expander('研究计划与证据缺口'):
            if state.plan:
                for step in state.plan.steps:
                    st.write(step.title)
                    st.caption(step.description)
            for gap in a.get('evidence_gaps', []):
                st.caption(gap['task'] + '：' + gap['issue'])
        with st.expander('工具执行记录'):
            for item in a.get('events', []):
                st.write(f'**{item["tool"]}** · {item["reason"]}')
                st.caption(item['result'])
        if state.report:
            st.download_button('下载当前报告', '\n\n'.join(f'## {s.title}\n{s.content}' for s in state.report.sections), 'research.md')
        st.caption('部分完成表示仍有证据缺口或模型降级；引用校验不代表投资判断正确。')
    with st.container():
        for number, message in enumerate(a.get('messages', [])):
            with st.chat_message(message['role']):
                st.markdown(message.get('display_summary', message['content']))
                if message.get('original_content'):
                    with st.expander('原回答'):
                        st.markdown(message['original_content'])
                if message.get('provenance_note'):
                    st.caption(message['provenance_note'])
                if message.get('citation_check'):
                    st.caption(message['citation_check'])
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
        if state.error:
            st.error(state.error)
    incoming = st.chat_input('继续追问、补充要求或核查新的资料…', key='followup')
    if incoming:
        service.submit(run_id, 'chat', incoming)
        st.rerun(scope='fragment')


conversation(run_id)
