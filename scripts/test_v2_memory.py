"""Research versions, actual hypothesis invalidation and configurable monitors."""
import copy
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.agent import create_agent
from src.models import ResearchReport, ReportSection, SynthesisBrief, GroundedFinding, ResearchPlan, ResearchPlanStep
from src.financial_ui import example_dataset
from src.financial_analysis import attach_financial_analysis, bind_financial_tasks
from src.evaluator import EvidenceEvaluator
from src.research_reasoning import update_hypotheses, build_evidence_graph
from src.research_memory import compare_snapshots, finalize_research_memory, diff_markdown, snapshot_changes
from src.report_links import snapshot_report
from src.stock_research import attach_research, stock_history
from src.storage import ResearchRunRepository
from src.workbench import Workbench
from src.background import Runner


def researched_state(supported=False):
    data = example_dataset()
    if supported:
        prior_values = {'03-31': 12, '06-30': 30, '09-30': 54, '12-31': 84}
        for row in data['financial_records']:
            if row['metric'] == 'attributable_net_profit' and row['period_end'].startswith('2025'):
                row['value'] = str(prior_values[row['period_end'][5:]])
    state = create_agent('研究002837')
    state.diagnostics['agent']['stock_symbol'] = '002837'
    state.plan = ResearchPlan(state.topic, state.depth, [ResearchPlanStep(1, '财务质量', '核对财务', ['002837 年报'])])
    attach_financial_analysis(state, data)
    bind_financial_tasks(state)
    state.evidence = EvidenceEvaluator().evaluate(state.documents, state.plan)
    update_hypotheses(state)
    evidence = {f'E{i+1}': e for i, e in enumerate(state.evidence)}
    state.synthesis = SynthesisBrief(state.topic, state.depth, evidence_index=evidence,
                                    key_findings=[GroundedFinding('关注业绩兑现' if supported else '关注利润与现金流风险', ['E1'])])
    state.report = ResearchReport(state.topic, state.depth, [ReportSection('结论', state.synthesis.key_findings[0].finding + ' [E1]')])
    build_evidence_graph(state)
    state.mark_completed()
    return state


