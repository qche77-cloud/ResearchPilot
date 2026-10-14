"""Offline contracts for the custom frontend: provenance, no paid reads, intents."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from src.agent import create_agent
from src.models import ResearchReport, ReportSection, Source
from src.storage import ResearchRunRepository
from src.workbench import Workbench
from src.studio_bridge import consume_event, packet, run_view, start_run


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = ResearchRunRepository(Path(self.tmp.name) / 'research.db')
        self.repo.initialize()
        self.store = Workbench(Path(self.tmp.name) / 'workbench.db')
        self.service = Mock(repo=self.repo, store=self.store, _studio_preview=False)
        self.service.active.return_value = False
        self.state = create_agent('离线研究界面契约')
        self.repo.save_state(self.state)
        self.session = {'studio_run': self.state.run_id}

    def send(self, action, **args):
        event = dict(id='event-' + str(len(self.session.get('studio_events', []))), action=action, **args)
        consume_event(event, self.service, self.session)
        return event

    def test_render_never_starts_worker_or_mutates_legacy_history(self):
        self.state.report = ResearchReport(self.state.topic, self.state.depth, [ReportSection('旧报告', '没有引用快照')])
        self.repo.save_state(self.state)
        before = self.repo.get_run(self.state.run_id)
        view = packet(self.service, self.session)
        self.assertEqual(view['run']['versions']['legacy']['cards'], [])
        self.assertEqual(before, self.repo.get_run(self.state.run_id))
        self.service.submit.assert_not_called()
        self.service.start_monitors.assert_not_called()

    def test_old_version_keeps_its_own_evidence_and_excerpts(self):
        a = self.state.diagnostics['agent']
        a['report_versions'] = {
            'old': dict(sections=[dict(title='旧版本', content='旧结论 [E1]')], evidence={'E1': dict(title='旧来源', text='旧原文')}, findings=[]),
            'new': dict(sections=[dict(title='新版本', content='新结论 [E2]')], evidence={'E2': dict(title='新来源', text='新原文')}, findings=[])}
        original = deepcopy(a)
        result = run_view(self.state)
        self.assertEqual(result['versions']['old']['cards'][0]['excerpts'], ['旧原文'])
        self.assertEqual(result['versions']['new']['cards'][0]['eid'], 'E2')
        self.assertEqual(a, original)

    def test_uncited_sources_are_not_assigned_evidence_numbers(self):
        self.state.sources = [Source('采集来源', 'https://example.invalid', 'text', 'web', 1)]
        self.assertEqual(run_view(self.state)['versions'], {})
        self.assertNotIn('eid', run_view(self.state)['sources'][0])

    def test_sensitive_nested_keys_are_redacted(self):
        self.state.diagnostics['hypotheses'] = [{'content': '假设', 'api_key': 'must-not-leak'}]
        self.assertNotIn('must-not-leak', str(run_view(self.state)))

    def test_replayed_command_is_consumed_once_even_after_other_events(self):
        event = self.send('chat', run_id=self.state.run_id, content='核查反例')
        self.send('navigate', view='watchlist')
        self.assertFalse(consume_event(event, self.service, self.session))
        self.service.submit.assert_called_once_with(self.state.run_id, 'chat', '核查反例')

    def test_stale_task_event_cannot_steer_selected_task(self):
        self.send('chat', run_id='different-task', content='核查反例')
        self.service.submit.assert_not_called()
        self.assertIn('任务已切换', self.session['studio_notice'])

    def test_commands_use_existing_runner(self):
        for command in ['pause', 'resume', 'budget']:
            self.send(command, run_id=self.state.run_id)
        self.assertEqual([c.args for c in self.service.submit.call_args_list], [
            (self.state.run_id, 'pause', ''), (self.state.run_id, 'resume', ''), (self.state.run_id, 'budget', '')])

    def test_invalid_text_budget_and_actions_do_not_start_paid_work(self):
        for args in [dict(topic=''), dict(topic='x', budget=99), dict(topic='x', budget=True)]:
            self.send('start', **args)
        self.send('chat', run_id=self.state.run_id, content=' ')
        self.send('execute_python', content='arbitrary code')
        self.service.submit.assert_not_called()
        self.assertEqual(self.repo.count_runs(), 1)

    def test_explicit_start_saves_state_and_submits_resume(self):
        self.send('start', topic='新增离线研究', budget=4)
        new = self.repo.get_state(self.session['studio_run'])
        self.assertEqual(new.topic, '新增离线研究')
        self.assertEqual(new.diagnostics['agent']['budget'], 4)
        self.service.submit.assert_called_once_with(new.run_id, 'resume')

    def test_preview_rejects_commands_but_allows_navigation(self):
        self.service._studio_preview = True
        self.send('start', topic='不可启动')
        self.send('chat', run_id=self.state.run_id, content='不可追问')
        self.send('navigate', view='screening')
        self.assertEqual(self.session['studio_view'], 'screening')
        self.service.submit.assert_not_called()
        self.assertEqual(self.repo.count_runs(), 1)
        with self.assertRaisesRegex(ValueError, '离线预览'):
            start_run(self.service, self.session, '旧工作台入口也必须被阻止')
        self.assertEqual(self.repo.count_runs(), 1)

    def test_screening_missing_inputs_not_fabricated(self):
        self.store.watch('002837', '离线演示')
        self.send('screen', as_of='2026-04-01', minimums={'revenue_yoy': 0})
        result = packet(self.service, self.session)['screening']
        self.assertEqual(result['stock_count'], 0)
        self.assertEqual(result['missing_symbols'], ['002837'])
        self.service.submit.assert_not_called()

    def test_invalid_screen_criteria_do_not_replace_previous_criteria(self):
        self.send('screen', as_of='2026-04-01', minimums={})
        before = deepcopy(self.session['studio_criteria'])
        self.send('screen', as_of='2026-99-99', minimums={})
        self.send('screen', as_of='2026-04-01', minimums={'unknown': 3})
        self.send('screen', as_of='2026-04-01', minimums=['revenue_yoy'])
        self.send('screen', as_of='2026-04-01', basis='invented_basis')
        self.send('screen', as_of='2026-04-01', currency='BTC')
        self.assertEqual(self.session['studio_criteria'], before)

    def test_malformed_open_event_is_rejected_without_sql_error(self):
        self.send('open', run_id={'unexpected': 'object'})
        self.assertIn('无效研究标识', self.session['studio_notice'])
        self.assertEqual(self.session['studio_run'], self.state.run_id)

    def test_studio_entry_renders_with_existing_repository(self):
        from streamlit.testing.v1 import AppTest
        import streamlit as st
        st.cache_resource.clear()
        self.addCleanup(st.cache_resource.clear)
        with patch('src.background.Runner', return_value=self.service):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'studio_app.py')).run(timeout=20)
        self.assertFalse(app.exception)
        self.service.submit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
