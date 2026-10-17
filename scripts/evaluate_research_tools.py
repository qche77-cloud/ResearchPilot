"""Fixed synthetic finance/criterion regression, no claim of investment accuracy."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from scripts.test_research_tools import research_fixture,test_spec
from src.financial_analysis import analyze_financials
from src.financial_diagnostics import research_diagnostics
from src.thesis_tracking import evaluate_test


def evaluate():
    rows=[]
    def finance(name,payload=None,cutoff='2026-04-01',options=None,expected=None):
        payload=payload or research_fixture();options=options or {}
        result=research_diagnostics(analyze_financials(payload,as_of=cutoff),**options)
        actual={'bridge':result['profit_bridge']['status'],'triggered':result['triggered_count'],'unavailable':result['unavailable_count']}
        rows.append({'id':name,'type':'financial','input':{'payload':payload,'as_of':cutoff,'options':options},
                     'expected':expected,'observed':actual,'matched':all(actual[k]==v for k,v in expected.items()),'result':result})
    finance('complete-accounting-bridge',expected={'bridge':'ok','triggered':7,'unavailable':0})
    missing=research_fixture();missing['financial_records']=[r for r in missing['financial_records'] if r['metric']!='net_profit']
    finance('cannot-substitute-attributable-profit',missing,expected={'bridge':'unavailable','triggered':6,'unavailable':1})
    missing=research_fixture();missing['financial_records']=[r for r in missing['financial_records'] if r['metric']!='expense']
    finance('unexplained-expenses-stay-visible',missing,expected={'bridge':'ok','triggered':7})
    finance('no-usd-inputs',options={'currency':'USD'},expected={'bridge':'unavailable','triggered':0,'unavailable':7})
    finance('no-parent-company-inputs',options={'scope':'parent_company'},expected={'bridge':'unavailable','triggered':0,'unavailable':7})
    finance('before-target-disclosure',cutoff='2026-03-01',options={'period_end':'2025-12-31'},expected={'bridge':'unavailable','triggered':0,'unavailable':7})
    finance('explicit-higher-margin-threshold',options={'thresholds':{'gross_margin_drop_pp':'20'}},expected={'bridge':'ok','triggered':6,'unavailable':0})
    negative=research_fixture();next(r for r in negative['financial_records'] if r['metric']=='inventory')['value']='-1'
    finance('invalid-negative-inventory',negative,expected={'bridge':'ok','triggered':6,'unavailable':1})
    def thesis(name,spec,cutoff,expected):
        payload=research_fixture();spec=dict(spec,symbol='002837')
        result=evaluate_test(spec,payload,as_of=cutoff)
        rows.append({'id':name,'type':'criterion','input':{'payload':payload,'spec':spec,'as_of':cutoff},'expected':expected,
                     'observed':result['status'],'matched':result['status']==expected,'result':result})
    thesis('criterion-met',test_spec(),'2026-04-01','criterion_met')
    spec=test_spec();spec['criteria'][0]['threshold']='30'
    thesis('criterion-not-met',spec,'2026-04-01','criterion_not_met')
    thesis('not-due',test_spec(),'2026-03-01','not_due')
    spec=test_spec();spec['review_on']='2026-02-01'
    thesis('late-disclosure-stays-unknown',spec,'2026-03-01','waiting_for_data')
    canonical=json.dumps([{'id':r['id'],'input':r['input'],'expected':r['expected']} for r in rows],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    return {'mode':'offline','provenance':'synthetic_offline_fixture','dataset_sha256':hashlib.sha256(canonical).hexdigest(),
            'hash_policy':'canonical JSON, UTF-8, sorted keys, line-ending independent',
            'cases':len(rows),'matched_cases':sum(r['matched'] for r in rows),'results':rows,
            'limitations':['Implementation-authored deterministic fixtures, not independent financial expert labels.',
                           'No real company validation, causal inference, trading returns or live API measurements.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='artifacts/research-tools-evaluation.json')
    args=parser.parse_args();report=evaluate();out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{report["matched_cases"]}/{report["cases"]} financial-research fixtures; {out}')
    return 0 if report['matched_cases']==report['cases'] else 1


if __name__=='__main__':raise SystemExit(main())
