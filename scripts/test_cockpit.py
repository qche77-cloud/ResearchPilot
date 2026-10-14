"""Finance import/version lineage, company memory, reviews and reproducible screens."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from src.agent import create_agent
from src.background import Runner
from src.financial_ui import example_dataset
from src.studio_bridge import consume_event, packet, execute_screen
from src.studio_company import import_financial, company_view
from src.storage import ResearchRunRepository
from src.workbench import Workbench


def supplied_fixture(symbol='002837'):
    data=example_dataset(symbol)
    data['provenance']='offline_unit_test_user_supplied'
    return data


class CockpitTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Workbench(Path(self.tmp.name)/'workbench.db')
        self.repo=ResearchRunRepository(Path(self.tmp.name)/'research.db')
        self.repo.initialize()
        self.service=Runner(self.repo,self.store)
        self.session={'studio_company':'002837','studio_view':'company','studio_finance_asof':'2026-10-14'}
        self.data=supplied_fixture()

    def event(self,action,**args):
        consume_event(dict(id=str(len(self.session.get('studio_events',[]))+1),action=action,**args),self.service,self.session)

    def test_import_versions_are_immutable_and_stock_scoped(self):
        first=import_financial(self.store,'002837',json.dumps(self.data))
        second=deepcopy(self.data);second['financial_records'][0]['value']='999'
        new=import_financial(self.store,'002837',json.dumps(second))
        self.assertNotEqual(first,new)
        self.assertEqual(self.store.financial_version('002837',first)['payload'],self.data)
        self.assertIsNone(self.store.financial_version('600000',first))
        self.session['studio_dataset']=first
        self.assertEqual(company_view(self.service,self.session)['dataset_id'],first)

    def test_invalid_import_never_overwrites_data(self):
        first=import_financial(self.store,'002837',json.dumps(self.data))
        for content in ['[]','{"symbol":"002837","x":NaN}',json.dumps(example_dataset()),json.dumps(supplied_fixture('600000')),'x'*(2*1024*1024+1)]:
            with self.assertRaises((ValueError,TypeError)):
                import_financial(self.store,'002837',content)
        self.assertEqual(self.store.financial_dataset('002837')['id'],first)

    def test_date_filtered_finance_and_exact_lineage(self):
        import_financial(self.store,'002837',json.dumps(self.data))
        self.session['studio_finance_asof']='2025-04-29'
        view=company_view(self.service,self.session)
        self.assertEqual(view['analysis']['usable_records'],0)
        self.session['studio_finance_asof']='2026-10-14'
        view=company_view(self.service,self.session)
        rows=[r for r in view['analysis']['quarter_records'] if r['metric']=='revenue' and r['period_end']=='2025-12-31']
        self.assertEqual(rows[0]['value'],'2300000')
        self.assertEqual(len(rows[0]['input_ids']),2)
        for rid in rows[0]['input_ids']:
            self.assertIn(rid,view['evidence']['inputs'])

    def test_company_profile_and_preferences_persist(self):
        self.event('save_profile',symbol='002837',focus='关注现金流',supporting='用户记录',contrary='利润下滑',questions='核查费用')
        self.event('save_preferences',symbol='002837',content='优先核查原始财报')
        reopened=Workbench(self.store.path)
        self.assertEqual(reopened.profile('002837')['focus'],'关注现金流')
        self.assertEqual(reopened.preferences(),'优先核查原始财报')

    def test_review_cas_preserves_newer_judgment(self):
        self.store.add_thesis('002837','增长是否兑现','新增订单','现金流下降')
        thesis=self.store.theses('002837')[0]
        before={'status':thesis['status'],'review':thesis['review']}
        self.event('review_thesis',symbol='002837',thesis_id=thesis['id'],before=before,review='第一次复盘',status='得到支持')
        self.event('review_thesis',symbol='002837',thesis_id=thesis['id'],before=before,review='过时复盘',status='被推翻')
        self.assertEqual(self.store.theses('002837')[0]['review'],'第一次复盘')
        self.assertEqual(len(self.store.review_history(thesis['id'])),1)
        self.assertIn('复盘已变更',self.session['studio_notice'])

    def test_stale_company_and_other_stock_thesis_rejected(self):
        self.event('save_profile',symbol='600000',focus='不能跨公司')
        self.assertEqual(self.store.profile('600000')['focus'],'')
        self.store.add_thesis('600000','另一家公司','','')
        self.event('review_thesis',symbol='002837',thesis_id=self.store.theses('600000')[0]['id'],review='不能混入',status='得到支持')
        self.assertIn('无效',self.session['studio_notice'])

    def test_timeline_compares_only_same_company_saved_snapshots(self):
        for day,judgment,text in [('01','direction_supported','最初判断'),('02','contradicted_by_data','出现反面证据')]:
            state=create_agent('公司002837研究')
            state.created_at=f'2026-04-{day}T00:00:00Z'
            state.mark_completed()
            state.diagnostics['agent']['stock_symbol']='002837'
            state.diagnostics['agent']['report_versions']={day:dict(as_of=state.created_at,sections=[dict(title='结论',content=text)],evidence={},findings=[dict(text=text,kind='inference',evidence_ids=[])],hypotheses=[dict(id='H1',content='增长兑现',judgment=judgment,uncertainty='高',questions=['核查现金流'])])}
            self.repo.save_state(state);self.store.link_run('002837',state.run_id)
        view=company_view(self.service,self.session)
        self.assertEqual(len(view['timeline']),2)
        self.assertEqual(len(view['timeline'][0]['diff']['invalidated_hypotheses']),1)
        self.assertIsNone(view['timeline'][1]['diff'])
        self.assertIn('+出现反面证据',view['timeline'][0]['report_diff'])

    def test_saved_preset_and_run_survive_store_reopen(self):
        self.store.watch('002837','离线演示')
        import_financial(self.store,'002837',json.dumps(self.data))
        self.session['studio_criteria']=dict(as_of='2026-10-14',minimums={'revenue_yoy':0})
        self.event('save_preset',name='营收增长')
        preset=self.store.screening_presets()[0]
        self.event('run_preset',preset_id=preset['id'])
        reopened=Workbench(self.store.path)
        self.assertEqual(reopened.screening_presets()[0]['criteria']['as_of'],'2026-10-14')
        self.assertEqual(reopened.screening_executions()[0]['preset_revision'],1)

    def test_replay_uses_original_financial_version_after_new_import(self):
        self.store.watch('002837','离线演示')
        first=import_financial(self.store,'002837',json.dumps(self.data))
        criteria=dict(as_of='2026-10-14',minimums={'revenue_yoy':0})
        original=execute_screen(self.service,self.session,criteria)
        execution=self.store.screening_executions()[0]
        updated=deepcopy(self.data)
        for row in updated['financial_records']:
            if row['metric']=='revenue' and row['period_end']=='2025-12-31':row['value']='1000'
        import_financial(self.store,'002837',json.dumps(updated))
        latest=execute_screen(self.service,self.session,criteria)
        self.assertNotEqual(original['id'],latest['id'])
        replay=execute_screen(self.service,self.session,criteria,archived=execution['input_ids'])
        self.assertEqual(original['id'],replay['id'])
        self.assertEqual(execution['input_ids']['002837']['dataset_id'],first)

    def test_invalid_saved_preset_and_preview_paid_actions_blocked(self):
        with self.assertRaises(ValueError):self.store.save_screening_preset('bad',dict(as_of='invalid',minimums={}))
        with self.assertRaises(ValueError):self.store.save_screening_preset('bad',dict(as_of='2026-10-14',basis='unknown',minimums={}))
        self.service._studio_preview=True;self.service._studio_fixture_writes=True
        self.event('company_research',symbol='002837')
        self.assertIn('不保存或启动真实研究',self.session['studio_notice'])
        self.assertEqual(self.repo.count_runs(),0)

    def test_company_research_pins_selected_financial_version_and_date(self):
        first=import_financial(self.store,'002837',json.dumps(self.data))
        updated=deepcopy(self.data)
        updated['financial_records'][0]['value']='999'
        import_financial(self.store,'002837',json.dumps(updated))
        self.session['studio_dataset']=first
        with patch.object(self.service,'submit') as submit:
            self.event('company_research',symbol='002837')
        state=self.repo.get_state(self.session['studio_run'])
        self.assertEqual(state.diagnostics['agent']['financial_input_context'],dict(dataset_id=first,as_of='2026-10-14'))
        self.assertTrue(state.diagnostics['agent']['market_checked'])
        self.assertTrue(any(r['value']=='1000000' for r in state.diagnostics['financial_analysis']['records'] if r['period_end']=='2024-03-31' and r['metric']=='revenue'))
        submit.assert_called_once_with(state.run_id,'resume')

    def test_cockpit_pe_and_pb_have_deterministic_eligible_denominators(self):
        row=dict(metric='attributable_net_assets',value='500',unit='万元',currency='CNY',scope='consolidated',basis='instant',period_end='2025-12-31',published_at='2026-04-30',source_url='https://example.invalid/unit-financial-source')
        self.data['financial_records'].append(row)
        import_financial(self.store,'002837',json.dumps(self.data))
        self.event('valuation',symbol='002837',value='55000000',currency='CNY',as_of='2026-10-14',source_url='https://example.invalid/unit-market-source')
        values={v['kind']:v['value'] for v in self.session['studio_valuation']['results'] if v['status']=='ok'}
        self.assertEqual(values,{'pe':'100','pb':'11'})


if __name__=='__main__':unittest.main()
