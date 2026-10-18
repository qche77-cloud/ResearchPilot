"""PDF confirmation, exact-period peer math, durable lineage and bounded intents."""
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from src.financial_import import propose_rows, confirmed_payload, prepare_import, extract_pdf
from src.peer_research import compare_peers
from src.studio_bridge import consume_event, start_run
from scripts import test_cockpit as cockpit_fixtures
supplied_fixture=cockpit_fixtures.supplied_fixture

ROOT=Path(__file__).resolve().parents[1]
REAL=json.loads((ROOT/'evals/financial_reports_real.json').read_text(encoding='utf-8'))['reports']


def proposal(symbol='002837'):
    content=b'%PDF fictional fixture'
    pages=[dict(page=1,text=f'公司代码 {symbol}\n主要会计数据 2025年 2024年\n单位：元\n营业收入 120.00 100.00\n归属于上市公司股东的净利润 8.00 10.00')]
    with patch('src.financial_import.extract_pdf',return_value=pages):
        p=prepare_import(content,symbol=symbol,period_end='2025-12-31',published_at='2026-04-01',source_url='https://example.invalid/fictional.pdf',filename='fictional.pdf')
    return p,content


def confirm(p,selected=None,**kw):
    options=dict(unit='元',currency='CNY',scope='consolidated',basis='cumulative',confirmed=True)
    options.update(kw)
    return confirmed_payload(p,selected or [r['id'] for r in p['candidates']],**options)


class ImportTests(unittest.TestCase):
    def test_real_table_golden_values_and_exact_locations(self):
        for fixture in REAL:
            rows=propose_rows(fixture['pages'],'2024-12-31')
            self.assertEqual(len(rows),len(fixture['expected']))
            for golden in fixture['expected']:
                actual=next(r for r in rows if (r['metric'],r['period_end'])==(golden['metric'],golden['period_end']))
                self.assertEqual(actual['value'],golden['value'])
                self.assertEqual(actual['page'],fixture['pages'][0]['page'])
                self.assertIn(actual['excerpt'], ' '.join(fixture['pages'][0]['text'].splitlines()))

    def test_confirmation_required_and_different_periods_preserved(self):
        p,_=proposal();payload=confirm(p)
        self.assertEqual(len(payload['financial_records']),4)
        self.assertEqual({r['period_end'] for r in payload['financial_records']},{'2024-12-31','2025-12-31'})
        with self.assertRaises(ValueError): confirm(p,confirmed=False)
        with self.assertRaises(ValueError): confirm(p,['unknown'])

    def test_conflicting_same_period_requires_selection(self):
        p,_=proposal();r=deepcopy(p['candidates'][0]);r.update(id='other',value='999');p['candidates'].append(r)
        with self.assertRaises(ValueError): confirm(p)
        self.assertEqual(len(confirm(p,[p['candidates'][0]['id']])['financial_records']),1)

    def test_unknown_units_and_bad_amount_blocked(self):
        p,_=proposal()
        for args in [dict(unit='千元'),dict(currency='unknown'),dict(scope='unknown'),dict(basis='ttm')]:
            with self.assertRaises(ValueError): confirm(p,**args)
        p['candidates'][0]['value']='-1'
        with self.assertRaises(ValueError): confirm(p)

    def test_file_budget_encryption_and_scans(self):
        for content in (b'not pdf',b'%PDF'+b'0'*(12*1024*1024)):
            with self.assertRaises(ValueError): extract_pdf(content)
        from src.financial_import_worker import extract
        from pypdf import PdfWriter
        import io
        writer=PdfWriter();writer.add_blank_page(100,100);out=io.BytesIO();writer.write(out)
        with self.assertRaises(ValueError): extract(out.getvalue())
        writer.encrypt('secret');out=io.BytesIO();writer.write(out)
        with self.assertRaises(ValueError): extract(out.getvalue())

    def test_timeout_and_malformed_pdf_fail_without_model(self):
        import subprocess
        with patch('subprocess.run',side_effect=subprocess.TimeoutExpired('parser',45)):
            with self.assertRaises(ValueError): extract_pdf(b'%PDF fail')
        with self.assertRaises(ValueError): extract_pdf(b'%PDF malformed')

    def test_header_required_for_prior_year_proposal(self):
        rows=propose_rows([dict(page=4,text='营业收入 120.00 100.00')],'2025-12-31')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['period_end'],'2025-12-31')

    def test_accounting_negative_and_explicit_unit_scope_conflicts(self):
        pages=[dict(page=2,text='主要会计数据 2025年 2024年\n单位：万元\n母公司利润表\n净利润 (12.00) (10.00)')]
        rows=propose_rows(pages,'2025-12-31')
        self.assertEqual([r['value'] for r in rows],['-12.00','-10.00'])
        p,_=proposal();p['candidates']=rows
        with self.assertRaises(ValueError): confirm(p,unit='元',scope='parent_company')
        with self.assertRaises(ValueError): confirm(p,unit='万元',scope='consolidated')


