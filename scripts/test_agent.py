"""Offline regression for resumable agent control and budget enforcement."""
import os
import unittest
from unittest.mock import patch

from src.agent import create_agent, choose_action, steer, tick
from src.agent_quality import focus_plan, evidence_gaps
from src.models import ResearchPlan, ResearchPlanStep, Source, EvidenceDocument
from src.storage import ResearchRunRepository
from tempfile import TemporaryDirectory
from pathlib import Path


class AgentTests(unittest.TestCase):
    def state(self):
        s = create_agent('液冷', 2)
        s.plan = ResearchPlan(s.topic, s.depth, [ResearchPlanStep(1, '收入', '核查收入', ['液冷 收入 公告'])])
        return s

    def test_budget(self):
        s = self.state()
        s.diagnostics['agent']['searches'] = 2
        self.assertEqual(choose_action(s)['action'], 'finish')

    def test_specific_missing_evidence(self):
        s = self.state()
        self.assertEqual(evidence_gaps(s)[0]['issue'], '尚无来源')
        source = Source('摘要', 'https://example.com', '', 'web', 1, research_task='收入')
        s.documents = [EvidenceDocument(source, '摘要', 2, 'fallback')]
        issues = [g['issue'] for g in evidence_gaps(s)]
        self.assertTrue(any('正文' in x for x in issues))
        self.assertTrue(any('日期未知' in x for x in issues))

    @patch.dict(os.environ, {'OPENAI_API_KEY': 'test'})
    @patch('src.agent_quality.urllib.request.urlopen')
    def test_goal_plan_validated(self, request):
        import json
        s = self.state()
        data = {'objective': '核实收入兑现', 'steps': [
            {'question': q, 'criterion': '查原始年报并统一期间', 'queries': [q + ' 年报']}
            for q in ['实际收入', '利润贡献', '已交付订单']]}
        request.return_value.__enter__.return_value.read.return_value = json.dumps(
            {'choices': [{'message': {'content': json.dumps(data)}}]}).encode()
        focus_plan(s)
        self.assertEqual(len(s.plan.steps), 3)
        self.assertEqual(s.plan.research_objective, '核实收入兑现')
        self.assertIn('统一期间', s.plan.steps[0].description)

    def test_repeated_empty_search_stops(self):
        s = self.state()
        s.diagnostics['agent']['empty_searches'] = 2
        self.assertEqual(choose_action(s)['action'], 'finish')

    @patch('src.agent.load_env')
    def test_no_evidence_never_delivered(self, _):
        s = self.state()
        s.diagnostics['agent']['searches'] = 2
        tick(s)
        self.assertEqual(s.status, 'failed')
        self.assertIsNone(s.report)

    @patch.dict(os.environ, {'OPENAI_API_KEY': ''})
    def test_fallback_and_steering(self):
        s = self.state()
        self.assertEqual(choose_action(s)['query'], '液冷 收入 公告')
        steer(s, '只看年报')
        self.assertIn('只看年报', choose_action(s)['query'])

    @patch('src.agent.load_env')
    @patch.dict(os.environ, {'TAVILY_API_KEY': 'test', 'OPENAI_API_KEY': ''})
    def test_service_failure_is_not_empty_result(self, _):
        s = self.state()
        with patch('src.agent.Searcher') as cls:
            cls.return_value.followup_search.return_value = []
            cls.return_value.last_diagnostics = {'followup_executed_query_details': [{'error': 'network error'}]}
            tick(s)
        self.assertEqual(s.status, 'failed')
        self.assertEqual(s.diagnostics['agent']['empty_searches'], 0)
        self.assertEqual(s.diagnostics['agent']['queries'], [])
        self.assertEqual(s.diagnostics['agent']['searches'], 0)
        self.assertEqual(choose_action(s)['action'], 'search')
        self.assertIsNone(s.report)

    @patch('src.agent.load_env')
    def test_replanning_uses_new_goal_and_preserves_sources(self, _):
        s = self.state()
        source = Source('旧公告', 'https://example.com', '', 'web', 1)
        s.sources.append(source)
        steer(s, '改为核查公司现金流')
        self.assertEqual(s.current_stage, 'replanning')
        new_plan = ResearchPlan('现金流', s.depth, [ResearchPlanStep(1, '经营现金流', '核对现金流', ['现金流 年报'])])
        with patch('src.agent.Planner') as planner, patch('src.agent.focus_plan', return_value='focused'):
            planner.return_value.plan.return_value = new_plan
            tick(s)
            analyzed = planner.return_value.plan.call_args.args[0]
            self.assertIn('公司现金流', analyzed.raw_query)
        self.assertEqual(s.plan.steps[0].title, '经营现金流')
        self.assertEqual(s.sources, [source])
        self.assertEqual(s.diagnostics['agent']['searches'], 0)
        self.assertEqual(s.current_stage, 'deciding')

    @patch('src.agent.load_env')
    @patch.dict(os.environ, {'TAVILY_API_KEY': 'test', 'OPENAI_API_KEY': ''})
    def test_search_read_checkpoint(self, _):
        s = self.state()
        source = Source('公告', 'https://example.com/a', '收入', 'web', 1, source_id='S1', research_task='收入')
        with patch('src.agent.Searcher.followup_search', return_value=[source]):
            tick(s)
        self.assertEqual(s.current_stage, 'reading')
        self.assertEqual(s.diagnostics['agent']['searches'], 1)
        doc = EvidenceDocument(source=source, extracted_text='年报收入数据', word_count=6, read_status='success')
        with patch('src.agent.Reader.read', return_value=[doc]), patch('src.agent.EvidenceEvaluator.evaluate', return_value=[]):
            tick(s)
        self.assertEqual(s.current_stage, 'deciding')
        with TemporaryDirectory() as tmp:
            repo = ResearchRunRepository(Path(tmp) / 'test.db')
            repo.initialize()
            repo.save_state(s)
            restored = repo.get_state(s.run_id)
            self.assertEqual(restored.diagnostics['agent']['queries'], ['液冷 收入 公告'])
            self.assertEqual(len(restored.documents), 1)


if __name__ == '__main__':
    unittest.main()
