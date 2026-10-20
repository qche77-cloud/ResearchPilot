"""Prospective registration, immutable review, readonly readiness and clock tests."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor
import unittest

from src.forward_demo import ForwardDemo
from src.forward_ledger import ForwardLedger, replay_review
from src.research_readiness import ReadOnlyWorkbench, audit_version, audit_workbench
from src.research_signals import DEFAULT_RULES, digest, score_archive


class ForwardTests(unittest.TestCase):
    def setUp(self):
        self.demo=ForwardDemo()
        self.addCleanup(self.demo.temporary.cleanup)
        self.store=self.demo.store
        self.ledger=self.demo.ledger
        self.reader=ReadOnlyWorkbench(self.store.path)

    def args(self):
        row=self.reader.financial_version(self.demo.symbol,self.demo.feature_id)
        score=score_archive({'id':row['id'],'captured_at':row['created'],'payload':row['payload']},
                            decision_on='2025-05-05',rules=dict(DEFAULT_RULES,frozen_at='2025-05-02'))
        return {'symbol':self.demo.symbol,'dataset_id':row['id'],'expected_payload_hash':digest(row['payload']),
                'decision_on':'2025-05-05','criterion':self.demo.manifest['cases'][0]['criterion'],
                'request_key':'forward-request-00000001','prediction':True,'note':'离线虚构判断',
                'evidence_ids':score['factors'][0]['input_ids']}

    def register(self,**changes):
        args=self.args()
        args.update(changes)
        return self.ledger.register(**args)

    def test_registration_freezes_values_and_server_time(self):
        record=self.register()
        self.assertEqual(record['created_at'],'2025-05-02T12:00:00+00:00')
        self.assertEqual(record['rules']['frozen_at'],'2025-05-02')
        self.assertEqual(record['score']['score'],'100')
        self.assertEqual(record['mode'],'synthetic_fixture')
        self.assertEqual(record['predictions']['manual'],True)
        self.assertEqual(self.ledger.registration(record['id']),record)

    def test_same_request_is_idempotent_even_after_decision_passes(self):
        args=self.args()
        first=self.ledger.register(**args)
        self.demo.advance()
        self.assertEqual(first,self.ledger.register(**args))
        self.assertEqual(len(self.ledger.registrations()),1)

    def test_changed_request_is_rejected(self):
        self.register()
        with self.assertRaisesRegex(ValueError,'内容发生变化'):
            self.register(note='改变判断依据')

    def test_duplicate_observation_cannot_inflate_count(self):
        self.register()
        with self.assertRaisesRegex(ValueError,'已登记'):
            self.register(request_key='another-request-0000001')

    def test_backdating_or_same_day_decision_rejected(self):
        for value in ('2025-05-01','2025-05-02','2027-05-02'):
            with self.assertRaisesRegex(ValueError,'决策日'):
                self.register(decision_on=value)
        self.assertEqual(self.ledger.registrations(),[])

    def test_changed_payload_after_preview_rejected(self):
        args=self.args()
        with self.store.connect() as db:
            db.execute('UPDATE financial_inputs SET payload=? WHERE id=?',
                       (json.dumps({'symbol':self.demo.symbol,'financial_records':[]}),self.demo.feature_id))
        with self.assertRaisesRegex(ValueError,'内容已变化'):
            self.ledger.register(**args)

    def test_source_after_now_rejected(self):
        with self.store.connect() as db:
            db.execute('UPDATE financial_inputs SET created=? WHERE id=?',('2025-05-03T00:00:00Z',self.demo.feature_id))
        with self.assertRaisesRegex(ValueError,'晚于本机'):
            self.register()

    def test_synthetic_input_is_never_saved_to_real_ledger(self):
        real=ForwardLedger(self.store,clock=lambda:self.demo.clock)
        with self.assertRaisesRegex(ValueError,'虚构'):
            real.register(**self.args())
        self.assertEqual(real.registrations(),[])

    def test_unmarked_fixture_url_still_rejected(self):
        row=self.reader.financial_version(self.demo.symbol,self.demo.feature_id)
        row['payload']['provenance']='user_import'
        audit=audit_version(row,as_of='2025-05-02')
        self.assertTrue(audit['synthetic'])
        self.assertFalse(audit['forward_ready'])

    def test_manual_prediction_requires_a_reason_and_existing_evidence(self):
        for changes in ({'note':''},{'evidence_ids':[]},{'evidence_ids':['unknown']},{'prediction':1}):
            with self.assertRaises(ValueError): self.register(**changes)

    def test_missing_prediction_remains_missing(self):
        record=self.register(prediction=None,note='',evidence_ids=[])
        self.assertIsNone(record['predictions']['manual'])

    def test_financial_rows_unchanged_after_registration(self):
        with self.store.connect() as db:
            before=[tuple(r) for r in db.execute('SELECT * FROM financial_inputs')]
        self.register()
        with self.store.connect() as db:
            self.assertEqual(before,[tuple(r) for r in db.execute('SELECT * FROM financial_inputs')])

    def test_failed_registration_rolls_back_schema_and_data(self):
        with self.store.connect() as db:
            before=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        with self.assertRaises(ValueError): self.register(evidence_ids=['not-existing'])
        with self.store.connect() as db:
            self.assertEqual(before,[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")])

    def test_concurrent_retry_creates_only_one_record(self):
        args=self.args()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self.ledger.register,**args) for _ in range(2)]
            ids=[f.result()['id'] for f in futures]
        self.assertEqual(ids[0],ids[1])
        self.assertEqual(len(self.ledger.registrations()),1)

    def test_not_started_and_not_due_checks_never_become_labels(self):
        record=self.register()
        first=self.ledger.review(record['id'])
        self.assertEqual(first['result']['status'],'awaiting_decision')
        self.demo.clock=datetime(2025,6,1,12,tzinfo=timezone.utc)
        second=self.ledger.review(record['id'])
        self.assertEqual(second['result']['status'],'not_due')
        self.assertIsNone(second['result']['label'])

    def test_due_without_new_data_is_unknown(self):
        record=self.register()
        self.demo.advance()
        review=self.ledger.review(record['id'])
        self.assertEqual(review['result']['status'],'waiting_for_data')
        self.assertIsNone(review['result']['label'])

    def test_known_outcome_and_replay_exact(self):
        record=self.register()
        self.demo.advance()
        review=self.ledger.review(record['id'],outcome_dataset_id='demo-forward-outcome')
        self.assertTrue(review['result']['label'])
        self.assertEqual(review['result'],replay_review(json.loads(json.dumps(review['replay']))))

    def test_review_idempotent_preserves_first_saved_time(self):
        record=self.register()
        self.demo.advance()
        first=self.ledger.review(record['id'],outcome_dataset_id='demo-forward-outcome')
        self.demo.clock=datetime(2026,5,2,13,tzinfo=timezone.utc)
        self.assertEqual(first,self.ledger.review(record['id'],outcome_dataset_id='demo-forward-outcome'))
        self.assertEqual(len(self.ledger.reviews(record['id'])),1)

    def test_future_review_cutoff_and_future_saved_version_rejected(self):
        record=self.register()
        with self.assertRaisesRegex(ValueError,'截止日'):
            self.ledger.review(record['id'],as_of='2026-05-02')
        self.demo.advance()
        with self.assertRaisesRegex(ValueError,'截止日之后'):
            self.ledger.review(record['id'],outcome_dataset_id='demo-forward-outcome',as_of='2025-06-01')

    def test_clock_rollback_cannot_backdate_new_writes(self):
        record=self.register()
        self.demo.advance()
        self.ledger.review(record['id'])
        self.demo.clock=datetime(2025,6,1,12,tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError,'本机时间'):
            self.ledger.review(record['id'])

    def test_outcome_for_other_company_rejected(self):
        record=self.register()
        self.demo.advance()
        with self.store.connect() as db:
            db.execute('INSERT INTO financial_inputs VALUES (?,?,?,?)',
                       ('other','000002','2026-05-01T12:00:00Z','{}'))
        with self.assertRaisesRegex(ValueError,'不存在'):
            self.ledger.review(record['id'],outcome_dataset_id='other')

    def test_revision_does_not_overwrite_original_prediction_or_review(self):
        record=self.register()
        self.demo.advance()
        original=self.ledger.review(record['id'],outcome_dataset_id='demo-forward-outcome')
        self.demo.revise()
        revised=self.ledger.review(record['id'],outcome_dataset_id='demo-forward-revised')
        self.assertTrue(original['result']['label'])
        self.assertFalse(revised['result']['label'])
        self.assertEqual(self.ledger.registration(record['id']),record)
        self.assertEqual(len(self.ledger.reviews(record['id'])),2)
        self.assertEqual(original['result'],replay_review(original['replay']))
        self.assertTrue(revised['result']['previous_review_diff']['changed_financial_values'])

    def test_first_known_and_latest_metrics_never_silently_mix(self):
        record=self.register()
        self.demo.advance()
        self.ledger.review(record['id'],outcome_dataset_id='demo-forward-outcome')
        self.demo.revise()
        self.ledger.review(record['id'],outcome_dataset_id='demo-forward-revised')
        first=self.ledger.summary()
        latest=self.ledger.summary(review_policy='latest')
        self.assertTrue(first['rows'][0]['label'])
        self.assertFalse(latest['rows'][0]['label'])
        self.assertEqual(first['revised_count'],1)
        self.assertEqual(first['groups']['local_prospective']['count'],0)
        self.assertEqual(first['groups']['synthetic_fixture']['with_manual']['n'],1)

    def test_later_review_is_not_visible_in_past_summary(self):
        record=self.register()
        self.demo.advance()
        self.ledger.review(record['id'],outcome_dataset_id='demo-forward-outcome')
        report=self.ledger.summary(as_of='2025-06-01')
        self.assertIsNone(report['rows'][0]['label'])
        self.assertEqual(report['groups']['synthetic_fixture']['rule_baseline']['n'],0)

    def test_missing_manual_prediction_not_filled_in_comparison(self):
        record=self.register(prediction=None,note='',evidence_ids=[])
        self.demo.advance()
        self.ledger.review(record['id'],outcome_dataset_id='demo-forward-outcome')
        group=self.ledger.summary()['groups']['synthetic_fixture']
        self.assertEqual(group['rule_baseline']['n'],1)
        self.assertEqual(group['with_manual']['n'],0)

    def test_sql_updates_and_deletes_are_blocked(self):
        record=self.register()
        self.ledger.review(record['id'])
        for table in ('signal_registrations','signal_reviews'):
            for sql in (f'UPDATE {table} SET checksum=?',f'DELETE FROM {table} WHERE checksum<>?'):
                with self.store.connect() as db:
                    with self.assertRaisesRegex(sqlite3.IntegrityError,'append-only'):
                        db.execute(sql,('bad',))

    def test_checksum_detects_accidental_corruption_even_without_trigger(self):
        record=self.register()
        with self.store.connect() as db:
            db.execute('DROP TRIGGER signal_registrations_no_update')
            db.execute('UPDATE signal_registrations SET checksum=? WHERE id=?',('wrong',record['id']))
        with self.assertRaisesRegex(ValueError,'校验失败'):
            self.ledger.registration(record['id'])

    def test_readonly_access_cannot_write_or_create_missing_database(self):
        before=self.store.path.read_bytes()
        self.reader.watches()
        self.reader.financial_versions(self.demo.symbol)
        self.assertEqual(before,self.store.path.read_bytes())
        with self.reader.connect() as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute('DELETE FROM financial_inputs')
        path=self.store.path.parent/'missing.db'
        with self.assertRaises(ValueError): ReadOnlyWorkbench(path).watches()
        self.assertFalse(path.exists())

    def test_readiness_missing_units_and_publication_remains_unknown(self):
        row=self.reader.financial_version(self.demo.symbol,self.demo.feature_id)
        for item in row['payload']['financial_records']:
            item.pop('published_at',None)
            item['unit']='unknown'
        result=audit_version(row,as_of='2025-05-02')
        self.assertFalse(result['forward_ready'])
        self.assertIsNone(result['score']['score'])
        self.assertIn('unknown_unit',result['record_issues'])
        self.assertIn('publication_required_for_as_of',result['record_issues'])

    def test_readiness_rejects_fetch_later_than_save_same_day(self):
        row=self.reader.financial_version(self.demo.symbol,self.demo.feature_id)
        row['payload']['fetched_at']='2025-05-01T13:00:00Z'
        result=audit_version(row,as_of='2025-05-02')
        self.assertIn('fetched_after_save',{p['code'] for p in result['issues']})

    def test_readiness_summary_is_readonly_and_marks_missing_versions(self):
        self.store.watch('000002','缺少版本的虚构样本')
        before=self.store.path.read_bytes()
        result=audit_workbench(self.store.path,as_of='2025-05-02')
        self.assertEqual(result['company_count'],2)
        self.assertEqual(result['missing_versions'],['000002'])
        self.assertEqual(self.store.path.read_bytes(),before)

    def test_preview_uses_the_exact_evidence_ids_accepted_by_registration(self):
        preview=self.ledger.preview(self.demo.symbol,self.demo.feature_id,decision_on='2025-05-05')
        evidence=[next(iter(preview['score']['inputs']))]
        record=self.register(evidence_ids=evidence,expected_payload_hash=preview['payload_hash'])
        self.assertEqual(record['manual_judgment']['evidence_ids'],evidence)

    def test_real_mode_accepts_unverified_user_source_but_does_not_certify_it(self):
        row=self.reader.financial_version(self.demo.symbol,self.demo.feature_id)
        row['payload']['provenance']='user_import'
        for item in row['payload']['financial_records']:
            item['source_url']='https://reports.example.com/annual'
        with self.store.connect() as db:
            db.execute('UPDATE financial_inputs SET payload=? WHERE id=?',(json.dumps(row['payload']),self.demo.feature_id))
        real=ForwardLedger(self.store,clock=lambda:self.demo.clock)
        preview=real.preview(self.demo.symbol,self.demo.feature_id,decision_on='2025-05-05')
        args=self.args()
        args.update(expected_payload_hash=preview['payload_hash'],evidence_ids=[next(iter(preview['score']['inputs']))])
        record=real.register(**args)
        self.assertEqual(record['mode'],'local_prospective')
        self.assertIn('不是独立授时认证',record['policy'])
        # Explicit test data above is never imported into a user workbench.

    def test_real_registration_rejects_synthetic_outcome(self):
        row=self.reader.financial_version(self.demo.symbol,self.demo.feature_id)
        row['payload']['provenance']='user_import'
        for item in row['payload']['financial_records']: item['source_url']='https://reports.example.com/annual'
        with self.store.connect() as db:
            db.execute('UPDATE financial_inputs SET payload=? WHERE id=?',(json.dumps(row['payload']),self.demo.feature_id))
        real=ForwardLedger(self.store,clock=lambda:self.demo.clock)
        preview=real.preview(self.demo.symbol,self.demo.feature_id,decision_on='2025-05-05')
        args=self.args()
        args.update(expected_payload_hash=preview['payload_hash'],evidence_ids=[next(iter(preview['score']['inputs']))])
        record=real.register(**args)
        self.demo.advance()
        with self.assertRaisesRegex(ValueError,'虚构复盘'):
            real.review(record['id'],outcome_dataset_id='demo-forward-outcome')

    def test_inplace_change_to_an_already_reviewed_version_is_rejected(self):
        record=self.register()
        self.demo.advance()
        self.ledger.review(record['id'],outcome_dataset_id='demo-forward-outcome')
        row=self.reader.financial_version(self.demo.symbol,'demo-forward-outcome')
        row['payload']['financial_records'][-1]['value']='1234'
        with self.store.connect() as db:
            db.execute('UPDATE financial_inputs SET payload=? WHERE id=?',(json.dumps(row['payload']),'demo-forward-outcome'))
        with self.assertRaisesRegex(ValueError,'原地修改'):
            self.ledger.review(record['id'],outcome_dataset_id='demo-forward-outcome')

    def test_registration_preview_and_audit_never_create_ledger_tables(self):
        before=self.store.path.read_bytes()
        self.ledger.preview(self.demo.symbol,self.demo.feature_id,decision_on='2025-05-05')
        self.ledger.summary()
        audit_version(self.reader.financial_version(self.demo.symbol,self.demo.feature_id),as_of='2025-05-02')
        self.assertEqual(self.store.path.read_bytes(),before)

    def test_custom_currency_is_checked_without_default_cny_substitution(self):
        row=self.reader.financial_version(self.demo.symbol,self.demo.feature_id)
        for item in row['payload']['financial_records']: item['currency']='USD'
        with self.store.connect() as db:
            db.execute('UPDATE financial_inputs SET payload=? WHERE id=?',(json.dumps(row['payload']),self.demo.feature_id))
        rules=dict(DEFAULT_RULES,currency='USD')
        preview=self.ledger.preview(self.demo.symbol,self.demo.feature_id,decision_on='2025-05-05',rules=rules)
        self.assertEqual(preview['score']['coverage_weight'],'100')
        with self.assertRaisesRegex(ValueError,'可比较因子'):
            self.ledger.preview(self.demo.symbol,self.demo.feature_id,decision_on='2025-05-05')

    def test_stale_financial_period_is_explicitly_flagged(self):
        row=self.reader.financial_version(self.demo.symbol,self.demo.feature_id)
        report=audit_version(row,as_of='2026-10-20')
        self.assertIn('old_financial_period',{p['code'] for p in report['issues']})
        self.assertGreater(report['financial_age_days'],550)

    def test_summary_keeps_first_known_outcome_beyond_ui_history_page(self):
        record=self.register()
        self.demo.advance()
        first=self.ledger.review(record['id'],outcome_dataset_id='demo-forward-outcome')
        self.demo.revise()
        revised=self.ledger.review(record['id'],outcome_dataset_id='demo-forward-revised')
        # A long persisted history fixture with independently replayable bodies.
        with self.store.connect() as db:
            for index in range(201):
                body=deepcopy(revised)
                body['id']='RV-history-'+str(index)
                body['created_at']=(self.demo.clock+timedelta(seconds=index+1)).isoformat()
                db.execute('INSERT INTO signal_reviews VALUES (?,?,?,?,?,?,?)',
                    (body['id'],record['id'],body['created_at'],body['as_of'],body['dataset_id'],json.dumps(body),digest(body)))
        self.demo.clock+=timedelta(hours=1)
        # Numerical replay is tested separately. Reuse the two already verified
        # packages here so this pagination test does not repeat 400 analyses.
        from unittest.mock import patch
        replayed={digest(first['replay']):first['result'],digest(revised['replay']):revised['result']}
        with patch('src.forward_ledger.replay_review',side_effect=lambda p:replayed[digest(p)]):
            self.assertEqual(len(self.ledger.reviews(record['id'],200)),200)
            summary=self.ledger.summary()
        self.assertIs(summary['rows'][0]['label'],True)
        self.assertTrue(summary['rows'][0]['result_revised'])


class ForwardUITests(unittest.TestCase):
    def app(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_string('from src.forward_research_ui import render_forward_research\nrender_forward_research()').run(timeout=30)
        self.assertFalse(app.exception)
        self.addCleanup(app.session_state['forward_demo_context'].temporary.cleanup)
        return app

    def click(self,app,label):
        next(b for b in app.button if b.label==label).click().run(timeout=30)
        self.assertFalse(app.exception)

    def test_demo_register_review_revision_and_old_replay(self):
        app=self.app()
        self.assertEqual(app.radio[0].value,'隔离演示')
        self.assertTrue(any('临时库' in w.value for w in app.warning))
        self.click(app,'保存前向登记')
        demo=app.session_state['forward_demo_context']
        registration=demo.ledger.registrations()[0]
        self.assertIsNone(registration['predictions']['manual'])
        self.assertEqual([m.value for m in app.metric],['1','0','0'])
        self.click(app,'模拟新财报到来')
        self.assertEqual([m.value for m in app.metric],['1','1','0'])
        self.click(app,'检查并追加复盘')
        self.assertTrue(any('财务判据满足' in i.value for i in app.info))
        first=demo.ledger.reviews(registration['id'])[0]
        self.click(app,'模拟财报修订')
        self.click(app,'检查并追加复盘')
        self.assertTrue(any('财务判据未满足' in i.value for i in app.info))
        self.assertEqual(len(demo.ledger.reviews(registration['id'])),2)
        self.assertTrue(demo.ledger.summary()['rows'][0]['label'])
        self.assertFalse(demo.ledger.summary(review_policy='latest')['rows'][0]['label'])
        history=next(s for s in app.selectbox if s.label=='选择已保存的复盘版本')
        history.set_value(first['id']).run(timeout=30)
        self.click(app,'校验所选版本的重放')
        self.assertTrue(any('重放一致' in s.value for s in app.success))

    def test_manual_judgment_without_reasons_is_rejected_on_page(self):
        app=self.app()
        next(s for s in app.selectbox if s.label=='你的事前判断').set_value('预期满足').run(timeout=30)
        self.click(app,'保存前向登记')
        self.assertTrue(any('请填写依据' in w.value for w in app.warning))
        self.assertEqual(app.session_state['forward_demo_context'].ledger.registrations(),[])

    def test_readiness_reports_missing_version_without_writing(self):
        from src.workbench import Workbench
        from streamlit.testing.v1 import AppTest
        with TemporaryDirectory() as directory:
            store=Workbench(Path(directory)/'readiness.db')
            store.watch('000001','虚构缺版本公司')
            before=store.path.read_bytes()
            code='from src.forward_research_ui import render_readiness\nfrom src.research_readiness import ReadOnlyWorkbench\nrender_readiness(ReadOnlyWorkbench('+repr(str(store.path))+'))'
            app=AppTest.from_string(code).run(timeout=30)
            self.click(app,'只读检查自选财务资料')
            self.assertEqual([m.value for m in app.metric],['1','0','1'])
            self.assertTrue(any('尚无独立财务版本' in i.value for i in app.info))
            self.assertEqual(store.path.read_bytes(),before)


if __name__=='__main__':
    unittest.main()
