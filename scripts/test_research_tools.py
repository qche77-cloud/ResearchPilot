"""Offline accounting identities, financial signal scopes and criterion history."""
from copy import deepcopy
from decimal import Decimal, localcontext
import json
from pathlib import Path
import tempfile
import unittest

from src.financial_analysis import analyze_financials, attach_financial_analysis
from src.financial_diagnostics import research_diagnostics
from src.thesis_tracking import evaluate_test,validate_test
from src.workbench import Workbench


def research_fixture():
    rows=[]
    for year,values in [(2024,[1000,600,100,250,80,70,120,100,100,40]),
                        (2025,[1200,840,60,300,50,15,40,150,150,30])]:
        metrics=['revenue','cost_of_revenue','net_profit','expense','attributable_net_profit',
                 'attributable_profit_excluding_nonrecurring','operating_cash_flow','inventory','accounts_receivable','rd_expense']
        for metric,value in zip(metrics,values):
            rows.append(dict(metric=metric,value=str(value),unit='元',currency='CNY',scope='consolidated',
                             basis='instant' if metric in {'inventory','accounts_receivable'} else 'cumulative',
                             period_end=f'{year}-12-31',published_at=f'{year+1}-03-30',
                             source_url='https://example.invalid/fictional-filing'))
    return dict(symbol='002837',provenance='offline_synthetic_test',fetched_at='2026-10-18T00:00:00Z',financial_records=rows)


def test_spec():
    return {'review_on':'2026-04-01','criteria':[{'metric':'revenue','measure':'yoy','operator':'>=',
            'threshold':'15','period_end':'2025-12-31','basis':'cumulative','currency':'CNY','scope':'consolidated'}]}


class DiagnosticsTests(unittest.TestCase):
    def analyze(self,payload=None,**options):
        return research_diagnostics(analyze_financials(payload or research_fixture(),as_of='2026-04-01'),**options)

    def test_seven_distinct_questions_have_actual_inputs(self):
        result=self.analyze()
        self.assertEqual(result['triggered_count'],7)
        self.assertEqual(result['unavailable_count'],0)
        ids={r['id'] for r in analyze_financials(research_fixture())['records']}
        self.assertTrue(all(r['input_ids'] and set(r['input_ids'])<=ids for r in result['rules']))

    def test_bridge_reconciles_known_accounting_identity(self):
        b=self.analyze()['profit_bridge']
        self.assertEqual(b['status'],'ok')
        self.assertTrue(b['reconciled'])
        self.assertEqual([s['value'] for s in b['steps']],['100','80','-120','-50','50','60'])
        self.assertEqual(sum(Decimal(s['value']) for s in b['steps'][:-1]),Decimal('60'))
        self.assertEqual(b['change'],'-40')

    def test_missing_expense_is_visible_not_zero_filled(self):
        payload=research_fixture()
        payload['financial_records']=[r for r in payload['financial_records'] if r['metric']!='expense']
        b=self.analyze(payload)['profit_bridge']
        self.assertEqual(b['status'],'ok')
        self.assertEqual(b['missing_components'],['两期期间费用'])
        self.assertFalse(any(s['key']=='expense' for s in b['steps']))
        self.assertEqual(next(s['value'] for s in b['steps'] if s['key']=='residual'),'0')

    def test_attributable_profit_never_substitutes_consolidated_net_profit(self):
        payload=research_fixture()
        payload['financial_records']=[r for r in payload['financial_records'] if r['metric']!='net_profit']
        self.assertEqual(self.analyze(payload)['profit_bridge']['status'],'unavailable')

    def test_currency_scope_missing_dates_and_negative_balances(self):
        for field,value in [('currency','USD'),('scope','parent_company'),('published_at',None)]:
            payload=research_fixture()
            next(r for r in payload['financial_records'] if r['metric']=='net_profit' and r['period_end']=='2025-12-31')[field]=value
            self.assertEqual(self.analyze(payload)['profit_bridge']['status'],'unavailable')
        payload=research_fixture()
        next(r for r in payload['financial_records'] if r['metric']=='inventory')['value']='-1'
        row=next(r for r in analyze_financials(payload)['records'] if r['metric']=='inventory' and r['period_end']=='2024-12-31')
        self.assertEqual(row['status'],'blocked')

    def test_cutoff_prevents_future_financial_signal(self):
        a=analyze_financials(research_fixture(),as_of='2026-03-01')
        result=research_diagnostics(a,period_end='2025-12-31')
        self.assertEqual(result['triggered_count'],0)
        self.assertEqual(result['unavailable_count'],7)

    def test_duplicate_conflict_is_not_resolved_by_latest_row(self):
        payload=research_fixture()
        r=deepcopy(next(r for r in payload['financial_records'] if r['metric']=='revenue' and r['period_end']=='2025-12-31'))
        r['value']='500'
        payload['financial_records'].append(r)
        self.assertEqual(self.analyze(payload)['profit_bridge']['status'],'unavailable')

    def test_thresholds_explicit_and_context_validation(self):
        result=self.analyze(thresholds={'gross_margin_drop_pp':20})
        self.assertEqual(next(r['status'] for r in result['rules'] if r['code']=='gross_margin_drop'),'clear')
        for options in ({'thresholds':{'bad':'1'}},{'thresholds':{'gross_margin_drop_pp':'NaN'}},{'basis':'ttm'}):
            with self.assertRaises(ValueError):self.analyze(**options)

    def test_bridge_rounding_keeps_reconciliation_and_positive_base_requirement(self):
        payload=research_fixture()
        next(r for r in payload['financial_records'] if r['metric']=='revenue' and r['period_end']=='2024-12-31')['value']='333'
        self.assertTrue(self.analyze(payload)['profit_bridge']['reconciled'])
        next(r for r in payload['financial_records'] if r['metric']=='revenue' and r['period_end']=='2024-12-31')['value']='0'
        self.assertEqual(self.analyze(payload)['profit_bridge']['status'],'unavailable')

    def test_extreme_valid_input_does_not_crash_or_emit_unbounded_contribution(self):
        payload=research_fixture()
        next(r for r in payload['financial_records'] if r['metric']=='revenue' and r['period_end']=='2024-12-31')['value']='1e-90'
        self.assertEqual(self.analyze(payload)['profit_bridge']['status'],'unavailable')

    def test_agent_receives_exact_question_and_bridge_evidence(self):
        from src.agent import create_agent
        state=create_agent('研究002837')
        attach_financial_analysis(state,research_fixture(),as_of='2026-04-01')
        self.assertEqual(state.diagnostics['financial_research']['triggered_count'],7)
        docs=[d for d in state.documents if '财务异常与利润变化分解' in d.source.title]
        self.assertEqual(len(docs),1)
        corpus=json.loads(docs[0].extracted_text)
        self.assertTrue(corpus['inputs'])
        self.assertTrue(corpus['diagnostics']['profit_bridge']['reconciled'])


