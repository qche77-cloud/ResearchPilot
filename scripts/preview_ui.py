"""Isolated UI preview: fictional data, temporary databases, no model/network tools.

Run via Streamlit. Intended only for screenshots and UI acceptance, not research.
"""
from pathlib import Path
import runpy
import tempfile
from unittest.mock import patch
import streamlit as st
from src.agent import create_agent
from src.background import Runner
from src.financial_ui import example_dataset
from src.models import ResearchReport, ReportSection, Source
from src.report_links import normalize_history
from src.storage import ResearchRunRepository
from src.workbench import Workbench


@st.cache_resource
def preview_service():
    tmp = tempfile.TemporaryDirectory(prefix='researchpilot-ui-')
    store = Workbench(Path(tmp.name) / 'workbench.db')
    repo = ResearchRunRepository(Path(tmp.name) / 'research.db')
    repo.initialize()
    store.save_directory([{'symbol': '002837', 'name': '界面演示公司（虚构）', 'exchange': 'SZ'}])
    dataset = example_dataset()
    # Keep synthetic provenance: pass the fixture directly to the renderer below,
    # never store it as a real financial input.
    store.save_snapshot('002837', dict(provider='离线合成演示 / 非真实行情', fetched_at='2026-10-12T00:00:00Z',
        adjustment='不复权 / 虚构数据', warnings=['此页面的财务与行情为合成测试数据，不能用于投资判断。'],
        daily=[{'日期': f'2026-09-{day:02d}', '收盘': 10 + day / 10, '开盘': 10 + day / 12,
                '最高': 11 + day / 10, '最低': 9 + day / 12, '成交量': 1000 + day * 100} for day in range(1, 26)],
        info=[{'item': '公司', 'value': '虚构界面演示'}], finance=[]))
    state = create_agent('离线界面演示：现金流如何检验增长质量？')
    state.sources = [Source('合成财报资料（虚构）', 'https://example.invalid/report', '离线演示来源', 'report', 1)]
    state.report = ResearchReport(state.topic, state.depth, [
        ReportSection(title='研究摘要', content='本页为离线界面演示。收入增长与利润变化需要分别核对，不能只凭单一指标判断经营质量。'),
        ReportSection(title='待验证问题', content='- 利润与经营现金流的变化是否一致？\n- 是否存在一次性收益或营运资金变化？\n- 哪些反面证据尚未进入结论？')])
    state.mark_completed()
    state.diagnostics['agent']['messages'] = [{'role': 'user', 'content': state.topic},
        {'role': 'assistant', 'content': '我会分别核对利润与现金流，并保留尚未验证的判断。此对话使用虚构数据展示界面。'}]
    normalize_history(state)
    repo.save_state(state)
    with patch('src.background.Workbench', return_value=store), patch('src.background.ResearchRunRepository', return_value=repo):
        service = Runner()
    service.start_monitors = lambda: None
    service.submit = lambda run_id, kind, content='': store.enqueue(run_id, kind, content)
    service._preview_tmp = tmp  # Keep the temporary directory alive with the resource.
    return service, dataset


service, dataset = preview_service()
def preview_financial_tools(store, symbol, snapshot=None):
    from src.financial_ui import render_analysis
    from src.financial_analysis import analyze_financials
    st.subheader('多期财务分析')
    st.warning('离线合成示例 / 非真实财务数据 / 不写入真实研究数据')
    render_analysis(analyze_financials(dataset), key='preview_fin_' + symbol)


with patch('src.background.Runner', return_value=service), \
     patch('src.workbench_ui.render_financial_tools', side_effect=preview_financial_tools), \
     patch('src.workbench_ui.fetch_stock', side_effect=RuntimeError('离线界面预览禁用网络')), \
     patch('src.workbench_ui.fetch_directory', side_effect=RuntimeError('离线界面预览禁用网络')):
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'agent_app.py'), run_name='__main__')
