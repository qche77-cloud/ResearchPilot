"""Offline UI regressions for navigation, drafts, commands and saved report views."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import streamlit as st
from streamlit.testing.v1 import AppTest
from src.agent import create_agent
from src.background import Runner
from src.models import ResearchReport, ReportSection
from src.report_links import normalize_history
from src.storage import ResearchRunRepository
from src.workbench import Workbench


class WorkspaceUITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Workbench(Path(self.tmp.name) / 'workbench.db')
        self.repo = ResearchRunRepository(Path(self.tmp.name) / 'research.db')
        self.repo.initialize()
        with patch('src.background.Workbench', return_value=self.store), patch('src.background.ResearchRunRepository', return_value=self.repo):
            self.runner = Runner()
        st.cache_resource.clear()
        self.addCleanup(st.cache_resource.clear)
        for target, kwargs in [('src.background.Runner', {'return_value': self.runner})]:
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ('start_monitors', 'submit'):
            patcher = patch.object(self.runner, name)
            mock = patcher.start()
            setattr(self, name, mock)
            self.addCleanup(patcher.stop)

    def app(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'agent_app.py')).run(timeout=20)
        self.assertFalse(app.exception)
        return app

    def click(self, app, label):
        next(b for b in app.button if b.label == label).click().run(timeout=20)
        self.assertFalse(app.exception)

    def open_run(self):
        state = create_agent('离线界面测试：现金流研究')
        state.report = ResearchReport(state.topic, state.depth, [ReportSection(title='测试报告', content='离线合成内容，不代表真实公司判断。')])
        state.diagnostics['agent']['messages'] = [{'role': 'user', 'content': state.topic}]
        normalize_history(state)
        self.repo.save_state(state)
        app = self.app()
        app.button(key=state.run_id).click().run(timeout=20)
        self.assertFalse(app.exception)
        return app, state

    def test_home_draft_survives_stock_navigation(self):
        app = self.app()
        app.text_area(key='home_editor').input('研究现金流的草稿').run()
        self.click(app, '个股与自选')
        self.assertIn('财务分析', [tab.label for tab in app.tabs])
        self.click(app, '研究对话')
        self.assertEqual(app.text_area(key='home_editor').value, '研究现金流的草稿')
        self.submit.assert_not_called()

    def test_starter_fills_draft_without_starting_paid_research(self):
        app = self.app()
        app.button(key='starter_03').click().run()
        self.assertIn('推翻', app.text_area(key='home_editor').value)
        self.assertEqual(self.repo.list_runs(), [])
        self.submit.assert_not_called()

    def test_saved_report_is_accessible_in_separate_views(self):
        app, state = self.open_run()
        self.assertEqual([tab.label for tab in app.tabs], ['研究对话', '研究报告', '证据与来源', '假设与验证'])
        self.assertTrue(any('离线合成内容' in m.value for m in app.markdown))
        self.assertEqual(self.repo.get_state(state.run_id).report.sections[0].title, '测试报告')

    def test_followup_draft_survives_navigation_and_enqueues_once(self):
        app, state = self.open_run()
        key = 'draft_widget_' + state.run_id
        app.text_area(key=key).input('请找出反面证据').run()
        self.click(app, '个股与自选')
        self.click(app, '研究对话')
        self.assertEqual(app.text_area(key=key).value, '请找出反面证据')
        app.button(key='send_' + state.run_id).click().run()
        self.assertFalse(app.exception)
        self.submit.assert_called_once_with(state.run_id, 'chat', '请找出反面证据')
        self.assertEqual(app.text_area(key=key).value, '')

    def test_controls_use_existing_runner_commands(self):
        app, state = self.open_run()
        app.button(key='resume').click().run()
        self.submit.assert_called_once_with(state.run_id, 'resume')
        self.submit.reset_mock()
        app.button(key='more').click().run()
        self.submit.assert_called_once_with(state.run_id, 'budget')


if __name__ == '__main__':
    unittest.main()