class TrackingTests(unittest.TestCase):
    def evaluate(self,spec=None,payload=None,as_of='2026-04-01'):
        return evaluate_test(dict(spec or test_spec(),symbol='002837'),payload or research_fixture(),as_of=as_of)

    def test_deadline_missing_data_met_and_unmet_are_different(self):
        self.assertEqual(self.evaluate()['status'],'criterion_met')
        self.assertEqual(self.evaluate(as_of='2026-03-01')['status'],'not_due')
        spec=test_spec();spec['review_on']='2026-02-01'
        self.assertEqual(self.evaluate(spec,as_of='2026-03-01')['status'],'waiting_for_data')
        spec=test_spec();spec['criteria'][0]['threshold']='30'
        self.assertEqual(self.evaluate(spec)['status'],'criterion_not_met')

    def test_does_not_use_another_period_or_currency_as_target(self):
        for field,value in [('period_end','2026-03-31'),('currency','USD'),('scope','parent_company')]:
            spec=test_spec();spec['criteria'][0][field]=value
            self.assertEqual(self.evaluate(spec)['status'],'waiting_for_data')

    def test_gross_margin_uses_currency_and_scope_metadata(self):
        spec=test_spec();spec['criteria'][0].update(metric='gross_margin',measure='value',threshold='35')
        result=self.evaluate(spec)
        self.assertEqual(result['status'],'criterion_not_met')
        self.assertEqual(result['observations'][0]['value'],'30')

    def test_multiple_currencies_do_not_suppress_the_matching_margin_calculation(self):
        payload=research_fixture()
        payload['financial_records'] += [dict(r,currency='USD') for r in deepcopy(payload['financial_records'])]
        spec=test_spec();spec['criteria'][0].update(metric='gross_margin',measure='value',threshold='25')
        result=self.evaluate(spec,payload=payload)
        self.assertEqual(result['status'],'criterion_met')
        self.assertEqual(result['observations'][0]['value'],'30')
        self.assertTrue(all(r['currency']=='CNY' for r in result['inputs'].values()))

    def test_multiple_criteria_need_all_data_and_all_met(self):
        spec=test_spec();other=deepcopy(spec['criteria'][0]);other.update(metric='net_profit',threshold='0')
        spec['criteria'].append(other)
        self.assertEqual(self.evaluate(spec)['status'],'criterion_not_met')
        other['currency']='USD'
        self.assertEqual(self.evaluate(spec)['status'],'waiting_for_data')

    def test_validation_and_source_immutability(self):
        payload=research_fixture();before=deepcopy(payload)
        result=self.evaluate(payload=payload)
        self.assertEqual(payload,before)
        self.assertTrue(result['inputs'])
        for field,value in [('threshold','NaN'),('operator','='),('period_end','2025-12-30'),('basis','instant')]:
            spec=test_spec();spec['criteria'][0][field]=value
            with self.assertRaises(ValueError):validate_test(spec)
        with self.assertRaises(ValueError):evaluate_test(dict(test_spec(),symbol='600000'),payload,as_of='2026-04-01')

    def test_saved_runs_versions_revisions_and_manual_review_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Workbench(Path(tmp)/'workbench.db')
            store.add_thesis('002837','收入增长能够兑现','新财报','增长不足')
            thesis=store.theses('002837')[0]
            before=deepcopy(thesis)
            dataset=store.save_financial_dataset('002837',research_fixture())
            revision=store.save_thesis_test('002837',thesis['id'],test_spec(),expected_revision=0,baseline_dataset_id=dataset,baseline_as_of='2026-04-01')
            self.assertEqual(revision,1)
            with self.assertRaises(ValueError):store.save_thesis_test('002837',thesis['id'],test_spec(),expected_revision=0)
            first=store.run_thesis_test('002837',thesis['id'],expected_revision=1,dataset_id=dataset,as_of='2026-04-01')
            self.assertEqual(first,store.run_thesis_test('002837',thesis['id'],expected_revision=1,dataset_id=dataset,as_of='2026-04-01'))
            self.assertEqual(len(store.thesis_test_runs('002837',thesis['id'])),1)
            data=research_fixture();next(r for r in data['financial_records'] if r['metric']=='revenue' and r['period_end']=='2025-12-31')['value']='1050'
            revised=store.save_financial_dataset('002837',data)
            store.run_thesis_test('002837',thesis['id'],expected_revision=1,dataset_id=revised,as_of='2026-04-01')
            runs=store.thesis_test_runs('002837',thesis['id'])
            self.assertEqual(runs[0]['payload']['status'],'criterion_not_met')
            self.assertEqual(runs[1]['payload']['status'],'criterion_met')
            self.assertEqual(len(runs[0]['payload']['revisions']),1)
            self.assertEqual(store.theses('002837')[0],before)
            spec=test_spec();spec['criteria'][0]['threshold']='0'
            store.save_thesis_test('002837',thesis['id'],spec,expected_revision=1)
            self.assertEqual(len(store.thesis_test_versions('002837',thesis['id'])),2)
            self.assertEqual(runs[1]['payload']['criteria']['criteria'][0]['threshold'],'15')
            with self.assertRaises(ValueError):store.run_thesis_test('002837',thesis['id'],expected_revision=1,dataset_id=dataset,as_of='2026-04-01')
            with self.assertRaises(ValueError):store.save_thesis_test('600000',thesis['id'],test_spec(),expected_revision=0)


