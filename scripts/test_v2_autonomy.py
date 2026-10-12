"""Actual financial triggers, bounded planning, graph lineage and critic checks."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.agent import create_agent, choose_action, tick
from src.models import ResearchPlan, ResearchPlanStep, SynthesisBrief, GroundedFinding, ResearchReport, ReportSection
from src.evaluator import EvidenceEvaluator
from src.financial_analysis import attach_financial_analysis, bind_financial_tasks
from src.financial_ui import example_dataset
from src.research_reasoning import (update_hypotheses, reflect_plan, build_evidence_graph, critic_review,
                                    normalized_query, query_is_new)
from src.storage import ResearchRunRepository


def financial_state():
    state = create_agent('研究002837营收与利润', 2)
    state.diagnostics['agent']['stock_symbol'] = '002837'
    state.plan = ResearchPlan(state.topic, state.depth, [ResearchPlanStep(1, '收入与利润', '核对财务原文', ['002837 年报'])])
    attach_financial_analysis(state, example_dataset())
    bind_financial_tasks(state)
    state.evidence = EvidenceEvaluator().evaluate(state.documents, state.plan)
    return state


class HypothesisTests(unittest.TestCase):
    def test_revenue_profit_divergence_has_real_calculation_refs(self):
        state = financial_state()
        h = next(h for h in update_hypotheses(state) if h.get('rule') == 'revenue_profit_alignment')
        self.assertEqual(h['judgment'], 'contradicted_by_data')
        observation = h['contrary'][0]
        self.assertEqual(observation['period'], '2025-12-31')
        ids = {c['id'] for c in state.diagnostics['financial_analysis']['computations']}
        self.assertTrue(all(i in ids for i in observation['evidence_ids']))
        self.assertGreater(len(observation['input_ids']), 1)
        self.assertTrue(h['questions'])

    def test_unknown_financial_metadata_does_not_trigger_a_false_contradiction(self):
        state = create_agent('研究002837')
        data = example_dataset()
        for r in data['financial_records']:
            del r['currency']
        attach_financial_analysis(state, data)
        hypotheses = update_hypotheses(state)
        self.assertTrue(all(h['judgment'] == 'open' for h in hypotheses))

    def test_hypothesis_history_only_records_actual_changes(self):
        state = financial_state()
        hypotheses = update_hypotheses(state)
        before = copy.deepcopy(hypotheses)
        update_hypotheses(state)
        self.assertEqual(state.diagnostics['hypotheses'], before)

    def test_user_views_are_not_rewritten_by_financial_rules(self):
        state = financial_state()
        thesis = dict(id='user1', thesis='我关注现金流', invalidation='现金流恶化')
        state.diagnostics['agent']['stock_theses'] = [copy.deepcopy(thesis)]
        hypotheses = update_hypotheses(state)
        user = next(h for h in hypotheses if h['origin'] == 'user_view')
        self.assertEqual(user['judgment'], 'open')
        self.assertEqual(state.diagnostics['agent']['stock_theses'], [thesis])


class ReflectionTests(unittest.TestCase):
    def test_divergence_appends_margin_expense_structure_without_new_budget(self):
        state = financial_state()
        changes = reflect_plan(state)
        self.assertEqual(len(changes), 1)
        self.assertEqual({s.title for s in state.plan.steps}, {'收入与利润', '毛利率变化', '费用率变化', '业务结构变化'})
        self.assertEqual(state.diagnostics['agent']['budget'], 2)
        self.assertEqual(len(state.diagnostics['agent']['reflection_pending']), 3)
        self.assertTrue(all(s.evidence_strategy for s in state.plan.steps))

    def test_reflection_is_idempotent_and_respects_revision_limit(self):
        state = financial_state()
        reflect_plan(state)
        prior = len(state.plan.steps)
        self.assertEqual(reflect_plan(state), [])
        self.assertEqual(len(state.plan.steps), prior)
        another = financial_state()
        another.diagnostics['agent']['max_automatic_revisions'] = 0
        self.assertEqual(reflect_plan(another), [])

    @patch.dict(os.environ, {'TAVILY_API_KEY': 'fixture', 'OPENAI_API_KEY': ''})
    def test_agent_selects_new_financial_followups_and_stops_at_existing_budget(self):
        state = financial_state()
        first = choose_action(state)
        self.assertEqual(first['task'], '毛利率变化')
        state.diagnostics['agent']['queries'].append(first['query'])
        state.diagnostics['agent']['searches'] += 1
        second = choose_action(state)
        self.assertEqual(second['task'], '费用率变化')
        state.diagnostics['agent']['queries'].append(second['query'])
        state.diagnostics['agent']['searches'] += 1
        self.assertEqual(choose_action(state)['action'], 'finish')
        self.assertEqual(state.diagnostics['agent']['budget'], 2)

    def test_query_deduplication_normalizes_case_and_whitespace(self):
        state = financial_state()
        state.diagnostics['agent']['queries'] = ['Fixture   REVENUE']
        self.assertFalse(query_is_new(state, ' fixture revenue '))

    def test_search_attempt_cap_is_independent_of_success_budget(self):
        state = financial_state()
        state.diagnostics['agent']['search_attempts'] = 34
        self.assertEqual(choose_action(state)['action'], 'finish')

    @patch('src.agent.load_env')
    def test_iteration_cap_preserves_evidence_without_another_model_call(self, _):
        state = financial_state()
        state.diagnostics['agent']['iterations'] = 96
        with patch('src.agent.choose_action') as decision:
            tick(state)
            decision.assert_not_called()
        self.assertEqual(state.status, 'failed')
        self.assertTrue(state.documents)


class GraphCriticTests(unittest.TestCase):
    def report_state(self):
        state = financial_state()
        update_hypotheses(state)
        item = next(e for e in state.evidence if e.keep)
        state.synthesis = SynthesisBrief(state.topic, state.depth, evidence_index={'E1': item},
                                        key_findings=[GroundedFinding('需要核查财务质量', ['E1'])])
        state.report = ResearchReport(state.topic, state.depth, [ReportSection('结论', '需要核查财务质量 [E1]')])
        return state

    def test_graph_links_hypotheses_to_calculations_and_original_sources(self):
        state = self.report_state()
        graph = build_evidence_graph(state)
        self.assertEqual(graph['dangling_edges'], [])
        kinds = {n['kind'] for n in graph['nodes']}
        self.assertTrue({'conclusion', 'hypothesis', 'calculation', 'financial_input', 'source', 'evidence'} <= kinds)
        self.assertTrue(any(e['relation'] == 'opposed_by' for e in graph['edges']))
        self.assertTrue(any(e['relation'] == 'addresses' for e in graph['edges']))
        self.assertTrue(all(n['id'].startswith(state.run_id + ':') for n in graph['nodes']))

    def test_independent_critic_flags_uncited_opposing_financial_evidence(self):
        state = self.report_state()
        review = critic_review(state)
        self.assertTrue(review['passed'])
        self.assertTrue(review['warnings'])
        self.assertEqual(review['semantic_support'], 'unknown')

    def test_hypotheses_and_graph_round_trip_in_existing_sqlite_state(self):
        state = self.report_state()
        build_evidence_graph(state)
        with tempfile.TemporaryDirectory() as tmp:
            repo = ResearchRunRepository(Path(tmp) / 'state.db')
            repo.initialize()
            repo.save_state(state)
            restored = repo.get_state(state.run_id)
        self.assertEqual(restored.diagnostics['hypotheses'], state.diagnostics['hypotheses'])
        self.assertEqual(restored.diagnostics['evidence_graph'], state.diagnostics['evidence_graph'])

    def test_reasoning_ui_shows_actual_reflection_and_counterevidence(self):
        from streamlit.testing.v1 import AppTest
        code = ('from scripts.test_v2_autonomy import financial_state\n'
                'from src.research_reasoning import reflect_plan,build_evidence_graph\n'
                'from src.reasoning_ui import render_reasoning\ns=financial_state()\n'
                'reflect_plan(s)\nbuild_evidence_graph(s)\nrender_reasoning(s)')
        app = AppTest.from_string(code).run(timeout=20)
        self.assertFalse(app.exception)
        self.assertTrue(any('毛利率变化' in m.value for m in app.markdown))


if __name__ == '__main__':
    unittest.main()
