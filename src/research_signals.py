"""Offline, deterministic research scoring and paired financial-outcome evaluation.

This module never fetches prices, calls a model or trades. Archive timestamps are
declared metadata, not independent proof of historical availability.
"""
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from src.financial_analysis import number, numeric_string
from src.financial_quality import financial_quality
from src.stock_data import normalize_symbol
from src.thesis_tracking import evaluate_test, validate_test

FACTOR_KEYS = {'revenue_yoy', 'attributable_profit_yoy', 'gross_margin', 'net_margin', 'cash_conversion'}
DEFAULT_RULES = {
    'version': 'research-quality-v1', 'frozen_at': '2026-10-20', 'threshold': '60',
    'basis': 'cumulative', 'currency': 'CNY', 'scope': 'consolidated',
    'factors': [
        {'key': 'revenue_yoy', 'weight': '20', 'cutoffs': ['0', '10', '20']},
        {'key': 'attributable_profit_yoy', 'weight': '20', 'cutoffs': ['0', '10', '20']},
        {'key': 'gross_margin', 'weight': '20', 'cutoffs': ['0', '15', '30']},
        {'key': 'net_margin', 'weight': '10', 'cutoffs': ['0', '5', '10']},
        {'key': 'cash_conversion', 'weight': '30', 'cutoffs': ['0.5', '1', '1.2']},
    ],
    'points': ['0', '40', '70', '100'],
}
LIMITATIONS = [
    '手工规则和权重未经收益优化；分数表示所设研究条件，不是买卖建议。',
    '只验证明确的未来财务判据，不验证完整论点、因果或股价收益。',
    '档案、股票池与登记日期由输入声明，哈希保证重放一致性，不独立证明事前存在。',
    '缺失项不补零、不重分配权重；只有完整覆盖才产生综合分和候选判断。',
    '不含估值评分、行情收益、交易成本、退市股票池或真实模型质量认证。',
]
LABEL_DEFINITION = '目标期营业收入同比不低于 0，且同范围净利润大于 0；两项均满足才标记满足。'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def day(value):
    """Date-level contracts use Shanghai dates; timestamps must include a zone."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return date.fromisoformat(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(ZoneInfo('Asia/Shanghai')).date()
    except (ValueError, TypeError):
        raise ValueError('日期须为 ISO 日期，时间戳须带时区') from None


def checked_rules(rules=None):
    rules = deepcopy(DEFAULT_RULES if rules is None else rules)
    if not isinstance(rules, dict) or set(rules) != set(DEFAULT_RULES):
        raise ValueError('规则字段不完整或包含不支持字段')
    if not isinstance(rules['version'], str) or not rules['version'].strip():
        raise ValueError('规则需要明确版本')
    rules['frozen_at'] = str(day(rules['frozen_at']))
    if rules['basis'] not in {'cumulative', 'single_quarter'} or rules['currency'] not in {'CNY','USD','HKD','EUR'} or rules['scope'] not in {'consolidated','parent_company'}:
        raise ValueError('规则财务口径无效')
    threshold = number(rules['threshold'])
    points = [number(v) for v in rules['points']] if isinstance(rules['points'], list) else []
    factors = rules['factors']
    if threshold is None or not 0 <= threshold <= 100 or len(points) != 4 or any(v is None for v in points) or not (points[0] == 0 and points[-1] == 100 and points == sorted(set(points))):
        raise ValueError('评分阈值或四档分值无效')
    if not isinstance(factors, list) or len(factors) != len(FACTOR_KEYS):
        raise ValueError('需要五项不同的财务因子')
    keys, weights = [], []
    for factor in factors:
        if not isinstance(factor, dict) or set(factor) != {'key','weight','cutoffs'}:
            raise ValueError('因子规则字段无效')
        key, weight = factor['key'], number(factor['weight'])
        cutoffs = [number(v) for v in factor['cutoffs']] if isinstance(factor['cutoffs'], list) else []
        if key not in FACTOR_KEYS or weight is None or weight <= 0 or len(cutoffs) != 3 or any(v is None for v in cutoffs) or cutoffs != sorted(set(cutoffs)):
            raise ValueError('因子、正权重或三档递增阈值无效')
        factor.update(weight=numeric_string(weight), cutoffs=[numeric_string(v) for v in cutoffs])
        keys.append(key)
        weights.append(weight)
    if len(set(keys)) != len(FACTOR_KEYS) or sum(weights) != 100:
        raise ValueError('因子不得重复且权重之和须为 100')
    rules.update(threshold=numeric_string(threshold), points=[numeric_string(v) for v in points])
    return rules


def score_financials(payload, *, as_of, rules=None):
    """Current/as-of rule score; strict archived replay is handled separately."""
    rules = checked_rules(rules)
    cutoff = day(as_of)
    if not isinstance(payload,dict) or not isinstance(payload.get('financial_records'),list) or len(payload['financial_records'])>1000:
        raise ValueError('评分输入须为含最多 1000 条标准财务记录的对象')
    if not isinstance(payload.get('symbol'),str) or not re.fullmatch(r'\d{6}',payload['symbol']):
        raise ValueError('评分公司须使用六位代码')
    quality = financial_quality(payload, as_of=cutoff, basis=rules['basis'],
                                currency=rules['currency'], scope=rules['scope'])
    index = {f['key']: f for f in quality['factors']}
    factors, coverage, observed = [], Decimal(0), Decimal(0)
    with localcontext() as ctx:
        ctx.prec, ctx.rounding = 40, ROUND_HALF_EVEN
        for rule in rules['factors']:
            source = index[rule['key']]
            valid = source['status'] == 'ok'
            points = number(rules['points'][sum(number(source['value']) >= number(v) for v in rule['cutoffs'])]) if valid else None
            contribution = points * number(rule['weight']) / 100 if valid else None
            if valid:
                coverage += number(rule['weight'])
                observed += contribution
            factors.append(dict(source, weight=rule['weight'], cutoffs=rule['cutoffs'],
                                points=numeric_string(points) if valid else None,
                                contribution=numeric_string(contribution) if valid else None))
    complete = coverage == 100
    # Export only the usable lineage that actually feeds factors/flags. The
    # normalizer retains blocked/future rows for diagnostics; those values must
    # never become part of the decision evidence handed to a downstream role.
    inputs={}
    def follow(key):
        row=quality['inputs'].get(key)
        if key in inputs or not row or row.get('status')!='ok':
            return
        inputs[key]=deepcopy(row)
        for parent in row.get('input_ids',[]):
            follow(parent)
    for item in factors+quality['flags']:
        for key in item['input_ids']:
            follow(key)
    for factor in factors:
        factor['input_ids']=[key for key in factor['input_ids'] if key in inputs]
    return {'schema_version': 1, 'symbol': payload.get('symbol'), 'as_of': str(cutoff),
            'period_end': quality['period_end'], 'rules': rules, 'rules_hash': digest(rules),
            'score': numeric_string(observed) if complete else None,
            'observed_contribution': numeric_string(observed), 'coverage_weight': numeric_string(coverage),
            'prediction': observed >= number(rules['threshold']) if complete else None,
            'status': 'complete' if complete else 'insufficient_data',
            'factors': factors, 'flags': quality['flags'], 'inputs': inputs,
            'provenance':quality['provenance'],'limitations': LIMITATIONS}


def _snapshot(snapshot):
    if not isinstance(snapshot, dict) or set(snapshot) != {'id','captured_at','payload'}:
        raise ValueError('档案须包含唯一编号、采集日期和完整财务输入')
    if not isinstance(snapshot['id'], str) or not snapshot['id']:
        raise ValueError('档案编号无效')
    captured = day(snapshot['captured_at'])
    payload = deepcopy(snapshot['payload'])
    if not isinstance(payload, dict) or not isinstance(payload.get('financial_records'), list) or len(payload['financial_records']) > 1000:
        raise ValueError('档案须提供最多 1000 条 canonical 财务记录')
    normalize_symbol(payload.get('symbol'))
    for row in [payload, *payload['financial_records']]:
        if not isinstance(row, dict):
            raise ValueError('档案财务记录无效')
        fetched = row.get('fetched_at') or payload.get('fetched_at')
        if not fetched or day(fetched) > captured:
            raise ValueError('档案包含采集日期之后取得的数据或缺少取得日期')
        # Normalize metadata into the same date timezone before the existing
        # financial engine processes it. Original bytes remain in the manifest.
        for field in ('fetched_at','published_at','available_at'):
            if row.get(field):
                row[field] = str(day(row[field]))
    return payload, captured


def _baseline(score):
    factors = {f['key']: f for f in score['factors']}
    growth = [factors[key] for key in ('revenue_yoy','attributable_profit_yoy')]
    return all(number(f['value']) >= 0 for f in growth) if all(f['status']=='ok' for f in growth) else None


def score_archive(snapshot, *, decision_on, rules=None):
    rules = checked_rules(rules)
    payload,captured = _snapshot(snapshot)
    decision = day(decision_on)
    if captured >= decision or day(rules['frozen_at']) >= decision:
        raise ValueError('评分规则和档案必须在决策日前确定')
    return dict(score_financials(payload,as_of=decision,rules=rules),
                archive_hash=digest(snapshot),captured_at=str(captured))


def _agent(call, *, case, snapshot, score):
    if call is None:
        return None, '未提供事前登记的结构化研究判断'
    if not isinstance(call, dict) or not isinstance(call.get('prediction'), bool):
        return None, '研究判断缺少明确布尔预测'
    if call.get('feature_hash') != digest(snapshot) or call.get('criterion_hash') != digest(case['criterion']):
        return None, '研究判断未绑定当前档案和判据版本'
    try:
        timely = bool(call.get('recorded_at')) and day(call['recorded_at']) < day(case['decision_on'])
    except ValueError:
        timely = False
    if not call.get('origin') or not timely:
        return None, '研究判断必须在决策日前登记并标识来源'
    ids = call.get('evidence_ids')
    if not isinstance(ids, list) or not ids or any(not isinstance(key,str) or key not in score['inputs'] or score['inputs'][key].get('status')!='ok' for key in ids):
        return None, '研究判断缺少本档案内可用证据'
    return call['prediction'], '仅校验结构化判断的版本、时点和证据存在，不认证语义支持'


def _metrics(rows, method):
    pairs = [(r['predictions'][method], r['label']) for r in rows
             if isinstance(r['predictions'][method], bool) and isinstance(r['label'], bool)]
    tp = sum(p and y for p,y in pairs)
    tn = sum(not p and not y for p,y in pairs)
    fp = sum(p and not y for p,y in pairs)
    fn = sum(not p and y for p,y in pairs)
    def rate(n,d):
        with localcontext() as ctx:
            ctx.prec,ctx.rounding=40,ROUND_HALF_EVEN
            return numeric_string(Decimal(n)/d) if d else None
    return {'n':len(pairs), 'tp':tp,'tn':tn,'fp':fp,'fn':fn,
            'accuracy':rate(tp+tn,len(pairs)), 'precision':rate(tp,tp+fp), 'recall':rate(tp,tp+fn)}


def evaluate_experiment(manifest, *, as_of, rules=None):
    """Replay fixed decisions and compare methods on explicitly shared cohorts."""
    cutoff = day(as_of)
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 1 or not manifest.get('provenance'):
        raise ValueError('实验需要 schema_version=1 与来源标识')
    rules = checked_rules(rules if rules is not None else manifest.get('rules'))
    cases, archives, universe = manifest.get('cases'), manifest.get('snapshots'), manifest.get('universe')
    if not isinstance(cases,list) or not 1 <= len(cases) <= 100 or not isinstance(archives,list) or not 1 <= len(archives) <= 200:
        raise ValueError('实验需要 1–100 个样本、1–200 份档案')
    if not isinstance(universe,dict) or not universe.get('name') or not isinstance(universe.get('symbols'),list) or not 1 <= len(universe['symbols']) <= 50:
        raise ValueError('需要明确名称、形成日期与最多 50 家公司的样本池')
    if any(not isinstance(symbol,str) or not re.fullmatch(r'\d{6}',symbol) for symbol in universe['symbols']):
        raise ValueError('样本池公司须使用六位代码')
    if len(set(universe['symbols'])) != len(universe['symbols']):
        raise ValueError('样本池公司不得重复')
    for symbol in universe['symbols']:
        normalize_symbol(symbol)
    snapshots, payloads, captured_days = {}, {}, {}
    record_count=0
    for archive in archives:
        payload,captured = _snapshot(archive)
        record_count+=len(payload['financial_records'])
        if record_count>20000:
            raise ValueError('实验财务记录总量超出上限')
        key = archive['id']
        if key in snapshots:
            raise ValueError('档案编号不得重复')
        snapshots[key],payloads[key],captured_days[key] = archive,payload,captured
    if any(not isinstance(c,dict) or not isinstance(c.get('id'),str) or not c['id'] for c in cases):
        raise ValueError('样本编号无效')
    if len({c['id'] for c in cases}) != len(cases):
        raise ValueError('样本编号不得缺失或重复')
    rows, observations_seen = [], set()
    for case in cases:
        if not isinstance(case,dict) or not isinstance(case.get('id'),str) or not case['id']:
            raise ValueError('样本编号无效')
        symbol = case.get('symbol')
        decision = day(case.get('decision_on'))
        if symbol not in universe['symbols'] or day(universe.get('known_at')) >= decision:
            raise ValueError('公司须属于决策日前明确的样本池')
        if day(case.get('registered_at')) >= decision or day(rules['frozen_at']) >= decision:
            raise ValueError('判据与规则必须在决策日前登记')
        if decision > cutoff:
            raise ValueError('不能评测尚未发生的决策')
        feature_id, outcome_id = case.get('feature_snapshot_id'),case.get('outcome_snapshot_id')
        if feature_id not in snapshots or outcome_id not in snapshots:
            raise ValueError('缺少指定档案，不得用最新版本替代')
        if any(payloads[key]['symbol'] != symbol for key in (feature_id,outcome_id)):
            raise ValueError('档案与样本公司不一致')
        if captured_days[feature_id] >= decision:
            raise ValueError('决策仅可使用前一日及以前已采集的档案')
        criterion = case.get('criterion')
        checked = validate_test(criterion)
        observation_key = (symbol,str(decision),digest(checked))
        if observation_key in observations_seen:
            raise ValueError('同公司、决策日和判据的样本不得重复计数')
        observations_seen.add(observation_key)
        if any(day(c['period_end']) <= decision for c in checked['criteria']):
            raise ValueError('此原型只验证决策日之后结束的财报期')
        if any((c['currency'],c['scope']) != (rules['currency'],rules['scope']) for c in checked['criteria']):
            raise ValueError('目标财务判据须与评分币种和报表范围一致')
        signatures = {(c['metric'],c['measure'],c['operator'],c['threshold']) for c in checked['criteria']}
        if len(checked['criteria']) != 2 or signatures != {('revenue','yoy','>=','0'),('net_profit','value','>','0')} or len({c['period_end'] for c in checked['criteria']}) != 1 or any(c['basis'] != rules['basis'] for c in checked['criteria']):
            raise ValueError('v1 验证任务固定为同目标期营收同比≥0且净利润>0，且期间口径一致')
        score = score_archive(snapshots[feature_id], decision_on=decision, rules=rules)
        if score['period_end'] and any(day(c['period_end']) <= day(score['period_end']) for c in checked['criteria']):
            raise ValueError('目标财报期必须晚于评分期')
        if captured_days[outcome_id] <= decision:
            raise ValueError('后续验证档案必须晚于决策日')
        observation = None
        label = None
        status = 'not_due' if day(checked['review_on']) > cutoff else 'waiting_for_data'
        if captured_days[outcome_id] <= cutoff:
            observation = evaluate_test(dict(criterion,symbol=symbol),payloads[outcome_id],as_of=cutoff)
            status = observation['status']
            if status in {'criterion_met','criterion_not_met'}:
                label = status == 'criterion_met'
        agent,reason = _agent(case.get('agent_call'),case=case,snapshot=snapshots[feature_id],score=score)
        rows.append({'id':case['id'],'symbol':symbol,'decision_on':str(decision),'label':label,
                     'outcome_status':status,'score':score,'outcome':observation,
                     'predictions':{'baseline':_baseline(score),'rules':score['prediction'],'agent':agent},
                     'agent_note':reason,'feature_hash':digest(snapshots[feature_id]),
                     'outcome_hash':digest(snapshots[outcome_id]),'criterion_hash':digest(criterion)})
    methods = ['baseline','rules','agent']
    pair_rules = [r for r in rows if isinstance(r['label'],bool) and all(isinstance(r['predictions'][m],bool) for m in ('baseline','rules'))]
    pair_agent = [r for r in pair_rules if isinstance(r['predictions']['agent'],bool)]
    common = lambda cohort,names: {'case_ids':[r['id'] for r in cohort], 'n':len(cohort),
                                    'metrics':{m:_metrics(cohort,m) for m in names}}
    coverage = {m:{'decisions':sum(isinstance(r['predictions'][m],bool) for r in rows),
                   'labeled':_metrics(rows,m)['n'], 'total':len(rows)} for m in methods}
    return {'schema_version':1,'id':digest([manifest,rules,str(cutoff)]),
            'as_of':str(cutoff),'provenance':manifest['provenance'],'manifest_hash':digest(manifest),
            'label_definition':LABEL_DEFINITION,
            'rules_hash':digest(rules),'rules':rules,'case_count':len(rows),'rows':rows,'coverage':coverage,
            'rule_baseline_cohort':common(pair_rules,['baseline','rules']),'all_methods_cohort':common(pair_agent,methods),
            'replay':{'manifest':deepcopy(manifest),'rules':rules,'as_of':str(cutoff)},
            'limitations':LIMITATIONS}
