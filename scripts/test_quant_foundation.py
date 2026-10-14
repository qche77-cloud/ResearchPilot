"""Golden-value financial screening, time boundaries and invalid bar regressions."""
import copy
from datetime import date
from pathlib import Path
import unittest
from unittest.mock import patch
import pandas as pd
from src.financial_analysis import analyze_financials, normalize_financials, attach_financial_analysis
from src.financial_quality import financial_quality
from src.financial_ui import example_dataset
from src.research_memory import financial_snapshot
from src.stock_data import validate_daily
from src.agent import create_agent
from src.financial_screening import screen_financials


def dataset():
    data = example_dataset()
    extra = [dict(r, metric='net_profit') for r in data['financial_records'] if r['metric'] == 'attributable_net_profit']
    data['financial_records'].extend(extra)
    return data


class TemporalTests(unittest.TestCase):
    def test_publication_after_fetch_is_blocked(self):
        data = example_dataset()
        data['financial_records'][0]['published_at'] = '2099-01-01'
        self.assertTrue(any('publication_after_fetch' in r['issues'] for r in normalize_financials(data)))

    def test_invalid_and_before_period_publications_are_blocked(self):
        for publication in ('wrong', '2024-03-01', '2024-04-01junk'):
            data = example_dataset()
            data['financial_records'][0]['published_at'] = publication
            self.assertTrue(any(r['status'] == 'blocked' for r in normalize_financials(data)))

    def test_as_of_excludes_missing_and_later_publications(self):
        data = example_dataset()
        del data['financial_records'][0]['published_at']
        result = analyze_financials(data, as_of='2025-05-01')
        self.assertTrue(any('publication_required_for_as_of' in r['issues'] for r in result['records']))
        self.assertTrue(any('not_available_as_of' in r['issues'] for r in result['records']))
        self.assertTrue(all(r['period_end'].startswith('2024') for r in result['records'] if r['status'] == 'ok'))

    def test_invalid_as_of_fails_instead_of_using_current_values(self):
        with self.assertRaises(ValueError):
            analyze_financials(example_dataset(), as_of='2026-01-01junk')

    def test_delayed_availability_and_invalid_order(self):
        data = example_dataset()
        row = data['financial_records'][0]
        row['available_at'] = '2026-07-01'
        blocked = normalize_financials(data, as_of='2026-06-01')
        self.assertIn('not_available_as_of', next(r for r in blocked if r['raw'].get('available_at'))['issues'])
        row['available_at'] = '2024-04-01'
        self.assertTrue(any('availability_before_publication' in r['issues'] for r in normalize_financials(data)))

    def test_future_revision_does_not_block_old_known_value(self):
        data = example_dataset()
        old = copy.deepcopy(data['financial_records'][0])
        revised = dict(old, value='999', published_at='2026-08-01')
        data['financial_records'].append(revised)
        rows = normalize_financials(data, as_of='2025-06-01')
        self.assertTrue(any(r['value'] == '1000000' and r['status'] == 'ok' for r in rows))

    def test_historical_pe_selects_older_available_annual_report(self):
        data = dataset()
        data['market_valuation'] = dict(symbol='002837', currency='CNY', unit='万元', value='700',
                                        as_of='2026-02-01', source_url='https://example.invalid/price')
        result = analyze_financials(data)
        pe = next(v for v in result['valuations'] if v['kind'] == 'pe')
        self.assertEqual(pe['status'], 'ok')
        self.assertEqual(pe['financial_period'], '2024-12-31')
        self.assertEqual(pe['value'], '10')

    def test_derived_dates_and_memory_keep_availability(self):
        data = dataset()
        # Every 2025 quarterly value shares a conservative annual disclosure date.
        result = analyze_financials(data, as_of='2026-06-01')
        last = next(r for r in result['ttm_records'] if r['metric'] == 'net_profit' and r['period_end'] == '2025-12-31')
        self.assertEqual(last['available_at'], '2026-04-30')
        snapshot = financial_snapshot(result)
        self.assertEqual(snapshot['as_of'], '2026-06-01')
        self.assertTrue(all('published_at' in r and 'available_at' in r for r in snapshot['records']))