class ResearchBridgeTests(unittest.TestCase):
    def test_read_only_view_and_explicit_save_run_events(self):
        from src.background import Runner
        from src.storage import ResearchRunRepository
        from src.studio_bridge import consume_event
        from src.studio_company import company_view
        with tempfile.TemporaryDirectory() as tmp:
            store=Workbench(Path(tmp)/'workbench.db')
            repo=ResearchRunRepository(Path(tmp)/'research.db');repo.initialize()
            service=Runner(repo,store)
            dataset=store.save_financial_dataset('002837',research_fixture())
            store.add_thesis('002837','收入保持增长','','')
            thesis=store.theses('002837')[0]
            session={'studio_company':'002837','studio_dataset':dataset,'studio_finance_asof':'2026-04-01'}
            before=deepcopy(thesis)
            for _ in range(2):
                view=company_view(service,session)
                self.assertEqual(view['research']['triggered_count'],7)
                self.assertIsNone(view['theses'][0]['test'])
            from unittest.mock import patch
            with patch.object(store,'thesis_test',None):
                self.assertFalse(company_view(service,session)['tracking_ready'])
            self.assertFalse(store.thesis_test_runs('002837',thesis['id']))
            event={'id':'save-1','action':'save_thesis_test','symbol':'002837','thesis_id':thesis['id'],
                   'revision':0,'dataset_id':dataset,'as_of':'2026-04-01','test':test_spec()}
            consume_event(event,service,session)
            self.assertEqual(store.thesis_test('002837',thesis['id'])['revision'],1)
            run=dict(event,id='run-1',action='run_thesis_test',revision=1)
            consume_event(run,service,session)
            self.assertEqual(len(store.thesis_test_runs('002837',thesis['id'])),1)
            consume_event(run,service,session)
            self.assertEqual(len(store.thesis_test_runs('002837',thesis['id'])),1)
            consume_event(dict(run,id='stale-date',as_of='2026-03-01'),service,session)
            self.assertIn('已变化',session['studio_notice'])
            consume_event(dict(run,id='wrong-stock',symbol='600000'),service,session)
            self.assertIn('公司已切换',session['studio_notice'])
            self.assertEqual(store.theses('002837')[0],before)
            service._studio_preview=True
            consume_event(dict(event,id='preview-save',revision=1),service,session)
            self.assertIn('离线预览',session['studio_notice'])
            self.assertEqual(store.thesis_test('002837',thesis['id'])['revision'],1)

    def test_old_database_upgrade_is_additive(self):
        import sqlite3
        from contextlib import closing
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'old.db'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE preferences (id INTEGER PRIMARY KEY,content TEXT NOT NULL)')
                db.execute('INSERT INTO preferences VALUES (1,?)',('保留原有偏好',))
                db.commit()
            store=Workbench(path)
            self.assertEqual(store.preferences(),'保留原有偏好')
            self.assertFalse(store.thesis_test_runs('002837','missing'))


if __name__=='__main__':unittest.main()
