"""Conversational A-share research workspace with background execution."""
import streamlit as st
from src.agent import create_agent
from src.background import Runner
from src.env import load_env
from src.workbench_ui import render_workbench
from src.ui_theme import (apply_theme, page_intro, status_strip, page_motion, welcome,
                          starter_card, brand, workspace_bar, section_label)
from src.stock_research import attach_research, symbols_in
from src.evidence_cards import render_cards

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


def start_research(topic, symbol=None, update=False):
    candidates = symbols_in(topic, store.directory())
    symbol = symbol or (candidates[0] if len(candidates) == 1 else None)
    if symbol and symbol not in topic:
        topic = f'{symbol} · {topic}'
    state = create_agent(topic, st.session_state.get('budget', 2))
    if symbol:
        attach_research(state, store, repo, symbol, update)
    state.diagnostics['agent']['preferences'] = store.preferences()
    state.diagnostics['agent']['messages'] = [
        {'role': 'user', 'content': topic},
        {'role': 'assistant', 'content': '我会核查原始资料，区分已兑现的事实与仍需验证的判断。研究在后台运行，可以继续发消息。'}]
    repo.save_state(state)
    if symbol:
        store.link_run(symbol, state.run_id)
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
        render_cards(snapshot)


with st.sidebar:
    brand()
    st.caption('工作空间 / WORKSPACE')
    page = st.session_state.get('page', '研究对话')
    if st.button('研究对话', use_container_width=True, type='primary' if page == '研究对话' else 'secondary'):
        st.session_state.page = '研究对话'
        st.rerun()
    if st.button('个股与自选', use_container_width=True, type='primary' if page == '个股与自选' else 'secondary'):
        st.session_state.page = '个股与自选'
        st.rerun()
    if st.button('＋ 新对话', key='new_research', use_container_width=True):
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
    history_query = st.text_input('搜索研究历史', placeholder='公司名称、代码或主题')
    recent_runs = repo.list_runs(limit=50, topic_query=history_query or None)
    for row in recent_runs:
        if st.button(row.topic[:30], key=row.run_id, help=row.topic, use_container_width=True):
            st.session_state.run_id = row.run_id
            st.session_state.page = '研究对话'
            st.rerun()
    if not recent_runs:
        st.caption('没有匹配记录' if history_query else '第一份研究，从一个问题开始。')
    st.markdown('<div class="rp-sidebar-foot">本地保存 · 可追溯研究<br>ResearchPilot / Research Desk</div>', unsafe_allow_html=True)

page_motion((st.session_state.get('page', '研究对话'), st.session_state.get('run_id')))
workspace_bar(st.session_state.get('page', '研究对话'))
if st.session_state.get('page') == '个股与自选':
    render_workbench(store, start_research, repo=repo)
    st.stop()

run_id = st.session_state.get('run_id')
if not run_id:
    welcome()
    section_label('选择一个研究方向', '从业绩、变化或反例入手')
    suggestions = ['研究一家公司的现金流质量', '核查近期公告中的风险', '寻找推翻投资假设的证据']
    cards = [('01', '读懂一家公司', '从利润到现金流，核查业绩是否真正兑现。'), ('02', '追踪关键变化', '聚焦公告与新信息，分清事实和市场预期。'), ('03', '挑战投资判断', '寻找反例，检验你的假设还能否成立。')]
    for column, suggestion, card in zip(st.columns(3), suggestions, cards):
        with column:
            starter_card(*card)
            if st.button('从这里开始 ↗', key='starter_' + card[0], help=suggestion, use_container_width=True):
                st.session_state.research_draft = suggestion
                st.session_state.home_editor = suggestion
    if 'home_editor' not in st.session_state:
        st.session_state.home_editor = st.session_state.get('research_draft', '')
    def save_home_draft():
        st.session_state.research_draft = st.session_state.home_editor
    with st.container(key='home_composer'):
        section_label('你想研究什么？', '公司 · 行业 · 投资假设')
        topic = st.text_area('输入公司名称、代码和关注的问题', key='home_editor', on_change=save_home_draft,
                             placeholder='例如：研究 002837 的利润与现金流，哪些证据可能推翻增长判断？',
                             label_visibility='collapsed', height=100)
        note, action = st.columns([4, 1])
        with note:
            st.markdown(f'<div class="rp-composer-note">本次搜索预算 {st.session_state.get("budget", 2)} 次 · 草稿在当前会话切页时保留</div>', unsafe_allow_html=True)
        with action:
            if st.button('开始研究', type='primary', use_container_width=True) and topic.strip():
                st.session_state.research_draft = ''
                start_research(topic.strip())
    st.caption('研究记录保存在本地。关闭或刷新浏览器不保证草稿保留。')
    st.stop()


@st.fragment(run_every='4s')
def conversation(run_id):
    state, active = service.read(run_id)
    if not state:
        st.error('未找到研究记录。')
        return
    from src.conversation_ui import render_conversation
    render_conversation(state, active, service, store, start_research, show_snapshot)



conversation(run_id)
