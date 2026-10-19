"""Offline regression for known v2 integrity failures and trace persistence."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.request

from src.agent import create_agent, tick
from src.agent_chat import validate_citations
from src.models import (EvidenceDocument, EvaluatedEvidence, ResearchDepth, ResearchPlan,
                        ResearchPlanStep, ResearchReport, ReportSection, Source, SynthesisBrief)
from src.observability import estimate_cost, request_json, span, trace_scope, resolve_model
from src.pipeline import run_research
from src.research_state import research_state_to_json
from src.searcher import Searcher
from src.storage import ResearchRunRepository
from src.synthesizer import Synthesizer
from src.verifier import compare_observations, text_conflicts, verify_report
from src.writer import Writer, _sanitize_citations


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.plan = ResearchPlan('fixture', ResearchDepth.QUICK,
                                 [ResearchPlanStep(1, 'revenue', 'check disclosure', ['fixture revenue'])])

    @patch('src.searcher.load_env')
    @patch.dict(os.environ, {'TAVILY_API_KEY': ''})
    def test_missing_search_config_has_no_simulated_sources(self, _):
        searcher = Searcher()
        self.assertEqual(searcher.search(self.plan), [])
        self.assertEqual(searcher.last_diagnostics['mode'], 'unavailable')

    @patch('src.searcher.load_env')
    @patch.dict(os.environ, {'TAVILY_API_KEY': 'fixture'})
    def test_search_service_failure_has_no_simulated_sources(self, _):
        searcher = Searcher()
        with patch.object(searcher, '_tavily_multi_query_search', side_effect=RuntimeError('sensitive body')):
            self.assertEqual(searcher.search(self.plan), [])
        self.assertNotIn('sensitive body', searcher.last_warning)

    @patch('src.searcher.load_env')
    @patch.dict(os.environ, {'TAVILY_API_KEY': 'fixture'})
    def test_empty_search_has_no_simulated_sources(self, _):
        searcher = Searcher()
        with patch.object(searcher, '_tavily_multi_query_search', return_value=[]):
            self.assertEqual(searcher.search(self.plan), [])
        self.assertEqual(searcher.last_diagnostics['mode'], 'no_results')

    def test_direction_conflict_with_real_quote_is_blocked(self):
        result = validate_citations({'action': 'answer', 'answer': 'Revenue increased 10% [E1]',
                                    'supports': {'E1': 'Revenue decreased 10%'}},
                                   {'E1': {'text': 'Revenue decreased 10%.'}})
        self.assertTrue(result['citation_rejected'])
        self.assertEqual(result['verification']['issues'][0]['code'], 'direction_conflict')

    def test_percentage_mismatch_is_blocked(self):
        self.assertIn('numeric_mismatch', text_conflicts('收入增长50%', '收入增长10%'))

    def test_period_mismatch_is_unknown(self):
        self.assertEqual(text_conflicts('2025年营收增长10%', '2024年营收下降10%'), [])
        self.assertEqual(text_conflicts('Q1 Revenue increased 10%', 'Q2 Revenue decreased 10%'), [])
        self.assertEqual(text_conflicts('营收同比增长10%', '营收环比下降10%'), [])

    def test_ambiguous_or_forecast_direction_is_unknown(self):
        self.assertEqual(text_conflicts('Revenue may grow 50%', 'Revenue decreased 10%'), [])
        self.assertEqual(text_conflicts('Revenue increased 50%', 'Revenue increased 10% and profit declined 20%'), [])

    def test_uncited_metric_assertion_is_blocked(self):
        result = validate_citations({'action': 'answer', 'answer': 'Revenue increased 50%'}, {})
        self.assertTrue(result['citation_rejected'])

    def test_uncited_meta_and_research_requests_are_allowed(self):
        self.assertNotIn('citation_rejected', validate_citations({'action': 'answer', 'answer': 'Evidence is insufficient to confirm revenue growth'}, {}))
        self.assertNotIn('citation_rejected', validate_citations({'action': 'research', 'answer': 'Check revenue growth'}, {}))

    def test_valid_quote_keeps_semantics_unknown(self):
        result = validate_citations({'action': 'answer', 'answer': 'Revenue increased 10% [E1]',
                                    'supports': {'E1': 'Revenue increased 10%'}},
                                   {'E1': {'text': 'Revenue increased 10%.'}})
        self.assertNotIn('citation_rejected', result)
        self.assertEqual(result['verification']['semantic_support'], 'unknown')

    def test_writer_rejects_unknown_id_instead_of_erasing_it(self):
        with self.assertRaises(RuntimeError):
            _sanitize_citations('Revenue increased 50% [E99]', {'E1'})
        self.assertEqual(_sanitize_citations('Revenue increased 10% [e1]', {'E1'}), 'Revenue increased 10% [E1]')
        with self.assertRaises(RuntimeError):
            _sanitize_citations('Revenue increased 10% [Ebad]', {'E1'})

    def test_final_report_is_verified(self):
        doc = EvidenceDocument(Source('fixture', 'https://example.invalid/fixture', '', 'web', 1), 'Revenue decreased 10%.', 3, 'success')
        item = EvaluatedEvidence(doc, 90, 90, 90, 90, 'fixture')
        synthesis = SynthesisBrief('fixture', ResearchDepth.QUICK, evidence_index={'E1': item})
        report = ResearchReport('fixture', ResearchDepth.QUICK, [ReportSection('结论', 'Revenue increased 10% [E1]')])
        self.assertFalse(verify_report(report, synthesis)['passed'])
        with self.assertRaises(RuntimeError):
            Writer()._report_from_llm_json(self.plan, synthesis, {'sections': [{'title': '结论', 'content': 'Revenue increased 10% [E1]'}]})

    @patch('src.synthesizer.load_env')
    @patch.dict(os.environ, {'OPENAI_API_KEY': ''})
    def test_rejected_evidence_is_not_reintroduced(self, _):
        doc = EvidenceDocument(Source('fixture', 'https://example.invalid', '', 'web', 1), 'rejected', 1, 'success')
        rejected = EvaluatedEvidence(doc, 0, 0, 0, 0, 'rejected', keep=False)
        self.assertEqual(Synthesizer().synthesize(self.plan, [rejected]).evidence_index, {})

    def test_pipeline_without_evidence_fails_before_model_synthesis(self):
        from scripts.test_v13_pipeline_state import _offline_components, _patch_pipeline
        components = _offline_components(followup_sources=[], search_mode='unavailable')
        components['Searcher'].return_value.search.side_effect = lambda plan: []
        with _patch_pipeline(components):
            with self.assertRaises(ValueError):
                run_research('fixture', ResearchDepth.QUICK)
        components['Synthesizer'].return_value.synthesize.assert_not_called()

    def fact(self, **changes):
        return dict(entity='fixture', metric='revenue', period='2025-Q1', currency='CNY', unit='yuan', basis='single_quarter', value='100', **changes)

    def test_typed_numbers_are_exact_decimal(self):
        a, b = self.fact(), self.fact()
        b['value'] = '100.000'
        self.assertEqual(compare_observations(a, b)['status'], 'consistent')
        b['value'] = '101'
        self.assertEqual(compare_observations(a, b)['status'], 'conflict')

    def test_incompatible_financial_scope_is_not_a_conflict(self):
        for key, value in [('period', '2024-Q1'), ('currency', 'USD'), ('unit', 'million_yuan'), ('basis', 'cumulative'), ('entity', 'other')]:
            a, b = self.fact(), self.fact()
            b[key] = value
            self.assertEqual(compare_observations(a, b)['status'], 'unknown')

    def test_invalid_numbers_are_unknown(self):
        for value in ('NaN', 'Infinity', 'not-a-number', None):
            a, b = self.fact(), self.fact()
            b['value'] = value
            self.assertEqual(compare_observations(a, b)['status'], 'unknown')


class TraceTests(unittest.TestCase):
    @patch.dict(os.environ, {'RESEARCHPILOT_STRICT_OUTPUTS': '1'})
    def test_optional_strict_decision_schema_is_applied_without_changing_other_roles(self):
        opener = MagicMock()
        opener.return_value.__enter__.return_value.read.return_value = b'{}'
        for role in ('agent.decide', 'writer.generate'):
            request = urllib.request.Request('https://example.invalid', data=b'{"model":"fixture-model","response_format":{"type":"json_object"}}')
            request_json(request, timeout=1, opener=opener, operation=role)
            response_format = json.loads(request.data)['response_format']
            self.assertEqual(response_format['type'], 'json_schema' if role == 'agent.decide' else 'json_object')
            if role == 'agent.decide':
                self.assertFalse(response_format['json_schema']['schema']['additionalProperties'])
                self.assertTrue(response_format['json_schema']['strict'])
    @patch.dict(os.environ, {'RESEARCHPILOT_MODEL_ROUTES_JSON': '{"planner":"fixture-small","writer.generate":"fixture-writer"}'})
    def test_explicit_model_routes_preserve_default_and_allow_operation_override(self):
        self.assertEqual(resolve_model('planner.focus', 'fixture-default'), ('fixture-small', 'explicit_role_route'))
        self.assertEqual(resolve_model('writer.generate', 'fixture-default'), ('fixture-writer', 'explicit_role_route'))
        self.assertEqual(resolve_model('chat.answer', 'fixture-default'), ('fixture-default', 'default_model'))

    def test_invalid_model_routes_do_not_corrupt_existing_requests(self):
        for raw in ('not json', '[]', '{"planner":42}', '{"planner":"bad model name"}'):
            with patch.dict(os.environ, {'RESEARCHPILOT_MODEL_ROUTES_JSON': raw}):
                self.assertEqual(resolve_model('planner.generate', 'fixture-default')[0], 'fixture-default')

    @patch.dict(os.environ, {'RESEARCHPILOT_MODEL_ROUTES_JSON': '{"planner":"fixture-small"}'})
    def test_transport_records_actual_routed_model_without_an_extra_call(self):
        state = create_agent('fixture')
        request = urllib.request.Request('https://example.invalid', data=b'{"model":"fixture-default"}')
        opener = MagicMock()
        opener.return_value.__enter__.return_value.read.return_value = b'{}'
        with trace_scope(state):
            request_json(request, timeout=1, opener=opener, operation='planner.generate')
        self.assertEqual(json.loads(request.data)['model'], 'fixture-small')
        self.assertEqual(state.diagnostics['trace'][0]['model'], 'fixture-small')
        opener.assert_called_once()

    def usage(self):
        return dict(prompt_tokens=100, completion_tokens=20, total_tokens=120, cached_tokens=40)

    def pricing(self):
        return {'fixture-model': {'input_per_million': '1', 'output_per_million': '2',
                                  'cached_input_per_million': '.5', 'as_of': '2026-10-12'}}

    def test_cached_cost_is_deterministic_and_missing_rates_are_unknown(self):
        cost = estimate_cost('fixture-model', self.usage(), self.pricing())
        self.assertEqual(cost['amount'], '0.00012')
        self.assertIsNone(estimate_cost('unknown', self.usage(), self.pricing()))
        self.assertIsNone(estimate_cost('fixture-model', None, self.pricing()))

    def test_missing_cached_rate_is_not_assumed(self):
        pricing = self.pricing()
        del pricing['fixture-model']['cached_input_per_million']
        self.assertIsNone(estimate_cost('fixture-model', self.usage(), pricing))

    def test_unknown_cache_breakdown_and_invalid_rate_date_are_not_guessed(self):
        usage = self.usage()
        usage['cached_tokens'] = None
        self.assertIsNone(estimate_cost('fixture-model', usage, self.pricing()))
        pricing = self.pricing()
        pricing['fixture-model']['as_of'] = 'unknown'
        self.assertIsNone(estimate_cost('fixture-model', self.usage(), pricing))

    def test_response_usage_is_persisted_without_payload_secrets(self):
        state = create_agent('fixture')
        opener = MagicMock()
        usage = dict(prompt_tokens=100, completion_tokens=20, total_tokens=120,
                     prompt_tokens_details={'cached_tokens': 40})
        opener.return_value.__enter__.return_value.read.return_value = json.dumps({'usage': usage}).encode()
        request = urllib.request.Request('https://example.invalid', data=json.dumps({'model': 'fixture-model', 'messages': ['private prompt']}).encode(), headers={'Authorization': 'Bearer private-key'})
        with patch.dict(os.environ, {'RESEARCHPILOT_MODEL_PRICING_JSON': json.dumps(self.pricing())}), trace_scope(state), span('step', 'fixture'):
            request_json(request, timeout=1, opener=opener, operation='fixture')
        serialized = research_state_to_json(state)
        self.assertNotIn('private prompt', serialized)
        self.assertNotIn('private-key', serialized)
        self.assertEqual(state.diagnostics['trace_summary']['known_total_tokens'], 120)
        self.assertEqual(state.diagnostics['trace_summary']['total_model_cost_usd'], '0.00012')
        with tempfile.TemporaryDirectory() as tmp:
            repo = ResearchRunRepository(Path(tmp) / 'fixture.db')
            repo.initialize()
            repo.save_state(state)
            restored = repo.get_state(state.run_id)
            self.assertEqual(restored.diagnostics['trace'], state.diagnostics['trace'])

    def test_transport_error_is_traced_and_not_logged_verbatim(self):
        state = create_agent('fixture')
        request = urllib.request.Request('https://example.invalid', data=b'{"model":"fixture-model"}')
        with trace_scope(state), self.assertRaises(RuntimeError):
            request_json(request, timeout=1, opener=MagicMock(side_effect=RuntimeError('private response')), operation='fixture')
        self.assertEqual(state.diagnostics['trace'][0]['status'], 'error')
        self.assertNotIn('private response', research_state_to_json(state))
        self.assertIsNone(state.diagnostics['trace_summary']['total_model_cost_usd'])

    def test_missing_or_invalid_usage_never_becomes_zero_cost(self):
        for response in ({}, {'usage': {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 99}}):
            state = create_agent('fixture')
            opener = MagicMock()
            opener.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            with trace_scope(state):
                request_json(urllib.request.Request('https://example.invalid', data=b'{"model":"fixture-model"}'), timeout=1, opener=opener, operation='fixture')
            self.assertEqual(state.diagnostics['trace_summary']['unknown_usage_calls'], 1)
            self.assertIsNone(state.diagnostics['trace_summary']['total_model_cost_usd'])

    @patch('src.agent.load_env')
    def test_agent_tick_produces_a_persistable_step_trace(self, _):
        state = create_agent('fixture')
        state.plan = ResearchPlan('fixture', state.depth)
        state.diagnostics['agent']['searches'] = state.diagnostics['agent']['budget']
        tick(state)
        self.assertEqual(state.diagnostics['trace'][0]['operation'], 'agent.tick')
        self.assertNotEqual(state.diagnostics['trace'][0]['status'], 'running')

    def test_parallel_scopes_do_not_mix_runs(self):
        import threading
        first, second = create_agent('one'), create_agent('two')
        barrier = threading.Barrier(2)
        def worker(state):
            with trace_scope(state), span('tool', 'fixture'):
                barrier.wait(timeout=3)
        threads = [threading.Thread(target=worker, args=(s,)) for s in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        for state in (first, second):
            self.assertEqual([r['run_id'] for r in state.diagnostics['trace']], [state.run_id])


class BackgroundRecoveryTests(unittest.TestCase):
    def setUp(self):
        from src.background import Runner
        from src.workbench import Workbench
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = ResearchRunRepository(Path(self.tmp.name) / 'research.db')
        self.repo.initialize()
        self.store = Workbench(Path(self.tmp.name) / 'workbench.db')
        with patch('src.background.ResearchRunRepository', return_value=self.repo), patch('src.background.Workbench', return_value=self.store):
            self.runner = Runner()
        self.state = create_agent('fixture')
        self.repo.save_state(self.state)

    def test_repeated_save_failure_does_not_escape_or_ack_command(self):
        self.store.enqueue(self.state.run_id, 'resume')
        with patch.object(self.repo, 'save_state', side_effect=OSError('private filesystem detail')):
            self.runner._run(self.state.run_id)
        self.assertEqual(len(self.store.pending(self.state.run_id)), 1)
        restored, active = self.runner.read(self.state.run_id)
        self.assertFalse(active)
        self.assertEqual(restored.status, 'failed')
        self.assertIn('OSError', restored.error)
        self.assertNotIn('private filesystem detail', restored.error)

    def test_initial_read_failure_is_captured(self):
        with patch.object(self.repo, 'get_state', side_effect=OSError('private filesystem detail')):
            self.runner._run(self.state.run_id)
        self.assertIn(self.state.run_id, self.runner.worker_errors)

    def test_paused_run_resumes_from_persisted_stage_without_replanning(self):
        self.state.current_stage = 'reading'
        self.state.mark_running('reading')
        self.repo.save_state(self.state)
        self.store.enqueue(self.state.run_id, 'pause')
        with patch('src.background.tick') as tool:
            self.runner._run(self.state.run_id)
            tool.assert_not_called()
        self.store.enqueue(self.state.run_id, 'resume')
        def finish(state, *, store):
            self.assertIs(store, self.store)
            self.assertEqual(state.current_stage, 'reading')
            state.mark_completed()
        with patch('src.background.tick', side_effect=finish) as tool:
            self.runner._run(self.state.run_id)
            tool.assert_called_once()
        self.assertEqual(self.repo.get_state(self.state.run_id).status, 'completed')

    def test_committed_command_replay_is_acknowledged_without_second_model_call(self):
        self.store.enqueue(self.state.run_id, 'chat', 'fixture')
        command = self.store.pending(self.state.run_id)[0]
        self.state.diagnostics['agent']['processed_commands'] = [command['id']]
        self.repo.save_state(self.state)
        with patch('src.background.respond') as model:
            self.runner._run(self.state.run_id)
            model.assert_not_called()
        self.assertEqual(self.store.pending(self.state.run_id), [])


class EvaluationTests(unittest.TestCase):
    def test_synthetic_dataset_has_four_scenarios_and_expected_outcomes(self):
        from scripts.evaluate_agent import ROOT, evaluate_dataset
        report = evaluate_dataset(ROOT / 'evals' / 'agent_cases.json')
        self.assertEqual(report['cases'], 16)
        self.assertEqual(report['matched_cases'], 16)
        self.assertEqual(report['scenarios'], {'industry': 4, 'company': 4, 'finance': 4, 'conflict': 4})
        self.assertEqual(report['semantic_support_unknown_cases'], 16)

    def test_corrupted_expected_result_is_not_reported_as_success(self):
        from scripts.evaluate_agent import ROOT, evaluate_dataset
        dataset = json.loads((ROOT / 'evals' / 'agent_cases.json').read_text(encoding='utf-8'))
        dataset['cases'][0]['expected']['coverage'] = 0
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'corrupted.json'
            path.write_text(json.dumps(dataset), encoding='utf-8')
            self.assertEqual(evaluate_dataset(path)['matched_cases'], 15)

    def test_trace_ui_discloses_missing_cost_instead_of_showing_free_research(self):
        from streamlit.testing.v1 import AppTest
        source = ('from src.agent import create_agent\nfrom src.observability import trace_scope, span\n'
                  'from src.trace_ui import render_trace\ns=create_agent("fixture")\n'
                  'with trace_scope(s), span("model", "fixture"):\n    pass\nrender_trace(s)')
        app = AppTest.from_string(source).run(timeout=15)
        self.assertFalse(app.exception)
        self.assertTrue(any('费用未知' in c.value for c in app.caption))


class TransportIntegrationTests(unittest.TestCase):
    """Exercise real business components, substituting only external I/O."""
    def transports(self, state):
        from src.reader import _FetchMeta
        text = 'Fixture revenue increased 10%. ' * 30
        html = '<html><body><article><p>' + text + '</p></article></body></html>'

        def opener(request, timeout):
            operation = state.diagnostics['trace'][-1]['operation']
            if operation == 'tavily.search':
                data = {'results': [{'title': 'Fixture revenue annual report', 'url': 'https://example.invalid/fixture-report',
                                      'content': text, 'score': .95, 'published_date': '2026-10-01'}]}
            else:
                if operation == 'planner.generate':
                    content = {'research_objective': 'Check fixture revenue', 'tasks': [
                        {'title': name, 'description': 'Read original fixture report', 'search_queries': ['Fixture ' + name]}
                        for name in ('Revenue', 'Cash flow', 'Risks')]}
                elif operation == 'planner.focus':
                    content = {'objective': 'Check fixture revenue', 'steps': [
                        {'question': name, 'criterion': 'Read original fixture report', 'queries': ['Fixture ' + name]}
                        for name in ('Revenue', 'Cash flow', 'Risks')]}
                elif operation == 'agent.decide':
                    content = {'action': 'finish', 'reason': 'Fixture sources collected'} if state.documents else {
                        'action': 'search', 'task': 'Revenue', 'query': 'Fixture Revenue', 'reason': 'Check fixture original'}
                elif operation == 'synthesizer.generate':
                    content = {'key_findings': [{'finding': 'Fixture revenue increased 10%', 'evidence_ids': ['E1'],
                                                'candidate_excerpts': [{'evidence_id': 'E1', 'excerpt': 'Fixture revenue increased 10%.'}]}]}
                elif operation == 'writer.generate':
                    content = {'sections': [{'title': '核心结论', 'content': 'Fixture revenue increased 10% [E1]'}]}
                else:
                    raise AssertionError('Unexpected model/tool operation: ' + operation)
                data = {'choices': [{'message': {'content': json.dumps(content)}}],
                        'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120,
                                  'prompt_tokens_details': {'cached_tokens': 0}}}
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(data).encode()
            return response

        fetch = lambda url: _FetchMeta(html=html, http_status=200, content_type='text/html', encoding='utf-8')
        return opener, fetch

    @patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-key', 'TAVILY_API_KEY': 'fixture-key', 'LLM_MODEL': 'fixture-model'})
    def test_pipeline_real_components_with_fixture_http(self):
        from src.reader import Reader
        from src.research_state import ResearchState
        state = ResearchState(topic='Fixture revenue', depth=ResearchDepth.QUICK)
        opener, fetch = self.transports(state)
        with patch('urllib.request.urlopen', side_effect=opener), patch.object(Reader, '_fetch', side_effect=fetch):
            result = run_research(state.topic, state.depth, research_state=state)
        self.assertEqual(state.status, 'completed')
        self.assertEqual(result.report.writer_source, 'llm')
        self.assertEqual(result.synthesis.synthesizer_source, 'llm')
        self.assertTrue(state.diagnostics['verification']['passed'])
        self.assertEqual(state.diagnostics['trace_summary']['model_calls'], 3)
        self.assertEqual(state.diagnostics['trace_summary']['known_total_tokens'], 360)

    @patch.dict(os.environ, {'OPENAI_API_KEY': 'fixture-key', 'TAVILY_API_KEY': 'fixture-key', 'LLM_MODEL': 'fixture-model'})
    def test_agent_real_components_with_fixture_http(self):
        from src.reader import Reader
        state = create_agent('Fixture revenue')
        opener, fetch = self.transports(state)
        with patch('urllib.request.urlopen', side_effect=opener), patch.object(Reader, '_fetch', side_effect=fetch):
            for _ in range(12):
                tick(state)
                if state.status in {'completed', 'failed'}:
                    break
        self.assertEqual(state.status, 'completed', state.error)
        self.assertIsNotNone(state.research_health)
        self.assertEqual(state.report.writer_source, 'llm')
        self.assertTrue(state.diagnostics['verification']['passed'])
        self.assertGreaterEqual(state.diagnostics['trace_summary']['model_calls'], 5)
        self.assertTrue(all(s.evidence_strategy for s in state.plan.steps))


if __name__ == '__main__':
    unittest.main()
