"""Fictional signal experiments; codes never denote real company figures."""
from copy import deepcopy
from decimal import Decimal

from src.research_signals import DEFAULT_RULES, digest, score_archive


def demo_rules():
    return dict(deepcopy(DEFAULT_RULES),version='synthetic-research-quality-v1',frozen_at='2025-01-01')


def _payload(symbol, annuals, fetched):
    rows = []
    for year, values in annuals.items():
        for period, fraction in [('03-31','.2'),('06-30','.45'),('09-30','.7'),('12-31','1')]:
            for metric, value in values.items():
                rows.append({'metric':metric,'value':str(Decimal(str(value))*Decimal(fraction)),
                             'period_end':f'{year}-{period}','unit':'元','currency':'CNY',
                             'scope':'consolidated','basis':'cumulative',
                             'published_at':f'{year+1}-04-30',
                             'source_url':f'https://example.invalid/signal-fixture/{symbol}/{year}'})
    return {'symbol':symbol,'fetched_at':fetched,'provenance':'synthetic_offline_fixture','financial_records':rows}


def demo_manifest():
    annual = lambda r,p,c,cost: {'revenue':r,'net_profit':p,'attributable_net_profit':p,
                                'operating_cash_flow':c,'cost_of_revenue':cost}
    base = annual(100,10,10,70)
    # A healthy then confirmed; B weak then failed; C growth-only false positive;
    # D missing cash inputs; E good inputs followed by an adverse future outcome.
    configurations = [
        ('000001',annual(120,14,17,78),annual(132,15,18,86),True),
        ('000002',annual(150,5,2.5,135),annual(90,1,1,80),True),
        ('000003',annual(110,11,2.2,77),annual(90,8,5,65),False),
        ('000004',annual(120,14,17,78),annual(132,15,18,86),None),
        ('000005',annual(120,14,17,78),annual(80,-5,-2,70),False),
    ]
    snapshots,cases = [],[]
    for index,(symbol,current,future,agent) in enumerate(configurations,1):
        feature = {'id':f'feature-{index}','captured_at':'2025-05-01',
                   'payload':_payload(symbol,{2023:base,2024:current},'2025-05-01T00:00:00Z')}
        if symbol == '000004':
            feature['payload']['financial_records'] = [r for r in feature['payload']['financial_records'] if r['metric']!='operating_cash_flow']
        outcome = {'id':f'outcome-{index}','captured_at':'2026-05-01',
                   'payload':_payload(symbol,{2023:base,2024:current,2025:future},'2026-05-01T00:00:00Z')}
        criterion = {'review_on':'2026-05-01','criteria':[
            {'metric':'revenue','measure':'yoy','operator':'>=','threshold':'0','period_end':'2025-12-31',
             'currency':'CNY','scope':'consolidated','basis':'cumulative'},
            {'metric':'net_profit','measure':'value','operator':'>','threshold':'0','period_end':'2025-12-31',
             'currency':'CNY','scope':'consolidated','basis':'cumulative'},
        ]}
        case = {'id':f'fictional-{index}','symbol':symbol,'registered_at':'2025-05-02',
                'decision_on':'2025-05-05','feature_snapshot_id':feature['id'],
                'outcome_snapshot_id':outcome['id'],'criterion':criterion}
        if agent is not None:
            score = score_archive(feature,decision_on=case['decision_on'],rules=demo_rules())
            case['agent_call'] = {'prediction':agent,'recorded_at':'2025-05-03',
                                  'feature_hash':digest(feature),'criterion_hash':digest(criterion),
                                  'evidence_ids':score['factors'][0]['input_ids'],
                                  'origin':'synthetic_fixture_not_model_output'}
        snapshots.extend([feature,outcome])
        cases.append(case)
    return {'schema_version':1,'provenance':'synthetic_offline_fixture','rules':demo_rules(),
            'universe':{'name':'虚构工业公司样本池，不代表代码对应的真实公司',
                        'known_at':'2025-01-01','symbols':[c['symbol'] for c in cases]},
            'snapshots':deepcopy(snapshots),'cases':cases}
