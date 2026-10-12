"""Reproducible synthetic capability demo; no API, trading or production database."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.agent import create_agent
from src.financial_analysis import attach_financial_analysis, bind_financial_tasks, financial_evidence
from src.financial_ui import example_dataset
from src.models import ResearchPlan, ResearchPlanStep, SynthesisBrief, GroundedFinding, ResearchReport, ReportSection, SupportingExcerpt
from src.evaluator import EvidenceEvaluator
from src.research_reasoning import update_hypotheses, reflect_plan, build_evidence_graph, critic_review
from src.report_links import snapshot_report
from src.research_memory import finalize_research_memory, diff_markdown


def demo_state(supported):
    dataset = example_dataset()
    if supported:
        dataset['fetched_at'] = '2026-09-01T00:00:00Z'
        for row in dataset['financial_records']:
            if row['metric'] == 'attributable_net_profit' and row['period_end'].startswith('2025'):
                row['value'] = str({'03-31': 12, '06-30': 30, '09-30': 54, '12-31': 84}[row['period_end'][5:]])
    else:
        for metric, value in [('revenue', 150), ('attributable_net_profit', 5), ('operating_cash_flow', 4), ('cost_of_revenue', 105)]:
            dataset['financial_records'].append(dict(dataset['financial_records'][0], metric=metric, value=str(value), period_end='2026-03-31', published_at='2026-04-30'))
    state = create_agent('合成演示：002837 营收、利润与现金流；并非真实公司数据')
    state.diagnostics['agent']['stock_symbol'] = dataset['symbol']
    state.plan = ResearchPlan(state.topic, state.depth, [ResearchPlanStep(1, '财务质量', '统一期间与口径核查财务', ['合成财务演示'])])
    attach_financial_analysis(state, dataset)
    bind_financial_tasks(state)
    state.evidence = EvidenceEvaluator().evaluate(state.documents, state.plan)
    update_hypotheses(state)
    reflect_plan(state)
    index = {f'E{i+1}': e for i, e in enumerate(state.evidence)}
    h = next(h for h in state.diagnostics['hypotheses'] if h.get('rule') == 'revenue_profit_alignment')
    finding = '合成示例：营收和利润数据方向一致。' if supported else '合成示例：营收与利润出现方向背离，已追加毛利率、费用率与业务结构核查。'
    quotes = [SupportingExcerpt(eid, e.document.extracted_text[:200], e.source.title, e.source.url) for eid, e in index.items()]
    state.synthesis = SynthesisBrief(state.topic, state.depth, evidence_index=index,
                                    key_findings=[GroundedFinding(finding, list(index), supporting_excerpts=quotes)],
                                    synthesizer_source='deterministic_fixture')
    state.report = ResearchReport(state.topic, state.depth, [
        ReportSection('合成演示说明', '全部数值为虚构示例；报告由程序生成，未调用 LLM，不代表真实个股研究。'),
        ReportSection('核心结论', finding + ' ' + ' '.join('[' + eid + ']' for eid in index)),
        ReportSection('假设状态', h['judgment']),
    ], writer_source='fallback')
    build_evidence_graph(state)
    critic_review(state)
    state.mark_completed()
    state.diagnostics['agent']['report_as_of'] = dataset['fetched_at']
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='artifacts/v2-demo')
    args = parser.parse_args(argv)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    prior, current = demo_state(True), demo_state(False)
    version = snapshot_report(prior)
    current.diagnostics['agent']['baseline'] = {'version': version, 'snapshot': prior.diagnostics['agent']['report_versions'][version]}
    diff = finalize_research_memory(current)
    data = {'provenance': 'synthetic_fixture', 'financial_evidence': financial_evidence(current.diagnostics['financial_analysis']),
            'hypotheses': current.diagnostics['hypotheses'], 'plan_changes': current.diagnostics['agent']['automatic_revisions'],
            'evidence_graph': current.diagnostics['evidence_graph'], 'critic': current.diagnostics['critic'], 'diff': diff}
    (output / 'capabilities.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'research-diff.md').write_text('> 全部为离线合成数据，不代表真实公司研究。\n\n' + diff_markdown(diff), encoding='utf-8')
    print(f'Synthetic demo: {len(diff["invalidated_hypotheses"])} invalidated hypothesis, {len(diff["new_financial_records"])} new financial records; {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