class VersionMemoryTests(unittest.TestCase):
    def test_same_report_read_does_not_create_versions_from_time(self):
        state = researched_state()
        version = snapshot_report(state)
        state.updated_at = '2099-01-01T00:00:00Z'
        self.assertEqual(snapshot_report(state), version)
        self.assertEqual(len(state.diagnostics['agent']['report_versions']), 1)

    def test_versions_are_immutable_after_hypotheses_change(self):
        state = researched_state()
        first = snapshot_report(state)
        old = copy.deepcopy(state.diagnostics['agent']['report_versions'][first])
        state.diagnostics['hypotheses'][0]['questions'].append('新问题')
        second = snapshot_report(state)
        self.assertNotEqual(first, second)
        self.assertEqual(state.diagnostics['agent']['report_versions'][first], old)

    def test_snapshot_comparison_detects_real_hypothesis_invalidation_and_value_changes(self):
        before, after = researched_state(True), researched_state(False)
        first, second = snapshot_report(before), snapshot_report(after)
        diff = compare_snapshots(before.diagnostics['agent']['report_versions'][first], after.diagnostics['agent']['report_versions'][second])
        self.assertEqual(len(diff['invalidated_hypotheses']), 1)
        self.assertTrue(diff['changed_financial_values'])
        self.assertTrue(diff['changed_source_urls'])
        self.assertTrue(diff['new_conclusions'])
        self.assertIn('假设变化', diff_markdown(diff))

    def test_missing_financial_data_does_not_fake_a_value_revision(self):
        before = researched_state(True)
        version = snapshot_report(before)
        diff = compare_snapshots(before.diagnostics['agent']['report_versions'][version], {})
        self.assertEqual(diff['changed_financial_values'], [])
        self.assertEqual(diff['invalidated_hypotheses'], [])

    def test_same_url_content_changes_are_reported_without_claiming_new_announcement(self):
        old = {'evidence': {'E1': {'url': 'https://example.invalid/report', 'text': 'old'}}}
        new = {'evidence': {'E7': {'url': 'https://example.invalid/report', 'text': 'new'}}}
        diff = compare_snapshots(old, new)
        self.assertEqual(diff['new_source_urls'], [])
        self.assertEqual(diff['changed_source_urls'], ['https://example.invalid/report'])

    def test_same_company_update_carries_hypotheses_and_generates_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Workbench(Path(tmp) / 'workbench.db')
            repo = ResearchRunRepository(Path(tmp) / 'research.db')
            repo.initialize()
            prior = researched_state(True)
            repo.save_state(prior)
            current = researched_state(False)
            attach_research(current, store, repo, '002837', True)
            self.assertTrue(current.diagnostics['agent']['prior_hypotheses'])
            diff = finalize_research_memory(current)
            self.assertTrue(diff['invalidated_hypotheses'])
            self.assertEqual(repo.get_state(prior.run_id).diagnostics.get('agent', {}).get('report_versions'), None)
            self.assertEqual(len(stock_history(store, repo, '000001')), 0)

    def test_legacy_reports_without_agent_metadata_are_readable(self):
        state = researched_state()
        del state.diagnostics['agent']
        self.assertTrue(snapshot_report(state))

    def test_diff_page_runs_offline(self):
        from streamlit.testing.v1 import AppTest
        code = ('from scripts.test_v2_memory import researched_state\nfrom src.report_links import snapshot_report\n'
                'from src.research_memory import compare_snapshots\nfrom src.reasoning_ui import render_reasoning\n'
                'old,new=researched_state(True),researched_state(False)\na,b=snapshot_report(old),snapshot_report(new)\n'
                'new.diagnostics["research_diff"]=compare_snapshots(old.diagnostics["agent"]["report_versions"][a],new.diagnostics["agent"]["report_versions"][b])\nrender_reasoning(new)')
        app = AppTest.from_string(code).run(timeout=20)
        self.assertFalse(app.exception)
        self.assertTrue(any('研究版本差异' in m.value for m in app.markdown))


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Workbench(Path(self.tmp.name) / 'workbench.db')
        self.repo = ResearchRunRepository(Path(self.tmp.name) / 'research.db')
        self.repo.initialize()
        with patch('src.background.Workbench', return_value=self.store), patch('src.background.ResearchRunRepository', return_value=self.repo):
            self.runner = Runner()

    def tick_monitor(self, data=None, error=None):
        with patch('src.background.datetime') as clock, patch('src.stock_data.fetch_stock', return_value=data, side_effect=error) as fetch:
            clock.now.return_value = datetime(2026, 10, 12, 17)
            self.runner.monitor_once()
            return fetch.call_count

    def test_monitor_settings_are_bounded_and_do_not_enable_monitor(self):
        self.store.configure_monitor('002837', 3600, 'daily_and_financials')
        self.assertEqual(self.store.monitors(), [])
        with self.assertRaises(ValueError):
            self.store.configure_monitor('002837', 1, 'daily')
        with self.assertRaises(ValueError):
            self.store.configure_monitor('002837', 3600, 'unknown')

    def test_monitor_defaults_off_and_configured_interval_prevents_repeated_calls(self):
        self.store.set_monitor('002837', False)
        self.assertEqual(self.tick_monitor(), 0)
        self.store.set_monitor('002837', True)
        self.store.configure_monitor('002837', 3600, 'daily')
        data = {'daily': [{'日期': '2026-10-12', '收盘': 10}], 'provider': 'fixture'}
        self.assertEqual(self.tick_monitor(data), 1)
        self.assertEqual(self.tick_monitor(data), 0)
        self.assertEqual(self.store.monitor_events('002837')[0]['status'], 'success')

    def test_financial_update_detected_even_when_daily_date_is_unchanged(self):
        self.store.set_monitor('002837', True)
        old = {'daily': [{'日期': '2026-10-12', '收盘': 10}], 'finance': [{'value': 100}], 'provider': 'fixture'}
        new = dict(old, finance=[{'value': 120}])
        self.store.save_snapshot('002837', old)
        self.tick_monitor(new)
        self.assertIn('财务来源记录', self.store.alerts('002837')[0]['content'])
        self.assertTrue(self.store.monitor_events('002837')[0]['detail']['finance_changed'])

    def test_financial_source_unavailable_is_partial_not_a_false_change(self):
        self.store.set_monitor('002837', True)
        old = {'daily': [{'日期': '2026-10-12', '收盘': 10}], 'finance': [{'value': 100}]}
        self.store.save_snapshot('002837', old)
        self.tick_monitor(dict(old, finance=[]))
        event = self.store.monitor_events('002837')[0]
        self.assertEqual(event['status'], 'partial')
        self.assertFalse(event['detail']['finance_changed'])

    def test_failure_has_durable_record_and_preserves_old_snapshot(self):
        self.store.set_monitor('002837', True)
        self.store.save_snapshot('002837', {'daily': [{'日期': '2026-10-12', '收盘': 10}]})
        self.tick_monitor(error=ConnectionError('private connection details'))
        event = self.store.monitor_events('002837')[0]
        self.assertEqual(event['status'], 'failed')
        self.assertEqual(event['detail'], {'error_type': 'ConnectionError'})
        self.assertEqual(len(self.store.snapshots('002837')), 1)


if __name__ == '__main__':
    unittest.main()
