import tempfile
import unittest
from unittest.mock import patch
from datetime import date
from pathlib import Path
from src.workbench import Workbench
from src.storage import ResearchRunRepository
from src.agent import create_agent
from src.stock_research import (symbols_in, parse_date, date_status, freshness,
                                followup_scope, attach_research, stock_history, update_brief)
from src.models import ResearchReport, ReportSection, Source
from src.background import Runner


class StockResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Workbench(Path(self.tmp.name) / 'workbench.db')
        self.repo = ResearchRunRepository(Path(self.tmp.name) / 'research.db')
        self.repo.initialize()

    def test_dates(self):
        self.assertEqual(parse_date('20260630'), date(2026, 6, 30))
        self.assertIsNone(parse_date('未知'))
        self.assertIn('未知', date_status(None, 7))
        self.assertIn('晚于', date_status('2099-01-01', 7))
        self.assertIn('需更新', date_status('2026-09-01', 7, date(2026, 9, 20)))
        self.assertEqual(freshness({})['财报期间'], '未知')

    def test_profiles_isolated_and_theses_preserved(self):
        self.store.add_thesis('002837', '原假设', '催化', '证伪')
        self.store.save_profile('002837', '现金流', '证据', '反例', '问题')
        self.assertEqual(self.store.profile('000001')['focus'], '')
        self.assertEqual(self.store.theses('002837')[0]['thesis'], '原假设')
        again = Workbench(self.store.path)
        self.assertEqual(again.profile('002837')['focus'], '现金流')

    def test_scope_does_not_mix_stocks(self):
        state = create_agent('研究002837')
        self.assertIsNone(followup_scope(state, '现在怎么看', self.store))
        self.assertEqual(state.diagnostics['agent']['stock_symbol'], '002837')
        self.assertIn('新建', followup_scope(state, '000001怎么样', self.store))
        self.assertIn('多家', followup_scope(state, '002837和000001呢', self.store))
        self.assertEqual(symbols_in('英维克', [{'name': '英维克', 'symbol': '002837'}]), ['002837'])

    def test_legacy_history_and_baseline(self):
        prior = create_agent('研究002837现金流')
        prior.report = ResearchReport('旧报告', prior.depth, [ReportSection(title='结论', content='待核查')])
        prior.mark_completed()
        self.repo.save_state(prior)
        new = create_agent('更新002837')
        attach_research(new, self.store, self.repo, '002837', True)
        self.assertEqual(new.diagnostics['agent']['baseline']['run_id'], prior.run_id)
        self.assertEqual(len(stock_history(self.store, self.repo, '002837')), 1)
        self.assertEqual(stock_history(self.store, self.repo, '000001'), [])
        self.assertNotIn('report_versions', self.repo.get_state(prior.run_id).diagnostics['agent'])

    def test_no_new_and_failed_are_distinct(self):
        state = create_agent('更新002837')
        a = state.diagnostics['agent']
        a['update_mode'] = True
        a['baseline'] = {'as_of': '2026-09-01', 'urls': []}
        state.mark_completed()
        self.assertIn('不代表没有', update_brief(state))
        state.sources = [Source('未来公告', 'https://example.com', '', 'news', 1, published_date='2099-01-01')]
        self.assertIn('不代表没有', update_brief(state))
        state.mark_failed('network')
        self.assertIn('更新失败', update_brief(state))

    def test_link_is_idempotent_and_stock_cannot_be_reassigned(self):
        self.store.link_run('002837', 'run1')
        self.store.link_run('002837', 'run1')
        self.store.link_run('000001', 'run1')
        self.assertEqual(len(self.store.stock_runs('002837')), 1)
        self.assertEqual(self.store.stock_runs('000001'), [])

    def test_background_blocks_cross_stock_before_model(self):
        with patch('src.background.ResearchRunRepository', return_value=self.repo), patch('src.background.Workbench', return_value=self.store):
            runner = Runner()
        state = create_agent('研究002837')
        self.repo.save_state(state)
        self.store.enqueue(state.run_id, 'chat', '000001现在怎么样')
        with patch('src.background.respond') as model:
            runner._run(state.run_id)
            model.assert_not_called()
        saved = self.repo.get_state(state.run_id)
        self.assertIn('新建', saved.diagnostics['agent']['messages'][-1]['content'])
        self.assertEqual(self.store.pending(state.run_id), [])

    def test_update_button_wires_symbol_without_network(self):
        from streamlit.testing.v1 import AppTest
        source = ('import streamlit as st\nfrom src.workbench import Workbench\n'
                  'from src.storage import ResearchRunRepository\nfrom src.workbench_ui import render_workbench\n'
                  f'store=Workbench({str(self.store.path)!r})\nrepo=ResearchRunRepository({str(self.repo.db_path)!r})\n'
                  'repo.initialize()\ndef start(topic, **kwargs):\n    st.session_state.request=kwargs\n'
                  'render_workbench(store,start,repo=repo)')
        app = AppTest.from_string(source).run(timeout=20)
        self.assertFalse(app.exception)
        app.button(key='refresh_research_002837').click().run(timeout=20)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state.request, {'symbol': '002837', 'update': True})


if __name__ == '__main__':
    unittest.main()
