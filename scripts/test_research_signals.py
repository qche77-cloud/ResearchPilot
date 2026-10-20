"""Golden financial research scores, temporal leakage and fair-cohort regressions."""
from copy import deepcopy
import json
import unittest

from src.research_signal_fixtures import demo_manifest
from src.research_signals import (DEFAULT_RULES, checked_rules, digest, evaluate_experiment,
                                  score_archive, score_financials)


class SignalTests(unittest.TestCase):
    def setUp(self):
        self.data = demo_manifest()

    def evaluate(self,data=None,**kw):
        return evaluate_experiment(self.data if data is None else data,as_of=kw.pop('as_of','2026-05-02'),**kw)

    def test_hand_calculated_scores_and_unknown_coverage(self):
        rows = self.evaluate()['rows']
        self.assertEqual([r['score']['score'] for r in rows],['100','44','58',None,'100'])
        self.assertEqual(rows[3]['score']['coverage_weight'],'70')
        self.assertIsNone(rows[3]['predictions']['rules'])
        cash = next(f for f in rows[3]['score']['factors'] if f['key']=='cash_conversion')
        self.assertIsNone(cash['contribution'])
        self.assertIsNone(cash['points'])

    def test_golden_confusion_matrices_use_same_four_cases(self):
        result = self.evaluate()
        cohort = result['all_methods_cohort']
        self.assertEqual(cohort['case_ids'],['fictional-1','fictional-2','fictional-3','fictional-5'])
        self.assertEqual({m:v['n'] for m,v in cohort['metrics'].items()},{'baseline':4,'rules':4,'agent':4})
        self.assertEqual(cohort['metrics']['baseline']['accuracy'],'0.5')
        self.assertEqual(cohort['metrics']['rules']['accuracy'],'0.75')
        self.assertEqual(cohort['metrics']['rules']['fp'],1)
        self.assertEqual(cohort['metrics']['agent']['fp'],1)
        self.assertEqual(result['coverage']['rules'],{'decisions':4,'labeled':4,'total':5})
        self.assertEqual(result['coverage']['baseline']['labeled'],5)

    def test_future_changes_never_change_decision_features(self):
        before = self.evaluate()
        self.data['snapshots'][1]['payload']['financial_records'][-1]['value']='999999'
        after = self.evaluate()
        self.assertEqual(before['rows'][0]['score'],after['rows'][0]['score'])
        self.assertNotEqual(before['rows'][0]['outcome_hash'],after['rows'][0]['outcome_hash'])

    def test_input_immutable_and_json_replay_exact(self):
        original = deepcopy(self.data)
        result = self.evaluate()
        replay = result['replay']
        self.assertEqual(result,evaluate_experiment(**json.loads(json.dumps(replay))))
        self.assertEqual(self.data,original)

    def test_versioned_dataset_matches_fixture_generator(self):
        from pathlib import Path
        path=Path(__file__).resolve().parents[1]/'evals'/'research_signal_cases.json'
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')),self.data)

    def test_every_factor_and_derived_input_is_traceable(self):
        score = self.evaluate()['rows'][0]['score']
        for row in score['factors']+list(score['inputs'].values()):
            for key in row['input_ids']:
                self.assertIn(key,score['inputs'])

    def test_future_feature_archive_rejected(self):
        self.data['snapshots'][0]['captured_at']='2025-05-06'
        with self.assertRaisesRegex(ValueError,'决策'):
            self.evaluate()

    def test_same_day_capture_rejected_conservatively(self):
        self.data['snapshots'][0]['captured_at']='2025-05-05'
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_timestamp_timezone_cannot_move_late_capture_to_previous_day(self):
        self.data['snapshots'][0]['captured_at']='2025-05-04T23:30:00Z'
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_naive_timestamp_is_not_a_verified_date(self):
        self.data['snapshots'][0]['captured_at']='2025-05-01T12:00:00'
        with self.assertRaisesRegex(ValueError,'时区'):
            self.evaluate()

    def test_post_capture_fetched_data_rejected(self):
        self.data['snapshots'][0]['payload']['fetched_at']='2025-05-02T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'采集'):
            self.evaluate()

    def test_post_capture_row_fetched_override_rejected(self):
        self.data['snapshots'][0]['payload']['financial_records'][0]['fetched_at']='2025-05-02'
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_future_publication_not_used_as_feature(self):
        payload = self.data['snapshots'][0]['payload']
        for r in payload['financial_records']:
            if r['period_end'].startswith('2024') and r['metric']=='revenue':
                r['published_at']='2025-06-01'
        score = score_archive(self.data['snapshots'][0],decision_on='2025-05-05',rules=self.data['rules'])
        self.assertIsNone(score['score'])
        revenue = next(f for f in score['factors'] if f['key']=='revenue_yoy')
        self.assertIsNone(revenue['value'])

    def test_blocked_future_values_are_not_exported_as_decision_evidence(self):
        archive=self.data['snapshots'][0]
        extra=deepcopy(archive['payload']['financial_records'][-1])
        extra.update(period_end='2025-12-31',published_at='2026-04-30',value='999999')
        archive['payload']['financial_records'].append(extra)
        score=score_archive(archive,decision_on='2025-05-05',rules=self.data['rules'])
        self.assertFalse(any(r['value']=='999999' for r in score['inputs'].values()))
        self.assertTrue(all(r['status']=='ok' and r['period_end']<'2025-05-05' for r in score['inputs'].values()))

    def test_cross_currency_never_fills_missing_factors(self):
        payload = self.data['snapshots'][0]['payload']
        for r in payload['financial_records']:
            if r['metric']=='operating_cash_flow':
                r['currency']='USD'
        score = score_financials(payload,as_of='2025-05-05')
        self.assertIsNone(score['score'])
        self.assertEqual(score['coverage_weight'],'70')

    def test_negative_profit_base_is_unavailable_not_positive_growth(self):
        payload = self.data['snapshots'][0]['payload']
        for r in payload['financial_records']:
            if r['period_end'].startswith('2023') and r['metric']=='attributable_net_profit':
                r['value']='-10'
        score = score_financials(payload,as_of='2025-05-05')
        self.assertIsNone(score['score'])
        self.assertIsNone(next(f for f in score['factors'] if f['key']=='attributable_profit_yoy')['value'])

    def test_invalid_rules_fail_closed(self):
        for mutate in [lambda r:r.update(threshold='NaN'),lambda r:r['factors'][0].update(weight='-1'),
                       lambda r:r['factors'][0].update(cutoffs=['20','10','0']),
                       lambda r:r['factors'][0].update(key='cash_conversion'),lambda r:r.update(points=['0','0','70','100'])]:
            rules = deepcopy(DEFAULT_RULES)
            mutate(rules)
            with self.assertRaises(ValueError):
                checked_rules(rules)

    def test_rule_versions_change_fingerprint(self):
        changed = deepcopy(self.data['rules'])
        changed['threshold']='59'
        before = self.evaluate()
        after = self.evaluate(rules=changed)
        self.assertNotEqual(before['rules_hash'],after['rules_hash'])
        self.assertNotEqual(before['id'],after['id'])

    def test_registration_and_universe_and_rules_must_precede_decision(self):
        for path in ('registered','universe','rules'):
            data,rules=deepcopy(self.data),deepcopy(self.data['rules'])
            if path=='registered': data['cases'][0]['registered_at']='2025-05-05'
            elif path=='universe': data['universe']['known_at']='2025-05-06'
            else: rules['frozen_at']='2025-05-05'
            with self.assertRaises(ValueError):
                self.evaluate(data,rules=rules)

    def test_missing_archive_cannot_fall_back_to_latest(self):
        self.data['cases'][0]['feature_snapshot_id']='missing'
        with self.assertRaisesRegex(ValueError,'指定档案'):
            self.evaluate()

    def test_cross_company_archive_is_rejected(self):
        self.data['cases'][0]['outcome_snapshot_id']='outcome-2'
        with self.assertRaisesRegex(ValueError,'公司'):
            self.evaluate()

    def test_future_label_is_pending_not_failed_prediction(self):
        result=self.evaluate(as_of='2025-06-01')
        self.assertTrue(all(r['label'] is None and r['outcome'] is None for r in result['rows']))
        self.assertEqual(result['all_methods_cohort']['n'],0)
        self.assertIsNone(result['all_methods_cohort']['metrics']['rules']['accuracy'])

    def test_missing_outcome_is_unknown_not_negative(self):
        self.data['snapshots'][1]['payload']['financial_records']=[]
        row=self.evaluate()['rows'][0]
        self.assertIsNone(row['label'])
        self.assertEqual(row['outcome_status'],'waiting_for_data')

    def test_outcome_cannot_already_exist_before_decision(self):
        self.data['cases'][0]['outcome_snapshot_id']='feature-1'
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_past_target_is_not_a_forward_claim(self):
        self.data['cases'][0]['criterion']['criteria'][0]['period_end']='2024-12-31'
        with self.assertRaisesRegex(ValueError,'决策日之后'):
            self.evaluate()

    def test_late_or_unbound_agent_judgment_is_unavailable(self):
        for field,value in [('recorded_at','2025-05-05'),('recorded_at','invalid'),
                            ('feature_hash','wrong'),('criterion_hash','wrong'),('evidence_ids',['missing'])]:
            data=deepcopy(self.data)
            data['cases'][0]['agent_call'][field]=value
            result=self.evaluate(data)
            self.assertIsNone(result['rows'][0]['predictions']['agent'])
            self.assertEqual(result['all_methods_cohort']['n'],3)
            self.assertEqual(result['rule_baseline_cohort']['n'],4)

    def test_missing_agent_never_substitutes_the_rule_prediction(self):
        for case in self.data['cases']: case.pop('agent_call',None)
        result=self.evaluate()
        self.assertEqual(result['all_methods_cohort']['n'],0)
        self.assertEqual(result['coverage']['agent']['decisions'],0)

    def test_duplicate_observations_cannot_inflate_sample_size(self):
        other=deepcopy(self.data['cases'][0])
        other['id']='other-id'
        self.data['cases'].append(other)
        with self.assertRaisesRegex(ValueError,'重复计数'):
            self.evaluate()

    def test_duplicate_ids_and_excessive_case_count_rejected(self):
        for data in [dict(self.data,cases=[self.data['cases'][0]]*2),dict(self.data,cases=self.data['cases']*21)]:
            with self.assertRaises(ValueError):
                self.evaluate(data)

    def test_universe_membership_is_explicit(self):
        self.data['universe']['symbols'].remove('000001')
        with self.assertRaisesRegex(ValueError,'样本池'):
            self.evaluate()

    def test_invalid_precision_denominator_stays_unknown(self):
        rules=deepcopy(self.data['rules'])
        rules['threshold']='100'
        result=self.evaluate(as_of='2025-06-01',rules=rules)
        self.assertIsNone(result['all_methods_cohort']['metrics']['rules']['precision'])

    def test_actual_rule_version_cannot_be_backdated_by_default(self):
        with self.assertRaisesRegex(ValueError,'规则'):
            score_archive(self.data['snapshots'][0],decision_on='2025-05-05')

    def test_inverted_or_incomparable_label_task_rejected(self):
        for change in ({'operator':'<'},{'period_end':'2026-03-31'},{'threshold':'1000'}):
            data=deepcopy(self.data)
            data['cases'][0]['criterion']['criteria'][1].update(change)
            with self.assertRaises(ValueError):
                self.evaluate(data)


