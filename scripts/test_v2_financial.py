"""Hand-computed financial golden cases and actual UI/Agent integration."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.financial_analysis import (normalize_financials, single_quarters, growth, ratio,
                                    analyze_financials, chart_points, financial_evidence, valuation,
                                    attach_financial_analysis)
from src.financial_ui import example_dataset
from src.agent import create_agent, tick
from src.workbench import Workbench


def record(metric='revenue', value='100', period='2025-03-31', basis='cumulative', **kwargs):
    row = dict(metric=metric, value=value, period_end=period, basis=basis, unit='万元', currency='CNY',
               scope='consolidated', source_url='https://example.invalid/report', published_at='2026-04-30')
    row.update(kwargs)
    return row


def payload(*rows):
    return dict(symbol='002837', fetched_at='2026-10-12T00:00:00Z', financial_records=list(rows))


class FinancialTests(unittest.TestCase):
    def test_explicit_units_and_zero_are_preserved(self):
        rows = normalize_financials(payload(record(value='0'), record(metric='net_profit', value='2', unit='亿元')))
        self.assertEqual({r['metric']: r['value'] for r in rows}, {'revenue': '0', 'net_profit': '200000000'})
        self.assertTrue(all(r['status'] == 'ok' for r in rows))

    def test_missing_metadata_never_becomes_defaults(self):
        raw = record()
        for name in ('unit', 'currency', 'scope', 'basis'):
            del raw[name]
        row = normalize_financials(payload(raw))[0]
        self.assertEqual(row['status'], 'blocked')
        self.assertEqual(set(row['issues']), {'unknown_unit', 'unknown_currency', 'unknown_accounting_scope', 'unknown_period_basis'})

    def test_other_stock_and_wrong_metric_definition_are_blocked(self):
        self.assertIn('symbol_mismatch', normalize_financials(payload(record(symbol='000001')))[0]['issues'])
        self.assertIn('metric_definition_conflict', normalize_financials(payload(record(metric='cost_of_revenue', item_field='BIZTOTCOST')))[0]['issues'])

    def test_missing_abnormal_and_negative_values(self):
        for value in (None, '', '--', 'NaN', 'Infinity', float('nan'), float('inf'), '-1'):
            self.assertEqual(normalize_financials(payload(record(value=value)))[0]['status'], 'blocked')
        self.assertEqual(normalize_financials(payload(record(metric='net_profit', value='-1')))[0]['status'], 'ok')

    def test_extreme_numbers_future_periods_and_valid_negative_margin(self):
        self.assertEqual(normalize_financials(payload(record(value='1e99999999')))[0]['status'], 'blocked')
        self.assertEqual(normalize_financials(payload(record(period='2030-03-31')))[0]['status'], 'blocked')
        self.assertEqual(normalize_financials(payload(record(metric='gross_margin', value='-10', unit='%')))[0]['status'], 'ok')

    def test_financial_rounding_does_not_depend_on_callers_decimal_context(self):
        from decimal import localcontext, ROUND_UP, ROUND_DOWN
        rows = normalize_financials(payload(record(value='3'), record(metric='cost_of_revenue', value='1')))
        by_metric = {r['metric']: r for r in rows}
        results = []
        for rounding in (ROUND_UP, ROUND_DOWN):
            with localcontext() as ctx:
                ctx.rounding = rounding
                results.append(ratio(by_metric['cost_of_revenue'], by_metric['revenue'], 'gross_margin', True)['value'])
        self.assertEqual(results[0], results[1])

    def test_reporting_period_and_start_validation(self):
        self.assertEqual(normalize_financials(payload(record(period='2025-02-28')))[0]['status'], 'blocked')
        self.assertEqual(normalize_financials(payload(record(period_start='2025-02-01')))[0]['status'], 'blocked')

    def test_conflicting_duplicates_are_blocked(self):
        rows = normalize_financials(payload(record(value='100'), record(value='101')))
        self.assertTrue(all('conflicting_duplicate' in r['issues'] for r in rows))
        self.assertEqual(len(normalize_financials(payload(record(), record()))), 1)

    def test_cumulative_to_quarter_uses_adjacent_inputs(self):
        rows = normalize_financials(payload(record(value='100'), record(value='250', period='2025-06-30')))
        quarters = single_quarters(rows)
        self.assertEqual([r['value'] for r in quarters], ['1000000', '1500000'])
        self.assertEqual(len(quarters[1]['input_ids']), 2)
        self.assertEqual(quarters[1]['period_start'], '2025-04-01')

    def test_missing_prior_cumulative_is_not_annualized(self):
        row = single_quarters(normalize_financials(payload(record(value='250', period='2025-06-30'))))[0]
        self.assertEqual(row['status'], 'blocked')
        self.assertIsNone(row['value'])

    def test_cumulative_margin_is_never_subtracted(self):
        row = single_quarters(normalize_financials(payload(record(metric='gross_margin', unit='%', value='30'))))[0]
        self.assertIn('ratio_cannot_be_differenced', row['issues'])

    def test_decreasing_cumulative_revenue_blocks_negative_derived_quarter(self):
        rows = normalize_financials(payload(record(value='100'), record(value='90', period='2025-06-30')))
        self.assertEqual(single_quarters(rows)[1]['status'], 'blocked')

    def test_yoy_and_qoq_hand_calculations(self):
        rows = normalize_financials(payload(record(value='100', period='2024-03-31'), record(value='120', period='2025-03-31')))
        self.assertEqual(growth(rows[1], rows[0])['value'], '20')
        quarters = single_quarters(normalize_financials(payload(record(value='100'), record(value='250', period='2025-06-30'))))
        self.assertEqual(growth(quarters[1], quarters[0], 'qoq')['value'], '50')

    def test_zero_negative_base_and_currency_mismatch(self):
        for value, reason in [('0', 'zero_base'), ('-10', 'negative_base_not_conventional_growth')]:
            rows = normalize_financials(payload(record(metric='net_profit', value=value, period='2024-03-31'), record(metric='net_profit', value='20')))
            self.assertEqual(growth(rows[1], rows[0])['reason'], reason)
        rows = normalize_financials(payload(record(period='2024-03-31', currency='USD'), record()))
        self.assertEqual(growth(rows[1], rows[0])['reason'], 'incomparable_scope')

    def test_gross_margin_uses_cost_of_revenue_not_total_cost(self):
        rows = normalize_financials(payload(record(value='100'), record(metric='cost_of_revenue', value='70'), record(metric='total_operating_cost', value='90')))
        by_metric = {r['metric']: r for r in rows}
        self.assertEqual(ratio(by_metric['cost_of_revenue'], by_metric['revenue'], 'gross_margin', True)['value'], '30')
        self.assertEqual(ratio(by_metric['total_operating_cost'], by_metric['revenue'], 'gross_margin', True)['status'], 'blocked')

    def test_legacy_source_is_usable_only_after_explicit_metadata_verification(self):
        data = dict(symbol='002837', fetched_at='2026-10-12T00:00:00Z', finance=[{
            '报告期': '20250331', 'item_field': 'BIZTOTCOST', 'item_title': '营业成本', 'item_value': '70'}])
        self.assertEqual(normalize_financials(data)[0]['status'], 'blocked')
        data['finance_metadata'] = dict(verified=True, currency='CNY', money_unit='元', flow_basis='cumulative', scope='consolidated', basis_evidence='用户核对原报表')
        row = normalize_financials(data)[0]
        self.assertEqual(row['status'], 'ok')
        self.assertEqual(row['metric'], 'total_operating_cost')

    def test_full_multi_period_analysis_has_traceable_calculations(self):
        data = example_dataset()
        before = copy.deepcopy(data)
        analysis = analyze_financials(data)
        self.assertEqual(data, before)
        self.assertEqual(analysis['usable_records'], 32)
        points = chart_points(analysis, 'revenue', 'single_quarter')
        self.assertEqual(len(points), 8)
        self.assertTrue(all(p['record_id'] and p['input_ids'] and p['source_url'] for p in points))
        evidence = financial_evidence(analysis)
        for c in evidence['calculations']:
            self.assertTrue(all(i in evidence['inputs'] for i in c['input_ids']))
        ttm = [r for r in analysis['ttm_records'] if r['metric'] == 'attributable_net_profit' and r['period_end'] == '2025-12-31'][0]
        self.assertEqual(ttm['value'], '550000')

    def test_valuation_lineage_has_market_and_financial_inputs(self):
        data = example_dataset()
        data['market_valuation'] = dict(symbol=data['symbol'], value='1000', unit='万元', currency='CNY',
                                        as_of='2026-10-12', source_url='https://example.invalid/market')
        analysis = analyze_financials(data)
        evidence = financial_evidence(analysis)
        self.assertEqual(analysis['valuations'][0]['status'], 'ok')
        self.assertTrue(all(i in evidence['inputs'] for i in analysis['valuations'][0]['input_ids']))

    def test_valuation_positive_and_loss_or_lookahead_blocked(self):
        denominator = normalize_financials(payload(record(metric='attributable_net_profit', value='50', period='2025-12-31')))[0]
        market = dict(id='M1',symbol='002837', value='1000', unit='万元', currency='CNY', as_of='2026-10-12', source_url='https://example.invalid/market')
        self.assertEqual(valuation(market, denominator, 'pe')['value'], '20')
        denominator['value'] = '-500000'
        self.assertEqual(valuation(market, denominator, 'pe')['status'], 'blocked')
        denominator['value'] = '500000'
        denominator['published_at'] = '2026-12-01'
        self.assertEqual(valuation(market, denominator, 'pe')['status'], 'blocked')

    def test_pb_requires_parent_net_assets_and_instant_basis(self):
        denominator = normalize_financials(payload(record(metric='attributable_net_assets', value='500', period='2025-12-31', basis='instant')))[0]
        market = dict(id='M1',symbol='002837', value='1000', unit='万元', currency='CNY', as_of='2026-10-12', source_url='https://example.invalid/market')
        self.assertEqual(valuation(market, denominator, 'pb')['value'], '2')
        denominator['metric'] = 'net_assets'
        self.assertEqual(valuation(market, denominator, 'pb')['status'], 'blocked')


class FinancialIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Workbench(Path(self.tmp.name) / 'workbench.db')

    def test_separate_financial_storage_does_not_overwrite_price_snapshots(self):
        self.store.save_snapshot('002837', {'daily': [{'日期': '2026-10-12', '收盘': 10}]})
        data = example_dataset()
        with self.assertRaises(ValueError):
            self.store.save_financial_dataset('002837', data)
        data['provenance'] = 'user_import'
        self.store.save_financial_dataset('002837', data)
        self.assertEqual(self.store.financial_dataset('002837')['payload'], data)
        self.assertEqual(len(self.store.snapshots('002837')), 1)
        self.assertIsNone(self.store.financial_dataset('000001'))

    @patch('src.agent.load_env')
    def test_agent_uses_imported_financials_even_if_price_source_fails(self, _):
        data = example_dataset()
        data['provenance'] = 'user_import'
        self.store.save_financial_dataset('002837', data)
        state = create_agent('研究002837现金流')
        with patch('src.workbench.Workbench', return_value=self.store), patch('src.stock_data.fetch_stock', side_effect=ConnectionError('fixture unavailable')):
            tick(state)
        self.assertEqual(state.diagnostics['financial_analysis']['usable_records'], 32)
        self.assertTrue(any(s.source_type == 'financial_calculation' for s in state.sources))
        self.assertIsNone(state.plan)

    def test_agent_evidence_serializes_formula_and_inputs(self):
        state = create_agent('研究002837现金流')
        attach_financial_analysis(state, example_dataset())
        doc = next(d for d in state.documents if d.source.source_type == 'financial_calculation')
        content = json.loads(doc.extracted_text)
        self.assertIn('values', content)
        self.assertTrue(content['calculations'][0]['input_ids'])

    def test_financial_page_and_demo_are_usable_offline(self):
        from streamlit.testing.v1 import AppTest
        code = ('from src.workbench import Workbench\nfrom src.financial_ui import render_financial_tools\n'
                f's=Workbench({str(self.store.path)!r})\nrender_financial_tools(s,"002837")')
        app = AppTest.from_string(code).run(timeout=20)
        self.assertFalse(app.exception)
        app.checkbox(key='fin_demo_002837').check().run(timeout=20)
        self.assertFalse(app.exception)
        self.assertGreater(len(app.dataframe), 1)
        self.assertTrue(any('合成示例' in w.value for w in app.warning))

    def test_full_agent_app_opens_new_financial_tools_with_only_temporary_databases(self):
        from streamlit.testing.v1 import AppTest
        from src.storage import ResearchRunRepository
        from src.background import Runner
        import streamlit as st
        repo = ResearchRunRepository(Path(self.tmp.name) / 'research.db')
        repo.initialize()
        data = example_dataset()
        data['provenance'] = 'user_import'
        self.store.save_financial_dataset('002837', data)
        with patch('src.background.Workbench', return_value=self.store), patch('src.background.ResearchRunRepository', return_value=repo):
            runner = Runner()
        st.cache_resource.clear()
        with patch('src.background.Runner', return_value=runner), patch.object(runner, 'start_monitors'):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'agent_app.py')).run(timeout=20)
            self.assertFalse(app.exception)
            next(b for b in app.button if b.label == '个股与自选').click().run(timeout=20)
            self.assertFalse(app.exception)
            self.assertTrue(any('多期财务分析' in h.value for h in app.subheader))
            self.assertGreaterEqual(len(app.dataframe), 2)
        st.cache_resource.clear()


if __name__ == '__main__':
    unittest.main()