class PeerTests(unittest.TestCase):
    def pool(self):
        return {s:supplied_fixture(s) for s in ('002837','600000','600001')}

    def compare(self,pool=None,**kw):
        options=dict(symbols=['002837','600000','600001'],period_end='2025-12-31',as_of='2026-10-14')
        options.update(kw)
        return compare_peers(pool if pool is not None else self.pool(),**options)

    def test_exact_decimal_medians_deltas_and_source_ids(self):
        pool=self.pool()
        for symbol,cost in [('002837','80'),('600000','60'),('600001','40')]:
            for r in pool[symbol]['financial_records']:
                if r['period_end']=='2025-12-31' and r['metric'] in {'revenue','cost_of_revenue'}:
                    r['value']=cost if r['metric']=='cost_of_revenue' else '100';r['unit']='元'
        result=self.compare(pool)
        gross=[r for r in result['rows'] if any(f['key']=='gross_margin' and f['status']=='ok' for f in r['factors'])]
        self.assertEqual(len(gross),3)
        for row in gross:
            f=next(f for f in row['factors'] if f['key']=='gross_margin')
            self.assertTrue(all(i in row['inputs'] for i in f['input_ids']))
        self.assertEqual(result['summaries']['gross_margin']['median'],'40')
        self.assertEqual([next(f['group_delta'] for f in r['factors'] if f['key']=='gross_margin') for r in gross],['-20','0','20'])
        self.assertEqual([l['symbol'] for l in result['leads'] if l['kind']=='gross_margin_peer_gap'],['002837'])

    def test_missing_future_and_scope_do_not_silently_compare(self):
        self.assertEqual(self.compare({})['summaries']['revenue_yoy']['count'],0)
        r=self.compare(as_of='2025-12-31')
        self.assertEqual(r['summaries']['revenue_yoy']['count'],0)
        r=self.compare(scope='parent_company')
        self.assertEqual(r['summaries']['revenue_yoy']['count'],0)
        r=self.compare(period_end='2024-12-31')
        self.assertTrue(all(f['period_end']=='2024-12-31' for row in r['rows'] for f in row['factors']))

    def test_no_horizontal_lead_for_two_valid_samples(self):
        r=self.compare({k:v for k,v in self.pool().items() if k!='600001'})
        self.assertFalse(any(l['kind']=='gross_margin_peer_gap' for l in r['leads']))

    def test_bad_group_and_parameters(self):
        for args in [dict(symbols=['002837','002837']),dict(symbols=['bad','600000']),dict(period_end='2025-11-30'),dict(as_of='bad'),dict(currency='bad')]:
            with self.assertRaises(ValueError): self.compare(**args)


class PeerIntegrationTests(unittest.TestCase):
    setUp=cockpit_fixtures.CockpitTests.setUp
    event=cockpit_fixtures.CockpitTests.event
    # Reuse isolated DB setup only; inherited legacy tests remain independently
    # executed by their original suite, so remove inheritance collection below.
    def test_pdf_transaction_history_stale_guard_and_original_hash(self):
        p,content=proposal();payload=confirm(p)
        first=self.store.save_pdf_import(payload,content,None)
        self.assertEqual(self.store.financial_document('002837',p['id'])['content'],content)
        self.assertEqual(len(self.store.financial_documents('002837')),1)
        with self.assertRaises(ValueError): self.store.save_pdf_import(payload,content,None)
        self.assertEqual(self.store.financial_dataset('002837')['id'],first)
        self.assertIsNone(self.store.financial_document('600000',p['id']))
        with self.assertRaises(ValueError): self.store.save_pdf_import(payload,b'wrong',first)

    def test_import_retains_previous_period_and_old_version(self):
        original=supplied_fixture();before=self.store.save_financial_dataset('002837',original)
        p,content=proposal();payload=confirm(p)
        new=self.store.save_pdf_import(payload,content,before)
        self.assertEqual(self.store.financial_version('002837',before)['payload'],original)
        merged=self.store.financial_version('002837',new)['payload']['financial_records']
        self.assertTrue(any(r['period_end']=='2024-03-31' for r in merged))
        self.assertEqual(len([r for r in merged if r['metric']=='revenue' and r['period_end']=='2025-12-31']),1)

    def test_fixed_run_reopens_after_financial_revision(self):
        for symbol in ('002837','600000','600001'): self.store.save_financial_dataset(symbol,supplied_fixture(symbol))
        group=self.store.save_peer_group('测试比较组',['002837','600000','600001'])
        args=dict(symbol='002837',group_id=group,period_end='2025-12-31',as_of='2026-10-14',basis='cumulative',currency='CNY',scope='consolidated')
        self.event('compare_peers',**args)
        run=self.store.peer_run(self.session['studio_peer_run']);before=deepcopy(run)
        changed=supplied_fixture();changed['financial_records'][0]['value']='999'
        self.store.save_financial_dataset('002837',changed)
        reopened=self.store.peer_run(run['id'])
        self.assertEqual(before,reopened)
        self.assertEqual(self.store.peer_history('002837')[0]['id'],run['id'])
        self.event('open_peer_run',symbol='600000',run_id=run['id'])
        self.assertIn('公司已切换',self.session['studio_notice'])

    def test_lead_starts_with_archived_inputs_and_structured_evidence(self):
        p,content=proposal();self.store.save_pdf_import(confirm(p),content,None)
        self.store.save_financial_dataset('600000',supplied_fixture('600000'))
        group=self.store.save_peer_group('fixture',['002837','600000'])
        self.event('compare_peers',symbol='002837',group_id=group,period_end='2025-12-31',as_of='2026-10-14',basis='cumulative',currency='CNY',scope='consolidated')
        row=self.store.peer_run(self.session['studio_peer_run'])
        lead=next(l for l in row['result']['leads'] if l['symbol']=='002837')
        changed=confirm(p);changed['financial_records'][0]['value']='999'
        self.store.save_financial_dataset('002837',changed)
        with patch.object(self.service,'submit') as submit:
            self.event('research_peer_lead',symbol='002837',run_id=row['id'],lead_id=lead['id'])
            state=self.repo.get_state(self.session['studio_run'])
            self.assertEqual(state.diagnostics['agent']['financial_input_context']['dataset_id'],row['bindings']['002837'])
            self.assertEqual(state.diagnostics['peer_research']['lead']['id'],lead['id'])
            self.assertTrue(any('同业比较' in d.extracted_text for d in state.documents))
            submit.assert_called_once()


if __name__=='__main__': unittest.main()
