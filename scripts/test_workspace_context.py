"""Workspace-bound market/finance reads; temporary data, no provider requests."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from src.agent import create_agent, tick
from src.background import Runner
from src.storage import ResearchRunRepository
from src.workbench import Workbench


class WorkspaceContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.a = Workbench(root / 'a.db')
        self.b = Workbench(root / 'b.db')
        self.repo = ResearchRunRepository(root / 'research.db')
        self.repo.initialize()
        env = patch('src.agent.load_env')
        env.start()
        self.addCleanup(env.stop)

    @staticmethod
    def market(price):
        timestamp = datetime.now(timezone.utc).isoformat()
        return dict(symbol='000001', exchange='SZ', fetched_at=timestamp,
                    adjustment='test_unadjusted', price_unit='CNY',
                    daily=[{'日期': timestamp[:10], '收盘': price}],
                    finance=[], warnings=[])

    @staticmethod
    def financial(value):
        return dict(symbol='000001', provenance='offline_test', financial_records=[
            dict(metric='revenue', value=str(value), period_end='2025-12-31',
                 basis='cumulative', unit='万元', currency='CNY', scope='consolidated',
                 source_url='https://example.invalid/offline-fixture',
                 published_at='2026-04-30')])

    def assert_revenue(self, state, expected):
        records = state.diagnostics['financial_analysis']['records']
        self.assertEqual(next(r['value'] for r in records if r['metric'] == 'revenue'), expected)

    def test_two_workspaces_keep_cached_market_and_financials_separate(self):
        self.a.save_snapshot('000001', self.market(11))
        self.b.save_snapshot('000001', self.market(99))
        self.a.save_financial_dataset('000001', self.financial(11))
        self.b.save_financial_dataset('000001', self.financial(99))
        with patch('src.workbench.Workbench') as default_store, patch('src.stock_data.fetch_stock') as fetch:
            states = []
            for store in (self.a, self.b):
                state = create_agent('研究000001')
                tick(state, store=store)
                states.append(state)
            default_store.assert_not_called()
            fetch.assert_not_called()
        self.assertEqual([s.diagnostics['agent']['market_data']['latest_daily']['收盘'] for s in states], [11, 99])
        self.assert_revenue(states[0], '110000')
        self.assert_revenue(states[1], '990000')

    def test_new_snapshot_is_written_only_to_selected_workbench(self):
        state = create_agent('研究000001')
        with patch('src.stock_data.fetch_stock', return_value=self.market(23)), patch('src.workbench.Workbench') as default_store:
            tick(state, store=self.a)
            default_store.assert_not_called()
        self.assertEqual(self.a.snapshots('000001')[0]['payload']['daily'][0]['收盘'], 23)
        self.assertEqual(self.b.snapshots('000001'), [])

    def test_unavailable_market_keeps_financial_fallback_in_same_workbench(self):
        self.a.save_financial_dataset('000001', self.financial(11))
        self.b.save_financial_dataset('000001', self.financial(99))
        state = create_agent('研究000001')
        with patch('src.stock_data.fetch_stock', side_effect=ConnectionError('offline')), patch('src.workbench.Workbench') as default_store:
            tick(state, store=self.a)
            default_store.assert_not_called()
        self.assert_revenue(state, '110000')
        self.assertIn('行情数据不可用', [e['tool'] for e in state.diagnostics['agent']['events']])
        self.assertEqual(self.a.snapshots('000001'), [])

    def test_failed_injected_store_does_not_fall_back_to_default_database(self):
        store = Mock(spec=Workbench)
        store.snapshots.side_effect = RuntimeError('private storage failure')
        store.financial_dataset.side_effect = RuntimeError('private storage failure')
        state = create_agent('研究000001')
        with patch('src.workbench.Workbench') as default_store, patch('src.stock_data.fetch_stock') as fetch:
            tick(state, store=store)
            default_store.assert_not_called()
            fetch.assert_not_called()
        store.financial_dataset.assert_called_once_with('000001')
        self.assertNotIn('financial_analysis', state.diagnostics)
        self.assertIn('财务输入不可用', [e['tool'] for e in state.diagnostics['agent']['events']])
        self.assertNotIn('private storage failure', str(state.diagnostics['agent']['events']))

    def test_legacy_call_uses_default_desktop_store(self):
        self.a.save_snapshot('000001', self.market(17))
        state = create_agent('研究000001')
        with patch('src.workbench.Workbench', return_value=self.a) as default_store, patch('src.stock_data.fetch_stock') as fetch:
            tick(state)
            default_store.assert_called_once_with()
            fetch.assert_not_called()
        self.assertEqual(state.diagnostics['agent']['market_data']['latest_daily']['收盘'], 17)

    def test_runner_passes_its_workbench_to_each_step(self):
        state = create_agent('研究000001')
        self.repo.save_state(state)
        runner = Runner(self.repo, self.a)
        self.a.enqueue(state.run_id, 'resume')
        received = []

        def step(current, *, store):
            received.append(store)
            current.mark_completed()

        with patch('src.background.tick', side_effect=step):
            runner._run(state.run_id)
        self.assertEqual(received, [self.a])
        self.assertFalse(runner.worker_errors)
        self.assertEqual(self.repo.get_state(state.run_id).status, 'completed')
        self.assertEqual(self.a.pending(state.run_id), [])


if __name__ == '__main__':
    unittest.main()
