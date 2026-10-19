"""Offline acceptance tests for data, memory, references and background jobs."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from src.workbench import Workbench
from src.storage import ResearchRunRepository
from src.background import Runner
from src.agent import create_agent, tick
from src.agent_chat import validate_citations
from src.report_links import normalize_history
from src.stock_data import normalize_symbol, changes
from src.models import ResearchReport, ReportSection, SynthesisBrief, GroundedFinding, ResearchPlan


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Workbench(Path(self.tmp.name) / 'workbench.db')
        self.repo = ResearchRunRepository(Path(self.tmp.name) / 'runs.db')
        self.repo.initialize()

    def test_preferences_watch_and_review(self):
        self.store.save_preferences('优先公告')
        self.assertEqual(self.store.preferences(), '优先公告')
        self.store.watch('002837', '英维克')
        self.store.add_thesis('002837', '订单兑现', '财报', '现金流恶化')
        item = self.store.theses('002837')[0]
        self.store.review(item['id'], '等待验证', '观察中')
        self.assertEqual(self.store.theses('002837')[0]['review'], '等待验证')
        self.store.unwatch('002837')
        self.assertEqual(self.store.watches(), [])
        self.store.save_preferences('')
        self.assertEqual(self.store.preferences(), '')

    def test_snapshot_change_and_identity(self):
        self.assertEqual(normalize_symbol('002837'), ('002837', 'SZ'))
        with self.assertRaises(ValueError):
            normalize_symbol('not-a-stock')
        old = {'daily': [{'日期': '2026-09-10', '收盘': 10}]}
        new = {'daily': [{'日期': '2026-09-11', '收盘': 11}]}
        self.store.save_snapshot('002837', old)
        self.store.save_snapshot('002837', new)
        rows = self.store.snapshots('002837')
        self.assertIn('+10.00%', changes(rows[1]['payload'], rows[0]['payload']))
        self.assertIn('日期相同', changes(new, new))

    def test_invalid_citation_is_blocked(self):
        answer = {'action': 'answer', 'answer': '增长 [E99]', 'supports': {}}
        self.assertIn('未通过', validate_citations(answer, {})['answer'])
        answer = {'action': 'answer', 'answer': '增长 [E1]', 'supports': {'E1': '原文披露收入增长百分之十'}}
        self.assertIn('citation_check', validate_citations(answer, {'E1': {'text': '原文披露收入增长百分之十。'}}))
        answer = {'action': 'answer', 'answer': '增长 [E1]', 'supports': {'E1': 'E1Q1'}}
        self.assertIn('citation_check', validate_citations(answer, {'E1': {'text': '原文披露收入增长百分之十。', 'quotes': {'E1Q1': '原文披露收入增长百分之十'}}}))

    def test_monitor_runs_once_and_records_change(self):
        from datetime import datetime
        with patch('src.background.ResearchRunRepository', return_value=self.repo), patch('src.background.Workbench', return_value=self.store):
            runner = Runner()
        self.store.set_monitor('002837', True)
        self.store.save_snapshot('002837', {'daily': [{'日期': '2026-09-11', '收盘': 10}]})
        with patch('src.background.datetime') as clock, patch('src.stock_data.fetch_stock', return_value={'daily': [{'日期': '2026-09-14', '收盘': 11}]}) as fetch:
            clock.now.return_value = datetime(2026, 9, 14, 17)
            runner.monitor_once()
            runner.monitor_once()
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual(len(self.store.alerts('002837')), 1)

    def test_unknown_history_not_attached_to_current_report(self):
        s = create_agent('test')
        s.report = ResearchReport('test', s.depth, [ReportSection('报告', '当前内容')])
        s.diagnostics['agent']['messages'] = [{'role': 'assistant', 'content': '旧回答' * 150}]
        normalize_history(s)
        self.assertNotIn('report_version', s.diagnostics['agent']['messages'][0])
        self.assertIn('provenance_note', s.diagnostics['agent']['messages'][0])

    @patch('src.agent.load_env')
    def test_empty_synthesis_not_completed(self, _):
        s = create_agent('test')
        s.plan = ResearchPlan('test', s.depth)
        s.synthesis = SynthesisBrief('test', s.depth)
        s.current_stage = 'writing'
        with patch('src.agent.Writer') as writer:
            writer.return_value.write.return_value = ResearchReport('test', s.depth)
            writer.return_value.last_warning = None
            tick(s)
        self.assertEqual(s.status, 'failed')

    def test_background_queue_processes_message_after_tool(self):
        with patch('src.background.ResearchRunRepository', return_value=self.repo), patch('src.background.Workbench', return_value=self.store):
            runner = Runner()
        s = create_agent('test')
        self.repo.save_state(s)
        entered, release = threading.Event(), threading.Event()
        def fake_tick(state, *, store):
            self.assertIs(store, self.store)
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test release timeout')
            state.mark_completed()
        with patch('src.background.tick', side_effect=fake_tick), patch('src.background.respond', return_value={'action': 'answer', 'answer': '已收到补充'}):
            runner.submit(s.run_id, 'resume')
            self.assertTrue(entered.wait(5))
            thread = runner.threads[s.run_id]
            runner.submit(s.run_id, 'chat', '解释一下')
            self.assertEqual(len(self.store.pending(s.run_id)), 1)
            release.set()
            thread.join(5)
            self.assertFalse(thread.is_alive())
        restored = self.repo.get_state(s.run_id)
        self.assertEqual(restored.diagnostics['agent']['messages'][-1]['content'], '已收到补充')
        self.assertEqual(self.store.pending(s.run_id), [])


if __name__ == '__main__':
    unittest.main()
