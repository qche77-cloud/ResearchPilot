"""Claim attribution, abstention, lineage, snapshots and pipeline integration."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.evaluate_claims import ROOT, case_inputs, evaluate_dataset
from src.claim_verification import verify_claims
from src.models import ReportSection
from src.report_links import snapshot_report
from src.research_reasoning import build_evidence_graph, critic_review
from src.research_state import ResearchState
from src.storage import ResearchRunRepository
from src.studio_bridge import run_view
from src.verifier import verify_report


def fixture(text='2025年甲公司营收同比增长10%。', report='2025年甲公司营收同比增长10% [E1]。'):
    return case_inputs({'report': report, 'evidence': {'E1': {'text': text}}})


def state_fixture():
    report, synthesis = fixture()
    return ResearchState(topic=report.topic, depth=report.depth, report=report, synthesis=synthesis)


class ClaimTests(unittest.TestCase):
    def test_frozen_dataset_and_excerpts(self):
        result = evaluate_dataset(ROOT / 'evals' / 'claim_cases.json')
        self.assertEqual(result['cases'], 32)
        self.assertEqual(result['matched_cases'], 32)
        self.assertEqual(result['false_supports'], 0)
        self.assertEqual(result['splits']['heldout']['matched'], 16)

    def test_general_semantic_support_stays_unknown_even_on_exact_match(self):
        check = verify_report(*fixture())
        self.assertTrue(check['passed'])
        self.assertTrue(check['all_claims_matched'])
        self.assertEqual(check['semantic_support'], 'unknown')
        self.assertEqual(check['claims'][0]['semantic_support'], 'verbatim_only')
        self.assertEqual(check['passed_scope'], 'citation_integrity_and_narrow_conflicts')

    def test_missing_support_is_not_integrity_pass_as_semantic_success(self):
        report, synthesis = fixture(report='甲公司已形成长期竞争优势 [E1]。')
        check = verify_report(report, synthesis)
        self.assertTrue(check['passed'])
        self.assertFalse(check['all_claims_matched'])
        self.assertEqual(check['claims'][0]['status'], 'insufficient_evidence')

    def test_other_entity_in_document_does_not_block_report(self):
        report, synthesis = fixture(text='2025年乙公司营收同比下降10%。')
        check = verify_report(report, synthesis)
        self.assertTrue(check['passed'])
        self.assertFalse(check['all_claims_matched'])

    def test_same_scope_numeric_conflict_blocks_report(self):
        report, synthesis = fixture(text='2025年甲公司营收同比下降10%。')
        check = verify_report(report, synthesis)
        self.assertFalse(check['passed'])
        self.assertEqual(check['sections'][0]['issues'][0]['code'], 'direction_conflict')

    def test_mixed_document_is_visible_without_a_false_single_direction(self):
        report, synthesis = fixture(text='2025年甲公司营收同比增长10%。2025年甲公司营收同比下降10%。')
        check = verify_report(report, synthesis)
        self.assertTrue(check['passed'])
        self.assertEqual(check['claims'][0]['status'], 'mixed')

    def test_quotes_resolve_original_offsets_not_reconstructed_text(self):
        text = '来源说明。\n2025年甲公司营收同比增长10%。\n附录。'
        check = verify_claims(*fixture(text=text))
        reference = check['claims'][0]['references'][0]
        self.assertEqual(reference['source_id'], 'S1')
        self.assertEqual(reference['published_at'], '2026-01-01')
        for quote in reference['excerpts']:
            self.assertEqual(text[quote['start']:quote['end']], quote['text'])
            self.assertEqual(quote['relation'], 'supports')

    def test_claim_ids_stable_and_change_with_report(self):
        report, synthesis = fixture()
        first = verify_claims(report, synthesis)
        self.assertEqual(first, verify_claims(report, synthesis))
        report.sections[0].content = '需要更多资料 [E1]。'
        self.assertNotEqual(first['claims'][0]['id'], verify_claims(report, synthesis)['claims'][0]['id'])

    def test_no_claims_cannot_be_all_matched(self):
        report, synthesis = fixture()
        report.sections = [ReportSection('Sources', '[E1]')]
        result = verify_claims(report, synthesis)
        self.assertEqual(result['claim_summary']['total'], 0)
        self.assertIsNone(result['claim_summary']['statement_match_rate'])
        self.assertFalse(result['all_claims_matched'])

    def test_listing_source_is_not_verified_disclosure(self):
        report, synthesis = fixture()
        synthesis.evidence_index['E1'].document.source.url = 'https://data.eastmoney.com/notices/stock/002837.html'
        from src.stock_research import is_listing_source
        self.assertTrue(is_listing_source(synthesis.evidence_index['E1'].source.url))
        self.assertFalse(verify_claims(report, synthesis)['all_claims_matched'])

    def test_compound_different_metrics_abstains_on_partial_quote(self):
        report, synthesis = fixture(report='2025年甲公司营收同比增长10%，利润同比增长20% [E1]。')
        self.assertEqual(verify_claims(report, synthesis)['claims'][0]['status'], 'insufficient_evidence')

    def test_negation_and_forecast_not_silently_removed(self):
        for prefix in ('预计', '不能确认', '并非'):
            self.assertFalse(verify_claims(*fixture(text=prefix+'2025年甲公司营收同比增长10%。'))['all_claims_matched'])

    def test_snapshot_recomputes_exact_version_and_preserves_old_verdict(self):
        state = state_fixture()
        state.diagnostics['verification'] = {'claims': ['stale unrelated verification']}
        old_version = snapshot_report(state)
        old = copy.deepcopy(state.diagnostics['agent']['report_versions'][old_version])
        state.synthesis.evidence_index['E1'].document.extracted_text = '2025年甲公司营收同比下降10%。'
        new_version = snapshot_report(state)
        self.assertNotEqual(old_version, new_version)
        self.assertEqual(old, state.diagnostics['agent']['report_versions'][old_version])
        self.assertEqual(old['verification']['claims'][0]['status'], 'supported')
        latest = state.diagnostics['agent']['report_versions'][new_version]
        self.assertEqual(latest['verification']['claims'][0]['status'], 'contradicted')
        self.assertEqual(snapshot_report(state), new_version)

    def test_legacy_version_is_not_backfilled_by_render(self):
        state = state_fixture()
        state.diagnostics['agent'] = {'report_versions': {'legacy': {'sections': [], 'evidence': {}, 'findings': []}}}
        before = copy.deepcopy(state.diagnostics)
        view = run_view(state)
        self.assertNotIn('verification', view['versions']['legacy'])
        self.assertEqual(before, state.diagnostics)

    def test_critic_reports_unknown_claims_without_deleting_report(self):
        state = state_fixture()
        state.report.sections[0].content = '甲公司盈利能力持续增强 [E1]。'
        review = critic_review(state)
        self.assertTrue(review['passed'])
        self.assertTrue(any(w['code'] == 'claim_support_unresolved' for w in review['warnings']))
        self.assertIsNotNone(state.report)

    def test_graph_claim_edges_have_actual_excerpts_and_conservative_relations(self):
        state = state_fixture()
        state.documents = [state.synthesis.evidence_index['E1'].document]
        graph = build_evidence_graph(state)
        self.assertFalse(graph['dangling_edges'])
        self.assertTrue(any(n['kind'] == 'report_claim' and n['status'] == 'supported' for n in graph['nodes']))
        edges = [e for e in graph['edges'] if e['relation'] == 'matches_statement']
        self.assertEqual(len(edges), 1)
        self.assertTrue(edges[0]['excerpts'])

    def test_verification_and_version_round_trip_existing_sqlite(self):
        state = state_fixture()
        state.diagnostics['verification'] = verify_report(state.report, state.synthesis)
        snapshot_report(state)
        with tempfile.TemporaryDirectory() as tmp:
            repo = ResearchRunRepository(Path(tmp) / 'fixture.db')
            repo.initialize()
            repo.save_state(state)
            restored = repo.get_state(state.run_id)
        self.assertEqual(restored.diagnostics, state.diagnostics)

    def test_evaluation_rejects_empty_or_unlabeled_bundles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'bad.json'
            for data in ({'cases': []}, {'provenance': 'real', 'cases': [{'id': 'x'}]}):
                path.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaises(ValueError):
                    evaluate_dataset(path)


if __name__ == '__main__':
    unittest.main()
