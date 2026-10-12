"""Evaluate fixed synthetic fixtures; no LLM, API key or production data required."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from src.verifier import evaluate_case

ROOT = Path(__file__).resolve().parents[1]


def evaluate_dataset(path):
    content = Path(path).read_bytes()
    dataset = json.loads(content)
    if dataset.get('provenance') != 'synthetic_offline_fixture':
        raise ValueError('This evaluator requires explicitly labeled offline fixtures')
    cases = dataset['cases']
    if not cases or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Dataset must have nonempty unique case IDs')
    rows = []
    tp = fp = fn = tn = 0
    citation_decisions = []
    numeric_decisions = []
    for case in cases:
        actual = evaluate_case(case)
        observed = {'passed': actual['passed'], 'issues': sorted({i['code'] for i in actual['issues']}),
                    'coverage': actual['coverage'], 'conflict_detected': actual['conflict_detected'],
                    'observations': [o['status'] for o in actual['observations']]}
        matched = observed == case['expected']
        citation_codes = {'missing_citation', 'invalid_citation', 'quote_mismatch'}
        citation_decisions.append(bool(set(observed['issues']) & citation_codes) == bool(set(case['expected']['issues']) & citation_codes))
        numeric_decisions.extend(a['status'] == e for a, e in zip(actual['observations'], case['expected']['observations']))
        truth, predicted = case['expected']['conflict_detected'], actual['conflict_detected']
        tp += bool(truth and predicted)
        fp += bool(not truth and predicted)
        fn += bool(truth and not predicted)
        tn += bool(not truth and not predicted)
        rows.append({'id': case['id'], 'scenario': case['scenario'], 'matched': matched,
                     'expected': case['expected'], 'actual': actual})
    return {'evaluated_at': datetime.now(timezone.utc).isoformat(), 'mode': 'offline',
            'provenance': dataset['provenance'], 'dataset_sha256': hashlib.sha256(content).hexdigest(),
            'dataset_as_of': dataset['as_of'], 'cases': len(cases),
            'matched_cases': sum(r['matched'] for r in rows),
            'scenarios': dict(Counter(c['scenario'] for c in cases)),
            'citation_integrity_decision_accuracy': sum(citation_decisions) / len(citation_decisions),
            'typed_numeric_decision_accuracy': sum(numeric_decisions) / len(numeric_decisions) if numeric_decisions else None,
            'typed_numeric_pairs': len(numeric_decisions),
            'coverage_by_case': {r['id']: r['actual']['coverage'] for r in rows},
            'conflict_detection': {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
                                   'precision': tp / (tp + fp) if tp + fp else None,
                                   'recall': tp / (tp + fn) if tp + fn else None},
            'semantic_support_unknown_cases': sum(r['actual']['semantic_support'] == 'unknown' for r in rows),
            'limitations': ['Synthetic fixtures measure deterministic checks, not live research quality.',
                            'Text conflict checks cover narrow same-metric direction/percentage patterns.',
                            'Counterevidence checks require explicit relation metadata.',
                            'No verified semantic entailment or real API/cost measurements.'],
            'results': rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', default=str(ROOT / 'evals' / 'agent_cases.json'))
    parser.add_argument('--output', default='artifacts/agent-evaluation.json')
    args = parser.parse_args(argv)
    report = evaluate_dataset(args.dataset)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{report["matched_cases"]}/{report["cases"]} expected fixture outcomes; {output}')
    for row in report['results']:
        if not row['matched']:
            print(f'FAIL {row["id"]}: {row["actual"]}')
    return 0 if report['matched_cases'] == report['cases'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
