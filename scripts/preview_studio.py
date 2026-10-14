"""Isolated Studio acceptance fixture; fictional sources, no paid/network commands."""
from copy import deepcopy
from pathlib import Path
import runpy
import tempfile
from unittest.mock import patch
import streamlit as st

from src.agent import create_agent
from src.background import Runner
from src.financial_screening_ui import demo_pool
from src.models import ResearchReport, ReportSection, Source
from src.storage import ResearchRunRepository
from src.workbench import Workbench


@st.cache_resource
def preview_service(cache_scope='default'):
    tmp = tempfile.TemporaryDirectory(prefix='researchpilot-studio-')
    repo = ResearchRunRepository(Path(tmp.name) / 'research.db')
    repo.initialize()
    store = Workbench(Path(tmp.name) / 'workbench.db')
    pool = demo_pool()
    for index, symbol in enumerate(pool):
        store.watch(symbol, '离线演示公司 ' + ('A' if index == 0 else 'B') + '（虚构）')
    # Synthetic inputs are readable in this isolated fixture only, never persisted
    # through the production financial-import path.
    store.financial_dataset = lambda symbol: {'payload': pool[symbol], 'created': '2026-04-01T00:00:00Z',
                                             'id': 'synthetic-fixture-' + symbol} if symbol in pool else None
    state = create_agent('离线演示公司 A：增长是否转化为现金流？', budget=6)
    state.mark_completed()
    a = state.diagnostics['agent']
    a['searches'] = 3
    excerpts = [
        ('合成年度财报 · 收入与利润', '2025 年营业收入同比增长，归母净利润同比下降。以上为虚构的界面测试资料。'),
        ('合成现金流附注 · 营运资金', '经营现金流低于同期净利润，营运资金占用增加。以上为虚构的界面测试资料。'),
        ('合成经营说明 · 待验证反例', '新业务收入占比提升，但费用率变化与回款周期尚未核实。以上为虚构的界面测试资料。')]
    evidence = {f'E{i+1}': dict(title=title, text=text, url=f'https://example.invalid/fictional/{i+1}',
        date='2026-03-30', date_source='synthetic_fixture', date_confidence='虚构演示', read_status='success')
        for i, (title, text) in enumerate(excerpts)}
    state.sources = [Source(e['title'], e['url'], e['text'], 'report', 1, published_date=e['date']) for e in evidence.values()]
    sections = [
        dict(title='核心判断', content='**收入增长尚不能直接证明经营质量改善。** 应同时核对利润与经营现金流，并保留反例。\n\n合成财报显示，收入与归母净利润的变化出现分化 [E1]。现金流附注提示，应进一步检查营运资金占用 [E2]。\n\n> 本报告及全部资料均为离线虚构演示，不能用于投资判断。'),
        dict(title='增长与兑现质量', content='从三个层面拆解增长：\n\n- **收入**：确认增长对应的业务与财报期间 [E1]。\n- **利润**：核查毛利率、费用率和一次性损益 [E1]。\n- **现金流**：核对回款周期与营运资金占用 [E2]。\n\n财务计算应使用确定性工具，缺失输入不能由模型补齐。'),
        dict(title='反面证据与不确定性', content='业务结构变化可能改变当前判断，但费用率与回款周期仍待验证 [E3]。\n\n现有证据支持的是“需要进一步核查”，尚不足以推出因果关系或投资建议。'),
        dict(title='接下来核查什么', content='1. 对照原始财报，统一币种、单位、期间与合并范围。\n2. 比较应收、存货与经营现金流的多期变化。\n3. 补查反面证据，并记录是否改变原假设。')]
    old = dict(sections=deepcopy(sections[:2]), evidence={k: deepcopy(evidence[k]) for k in ['E1', 'E2']},
        findings=[], as_of='2026-04-01T10:00:00Z', hypotheses=[])
    hypothesis = dict(id='H1', content='收入增长能够转化为持续的利润与现金流改善。',
        judgment='contradicted_by_data', uncertainty='高', criterion='同范围利润及经营现金流随收入增长',
        supporting=[], contrary=[dict(evidence_id='E1', text='收入增长而归母利润下降（虚构）')],
        questions=['费用率是否上升？', '营运资金占用能否解释现金流变化？'])
    current = dict(sections=sections, evidence=evidence,
        findings=[dict(text='需要进一步核查营运资金占用。', kind='inference', evidence_ids=['E2'],
                       excerpts=[dict(evidence_id='E2', text=excerpts[1][1])])],
        as_of='2026-04-02T10:00:00Z', hypotheses=[hypothesis])
    a['report_versions'] = {'demo-version-01': old, 'demo-version-02': current}
    a['messages'] = [
        dict(role='user', content='收入增长了，是否说明经营质量改善？'),
        dict(role='assistant', content='先分别核对收入、利润与现金流。第一版记录了增长与兑现之间的差异。', report_version='demo-version-01'),
        dict(role='user', content='如果要推翻这个判断，需要核查什么？'),
        dict(role='assistant', content='新资料提示业务结构可能变化 [E3]。我把反例与待验证的问题补进了报告，下一步需要核查费用率和回款周期。', report_version='demo-version-02')]
    state.report = ResearchReport(state.topic, state.depth, [ReportSection(**s) for s in sections])
    state.diagnostics['hypotheses'] = [hypothesis]
    repo.save_state(state)
    for title in ['离线演示：产业链需求变化的三个线索', '离线演示：新公告是否改变原投资假设']:
        other = create_agent(title)
        other.mark_completed()
        repo.save_state(other)
    with patch('src.background.Workbench', return_value=store), patch('src.background.ResearchRunRepository', return_value=repo):
        service = Runner()
    service._studio_preview = True
    service._preview_tmp = tmp
    service.submit = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('PREVIEW_COMMANDS_BLOCKED'))
    return service


if __name__ == '__main__':
    service = preview_service()
    with patch('src.workbench_ui.fetch_stock', side_effect=RuntimeError('离线预览禁止网络抓取')), \
         patch('src.workbench_ui.fetch_directory', side_effect=RuntimeError('离线预览禁止网络抓取')):
        runpy.run_path(str(Path(__file__).resolve().parents[1] / 'studio_app.py'), run_name='__main__',
                       init_globals={'_preview_service': service})