class BarTests(unittest.TestCase):
    def bars(self, **kwargs):
        row = {'日期': '2026-10-13', '开盘': 10., '收盘': 11., '最高': 12., '最低': 9., '成交量': 100.}
        row.update(kwargs)
        return pd.DataFrame([row])

    def test_inconsistent_high_low_and_negative_volume_are_rejected(self):
        for fields in ({'最高': 2}, {'最低': 12}, {'成交量': -1}):
            with self.assertRaises(ValueError):
                validate_daily(self.bars(**fields))

    def test_nonfinite_missing_and_invalid_prices_are_rejected(self):
        for value in (float('inf'), float('-inf'), float('nan'), None, 'bad', 0):
            with self.assertRaises(ValueError):
                validate_daily(self.bars(最高=value))

    def test_invalid_and_duplicate_dates_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_daily(self.bars(日期='invalid'))
        with self.assertRaises(ValueError):
            validate_daily(pd.concat([self.bars(), self.bars()], ignore_index=True))

    def test_valid_zero_volume_sorted_copy(self):
        frame = pd.concat([self.bars(), self.bars(日期='2026-10-12', 成交量=0)], ignore_index=True)
        original = frame.copy(deep=True)
        result = validate_daily(frame)
        self.assertEqual(result['日期'].iloc[0], '2026-10-12')
        pd.testing.assert_frame_equal(frame, original)

    def test_future_bar_rejected_against_explicit_request_date(self):
        with self.assertRaises(ValueError):
            validate_daily(self.bars(日期='2026-10-15'), as_of=date(2026, 10, 14))


class QualityTests(unittest.TestCase):
    def test_hand_calculated_factors_and_flags(self):
        result = financial_quality(dataset(), as_of='2026-10-01')
        factors = {f['key']: f for f in result['factors']}
        self.assertEqual(result['available_factors'], 5)
        self.assertEqual(factors['gross_margin']['value'], '30')
        self.assertEqual(factors['cash_conversion']['value'], '0.8')
        self.assertTrue(factors['net_margin']['value'].startswith('7.857142857'))
        self.assertEqual({f['code'] for f in result['flags']}, {'revenue_profit_divergence', 'cash_below_profit'})

    def test_parent_profit_never_substitutes_consolidated_cash_denominator(self):
        result = financial_quality(example_dataset(), as_of='2026-10-01')
        self.assertEqual(next(f for f in result['factors'] if f['key'] == 'cash_conversion')['status'], 'unavailable')

    def test_missing_dates_and_currency_do_not_become_zero(self):
        data = dataset()
        for r in data['financial_records']:
            r.pop('published_at')
        result = financial_quality(data, as_of='2026-10-01')
        self.assertEqual(result['available_factors'], 0)
        self.assertTrue(all(f['value'] is None for f in result['factors']))
        self.assertEqual(financial_quality(dataset(), as_of='2026-10-01', currency='USD')['available_factors'], 0)

    def test_lineage_is_complete_and_repeatable(self):
        data = dataset()
        before = copy.deepcopy(data)
        result = financial_quality(data, as_of='2026-10-01')
        self.assertEqual(result, financial_quality(data, as_of='2026-10-01'))
        self.assertEqual(data, before)
        for f in result['factors']:
            for key in f['input_ids']:
                self.assertIn(key, result['inputs'])
        for r in result['inputs'].values():
            for key in r['input_ids']:
                self.assertIn(key, result['inputs'])

    def test_nonpositive_cash_denominator_is_unavailable(self):
        data = dataset()
        for r in data['financial_records']:
            if r['metric'] == 'net_profit':
                r['value'] = '0'
        result = financial_quality(data, as_of='2026-10-01')
        cash = next(f for f in result['factors'] if f['key'] == 'cash_conversion')
        self.assertEqual(cash['reason'], 'nonpositive_denominator')

    def test_historical_quality_does_not_use_later_annual_data(self):
        result = financial_quality(dataset(), as_of='2025-06-01')
        self.assertEqual(result['period_end'], '2024-12-31')
        self.assertEqual(result['available_factors'], 3)  # growth lacks 2023, margins and cash remain usable

    def test_latest_period_does_not_mix_older_revenue(self):
        data = dataset()
        data['financial_records'] = [r for r in data['financial_records'] if not (r['metric'] == 'revenue' and r['period_end'].startswith('2025'))]
        result = financial_quality(data, as_of='2026-10-01')
        self.assertEqual(result['period_end'], '2025-12-31')
        self.assertEqual(next(f for f in result['factors'] if f['key'] == 'gross_margin')['status'], 'unavailable')

    def test_agent_receives_actual_calculation_evidence(self):
        import json
        state = create_agent('研究002837现金流')
        attach_financial_analysis(state, dataset())
        self.assertEqual(state.diagnostics['financial_quality']['available_factors'], 5)
        document = next(d for d in state.documents if '财务质量体检' in d.source.title)
        self.assertEqual(json.loads(document.extracted_text)['factors'][4]['value'], '0.8')

    def test_panel_usable_with_offline_fixture_and_historical_date(self):
        from streamlit.testing.v1 import AppTest
        code = ('from scripts.test_quant_foundation import dataset\nfrom src.financial_quality_ui import render_financial_quality\n'
                'render_financial_quality(dataset(),key="fixture")')
        app = AppTest.from_string(code).run(timeout=20)
        self.assertFalse(app.exception)
        app.date_input(key='fixture_date').set_value(date(2025, 6, 1)).run()
        self.assertFalse(app.exception)
        self.assertTrue(any('2024-12-31' in c.value for c in app.caption))


