"""Frozen synthetic source bundles for conservative claim rules, not research IQ."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from src.claim_verification import verify_claims
from src.models import (EvidenceDocument, EvaluatedEvidence, ResearchDepth, ResearchReport,
                        ReportSection, Source, SynthesisBrief)

ROOT = Path(__file__).resolve().parents[1]


def case_inputs(case):
    evidence = {}
    for eid, record in case.get('evidence', {}).items():
        source = Source(record.get('title', 'Synthetic fixture'), record.get('url', 'https://example.invalid/filing'),
                        '', 'web', 1, source_id=eid.replace('E', 'S'),
                        published_date=record.get('date', '2026-01-01'))
        doc = EvidenceDocument(source, record['text'], len(record['text'].split()),
                               record.get('read_status', 'success'), snippet_fallback=record.get('snippet_fallback', False))
        evidence[eid] = EvaluatedEvidence(doc, 90, 90, 90, 90, 'Synthetic fixture', keep=record.get('keep', True))
    report = ResearchReport('Synthetic fixture', ResearchDepth.QUICK,
                            [ReportSection('结论', case['report'])])
    return report, SynthesisBrief('Synthetic fixture', ResearchDepth.QUICK, evidence_index=evidence)


def evaluate_dataset(path):
    content = Path(path).read_bytes()
    dataset = json.loads(content)
    cases = dataset['cases']
    if dataset.get('provenance') != 'synthetic_offline_fixture' or not cases:
        raise ValueError('Requires nonempty, explicitly synthetic source bundles')
    if len({c['id'] for c in cases}) != len(cases) or any(c['split'] not in {'development', 'heldout'} for c in cases):
        raise ValueError('Cases require unique IDs and explicit evaluation split')
    rows = []
    for case in cases:
        report, synthesis = case_inputs(case)
        check = verify_claims(report, synthesis)
        observed = [c['status'] for c in check['claims']]
        excerpts_valid = all(
            synthesis.evidence_index[r['evidence_id']].document.extracted_text[q['start']:q['end']] == q['text']
            for c in check['claims'] for r in c['references'] for q in r['excerpts'])
        rows.append({'id': case['id'], 'split': case['split'], 'expected': case['expected'],
                     'actual': observed, 'matched': observed == case['expected'] and excerpts_valid,
                     'excerpt_offsets_valid': excerpts_valid, 'verification': check})
    false_supports = sum(a == 'supported' and e != 'supported'
                         for row in rows for a, e in zip(row['actual'], row['expected']))
    return {'mode': 'offline', 'provenance': dataset['provenance'],
            'dataset_sha256': hashlib.sha256(content).hexdigest(), 'cases': len(rows),
            'matched_cases': sum(r['matched'] for r in rows), 'false_supports': false_supports,
            'splits': {split: {'cases': sum(r['split'] == split for r in rows),
                               'matched': sum(r['split'] == split and r['matched'] for r in rows)}
                       for split in ('development', 'heldout')},
            'statuses': dict(Counter(a for row in rows for a in row['actual'])),
            'limitations': ['Synthetic labels authored with the implementation; heldout is not an independent human benchmark.',
                            'Rule agreement and quote lineage only; not live research accuracy or general entailment.',
                            'No API calls, measured model costs, historical returns or search-policy evaluation.'],
            'results': rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', default=str(ROOT / 'evals' / 'claim_cases.json'))
    parser.add_argument('--output', default='artifacts/claim-evaluation.json')
    args = parser.parse_args(argv)
    result = evaluate_dataset(args.dataset)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{result["matched_cases"]}/{result["cases"]} claim-rule fixtures; false supports {result["false_supports"]}; {output}')
    for row in result['results']:
        if not row['matched']:
            print(f'FAIL {row["id"]}: expected {row["expected"]}, got {row["actual"]}')
    return 0 if result['matched_cases'] == result['cases'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