class SignalUITests(unittest.TestCase):
    def test_demo_run_and_pending_labels_are_usable_without_database(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_string('from src.signal_validation_ui import render_signal_validation\nrender_signal_validation()').run(timeout=25)
        self.assertFalse(app.exception)
        next(b for b in app.button if b.label=='运行离线验证').click().run(timeout=25)
        self.assertFalse(app.exception)
        self.assertEqual([m.value for m in app.metric[:3]],['5','4','4'])
        from datetime import date
        app.date_input(key='signal_review_date').set_value(date(2025,6,1))
        next(b for b in app.button if b.label=='运行离线验证').click().run(timeout=25)
        self.assertFalse(app.exception)
        self.assertEqual([m.value for m in app.metric[:3]],['5','0','0'])

    def test_current_score_is_explicitly_separate_from_replay(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_string('from src.signal_validation_ui import render_signal_validation\nrender_signal_validation()').run(timeout=25)
        next(b for b in app.button if b.label=='计算透明评分').click().run(timeout=25)
        self.assertFalse(app.exception)
        self.assertTrue(any(m.value=='100' for m in app.metric))
        self.assertTrue(any('虚构财务' in w.value for w in app.warning))

    def test_retired_studio_validation_navigation_returns_to_research(self):
        from unittest.mock import Mock
        from src.studio_bridge import consume_event
        service=Mock(_studio_preview=True)
        session={}
        self.assertTrue(consume_event({'id':'signal-navigation','action':'navigate','view':'signals'},service,session))
        self.assertEqual(session['studio_view'],'research')
        service.submit.assert_not_called()
        service.start_monitors.assert_not_called()


if __name__=='__main__':
    unittest.main()
