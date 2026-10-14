"""ResearchPilot Studio: a component-based workspace over the existing engine.

Run: python -m streamlit run studio_app.py --server.address 127.0.0.1
The legacy agent_app.py remains available. No automatic monitor is started here.
"""
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components
from src.background import Runner
from src.env import load_env
from src.studio_bridge import packet, consume_event, start_run

load_env()
st.set_page_config(page_title='ResearchPilot Studio', page_icon='◈', layout='wide', initial_sidebar_state='collapsed')
st.markdown('''<style>
[data-testid="stHeader"], [data-testid="stSidebar"], [data-testid="stAppDeployButton"] {display:none}
.block-container {padding:0!important; max-width:none!important}
[data-testid="stMainBlockContainer"] {padding:0!important}
[data-testid="stVerticalBlock"] {gap:0!important}
[data-testid="stElementContainer"]:has(iframe) {line-height:0}
iframe[title="studio_app.researchpilot_studio"] {border:0;display:block}
body,[data-testid="stAppViewContainer"] {background:#f6f7f9}
</style>''', unsafe_allow_html=True)


@st.cache_resource
def studio_service():
    # Do not silently duplicate the legacy service's monitor scheduler.
    return Runner()


# The isolated preview passes a service via runpy; it must not reuse a cached
# production factory or an obsolete preview fixture after source edits.
service = globals().get('_preview_service')
if service is None:
    service = studio_service()
studio = components.declare_component('researchpilot_studio', path=str(Path(__file__).parent / 'src' / 'studio_component'))


def start_research(topic, symbol=None, update=False):
    if getattr(service, '_studio_preview', False):
        st.warning('离线预览不启动研究。请在正式 Studio 中使用此操作。')
        return
    start_run(service, st.session_state, topic, st.session_state.get('budget', 2), symbol, update)
    st.session_state['studio_view'] = 'research'
    st.rerun()


if st.session_state.get('studio_view') == 'workbench':
    from src.ui_theme import apply_theme
    from src.workbench_ui import render_workbench
    apply_theme()
    with st.container():
        st.markdown('<style>.block-container{padding:1.5rem 2rem!important}</style>', unsafe_allow_html=True)
        if st.button('← 返回 Studio', key='studio_return'):
            st.session_state['studio_view'] = 'research'
            st.rerun()
        st.caption('完整数据工具 · 财务导入、行情、自选、监控配置与投资复盘')
        if getattr(service, '_studio_preview', False):
            st.warning('隔离的离线预览 · 所有公司与数据均为虚构，不保存到真实研究数据库。')
        st.info('Studio 不自动启动监控调度器；监控执行由已有的 agent_app 服务负责。')
        render_workbench(service.store, start_research, repo=service.repo)
else:
    @st.fragment(run_every='4s')
    def workspace():
        event = studio(data=packet(service, st.session_state), key='researchpilot_studio', default=None)
        if consume_event(event, service, st.session_state):
            st.rerun()
    workspace()
