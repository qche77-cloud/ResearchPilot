"""Explicit synthetic fixtures for a separate, loopback-only demonstration."""
from src.models import ResearchReport, ReportSection, Source, EvidenceDocument, EvaluatedEvidence, SynthesisBrief
from src.report_links import snapshot_report


def fill_report(state):
    text = '这是离线演示资料。收入增长需要与利润和现金流一起核查，不能仅由单一指标推出投资结论。'
    source = Source('虚构公司年度报告（演示夹具）', 'https://example.invalid/demo/annual-report', text,
                    'synthetic_fixture', 0, published_date='2026-04-30', date_source='synthetic_fixture', date_confidence='虚构演示')
    evidence = EvaluatedEvidence(EvidenceDocument(source, text, len(text), 'success'), 0, 0, 0, 0, '虚构演示，不是真实资料评价')
    state.sources = [source]
    state.synthesis = SynthesisBrief(state.topic, state.depth, evidence_index={'E1': evidence})
    state.report = ResearchReport(state.topic, state.depth, [
        ReportSection('结论与限制', '这是一份离线演示报告，全部公司、数字和资料均为虚构。\n\n收入增长需要与利润和现金流一起核查，不能仅由单一指标推出投资结论 [E1]。'),
        ReportSection('还需核查', '1. 对照原始财报，确认单位、期间和报表范围。\n2. 核查费用与营运资金变化。\n3. 保留可能推翻当前判断的反面证据。')])
    state.mark_completed()
    state.diagnostics['agent']['events'] = [dict(tool='离线演示', reason='用户明确选择了演示模式', result='未调用模型、搜索或行情服务')]
    snapshot_report(state)
    state.report.sections.append(ReportSection('反面证据与后续核查', '第二版增加了一个待验证问题：业务结构或回款节奏是否能解释差异？\n\n以上是虚构演示问题，尚未找到支持或反对它的真实资料。'))
    snapshot_report(state)


def seed(service, uid):
    worker = service.workspace(uid)
    if service.history(uid)['total']:
        return
    worker.store.watch('000001', '演示公司 A（虚构）')
    # Keep synthetic finance explicitly labelled; bypass the production import
    # rejection only inside the isolated demo workbench.
    from src.financial_ui import example_dataset
    import json
    payload = example_dataset('000001')
    with worker.store.connect() as db:
        db.execute('INSERT OR IGNORE INTO financial_inputs VALUES (?,?,?,?)',
                   ('demo-finance-v1', '000001', '2026-04-30T00:00:00Z', json.dumps(payload, ensure_ascii=False)))
    service.create(uid, '离线演示：收入增长是否改善经营质量？', 2, 'demo-initial-request', '000001')