class ScreeningTests(unittest.TestCase):
    def test_conditions_are_explained_and_missing_values_are_not_zero(self):
        result = screen_financials({'002837': dataset(), '600000': {'symbol': '600000'}}, as_of='2026-10-01',
                                  minimums={'revenue_yoy': '0', 'attributable_profit_yoy': '0'})
        self.assertEqual(result['matched_count'], 0)
        self.assertTrue(all(r['reasons'] for r in result['rows']))
        self.assertTrue(all(f['value'] is None for f in result['rows'][1]['quality']['factors']))

    def test_boundaries_and_cross_stock_inputs(self):
        with self.assertRaises(ValueError):
            screen_financials({str(i): {} for i in range(51)}, as_of='2026-10-01')
        with self.assertRaises(ValueError):
            screen_financials({'600000': dataset()}, as_of='2026-10-01')
        with self.assertRaises(ValueError):
            screen_financials({}, as_of='2026-10-01', minimums={'revenue_yoy': 'NaN'})

    def test_demo_rule_selects_one_fictional_sample_repeatably(self):
        from src.financial_screening_ui import demo_pool
        pool = demo_pool()
        kwargs = dict(as_of='2026-10-01', minimums={'revenue_yoy': '0', 'attributable_profit_yoy': '0'})
        a = screen_financials(pool, **kwargs)
        self.assertEqual(a, screen_financials(pool, **kwargs))
        self.assertEqual(a['matched_count'], 1)
        self.assertEqual(next(r['symbol'] for r in a['rows'] if r['matched']), '600000')

    def test_demo_ui_never_writes_or_triggers_real_research(self):
        import tempfile
        from src.workbench import Workbench
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'workbench.db')
            code = ('import streamlit as st\nfrom src.workbench import Workbench\n'
                    'from src.financial_screening_ui import render_financial_screening\n'
                    f'store=Workbench({path!r})\n'
                    'def start(*args,**kwargs):\n    raise AssertionError("demo must not trigger research")\n'
                    'render_financial_screening(store,start)')
            app = AppTest.from_string(code).run(timeout=20)
            app.checkbox(key='screen_demo').check().run()
            next(b for b in app.button if b.label == '运行财务筛选').click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any('匹配 1/2' in c.value for c in app.caption))
            self.assertFalse(any(b.label.startswith('Agent 核查 ') for b in app.button))
            store = Workbench(path)
            self.assertEqual(store.watches(), [])
            self.assertIsNone(store.financial_dataset('600000'))


if __name__ == '__main__':
    unittest.main()
