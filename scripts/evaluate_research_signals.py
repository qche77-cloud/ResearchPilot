"""Replay a local research-signal experiment, never fetch or call paid APIs."""
import argparse
import json
from pathlib import Path

from src.research_signals import evaluate_experiment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', help='Explicit local experiment JSON, max 2 MB')
    parser.add_argument('--demo', action='store_true', help='Explicit fictional data; not an LLM evaluation')
    parser.add_argument('--as-of', default='2026-05-02')
    parser.add_argument('--rules', help='Optional explicit local rule JSON')
    parser.add_argument('--output', default='artifacts/research-signals-evaluation.json')
    args = parser.parse_args()
    if bool(args.input) == args.demo:
        parser.error('Choose exactly one of --demo or --input')
    if args.input and Path(args.input).stat().st_size > 2*1024*1024:
        parser.error('Experiment exceeds 2 MB')
    fixture_root = Path(__file__).resolve().parents[1] / 'evals'
    manifest = json.loads((fixture_root/'research_signal_cases.json').read_text(encoding='utf-8')) if args.demo else json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
    rules = json.loads(Path(args.rules).read_text(encoding='utf-8-sig')) if args.rules else None
    if isinstance(manifest,dict) and isinstance(manifest.get('replay'),dict):
        replay=manifest['replay']
        manifest=replay['manifest']
        rules=rules if rules is not None else replay['rules']
    result = evaluate_experiment(manifest,as_of=args.as_of,rules=rules)
    verification=None
    if args.demo and not args.rules and args.as_of=='2026-05-02':
        expected=json.loads((fixture_root/'research_signal_expectations.json').read_text(encoding='utf-8'))
        rows=result['rows']
        checks=[([r['score']['score'] for r in rows]==expected['scores']),
                ([r['label'] for r in rows]==expected['labels']),
                (result['all_methods_cohort']['case_ids']==expected['paired_case_ids'])]
        for method,key in [('baseline','baseline_confusion'),('rules','rules_confusion'),('agent','agent_fixture_confusion')]:
            actual=result['all_methods_cohort']['metrics'][method]
            checks.append(all(actual[k]==v for k,v in expected[key].items()))
        verification={'passed':sum(checks),'total':len(checks),'all_passed':all(checks)}
        if not all(checks):
            raise ValueError('Synthetic golden expectations did not match')
    target = Path(args.output)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    if verification is not None:
        target.with_suffix('.checks.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
    print(json.dumps({'id':result['id'],'provenance':result['provenance'],'cases':result['case_count'],
                      'paired_rule_cases':result['rule_baseline_cohort']['n'],
                      'paired_agent_cases':result['all_methods_cohort']['n'],
                      'fixture_expectations':verification,
                      'output':str(target)},ensure_ascii=False))


if __name__=='__main__':
    main()
