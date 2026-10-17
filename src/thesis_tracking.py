"""Deterministic tests of user-defined financial criteria, never full-thesis truth."""
from datetime import date
from decimal import localcontext, ROUND_HALF_EVEN

from src.financial_analysis import (METRICS, STOCK_METRICS, analyze_financials, availability_date,
                                    identity, number, numeric_string, financial_evidence)
from src.financial_diagnostics import unique

TEST_LABELS = {'not_due':'未到复盘日', 'waiting_for_data':'等待可比披露数据',
               'criterion_met':'财务判据满足', 'criterion_not_met':'财务判据未满足'}


def validate_test(raw):
    if not isinstance(raw,dict) or not isinstance(raw.get('criteria'),list) or not 1 <= len(raw['criteria']) <= 6:
        raise ValueError('请填写 1–6 条明确的财务判据')
    try:
        review_on = date.fromisoformat(raw['review_on'])
    except (ValueError,TypeError,KeyError):
        raise ValueError('请填写明确的复盘日期')
    checked = []
    for c in raw['criteria']:
        if not isinstance(c,dict) or c.get('metric') not in METRICS or c.get('measure') not in {'value','yoy'} or c.get('operator') not in {'>=','>','<=','<'}:
            raise ValueError('财务判据指标、计算方式或比较符无效')
        if c.get('currency') not in {'CNY','USD','HKD','EUR'} or c.get('scope') not in {'consolidated','parent_company'}:
            raise ValueError('判据需要明确币种和报表范围')
        basis = c.get('basis')
        if basis not in ({'instant'} if c['metric'] in STOCK_METRICS else {'cumulative','single_quarter'}):
            raise ValueError('判据期间口径与指标不一致')
        if c['measure']=='yoy' and (basis=='instant' or c['metric']=='gross_margin'):
            raise ValueError('此指标暂不支持同比判据，请选择期末值或毛利率值')
        threshold = number(c.get('threshold'))
        if threshold is None:
            raise ValueError('判据阈值必须是有限数值')
        try:
            period = date.fromisoformat(c['period_end'])
        except (ValueError,TypeError,KeyError):
            raise ValueError('请填写明确的目标财报期末')
        if (period.month,period.day) not in {(3,31),(6,30),(9,30),(12,31)} or review_on < period:
            raise ValueError('目标须为财报季末，复盘日不能早于目标期末')
        checked.append({k:c[k] for k in ('metric','measure','operator','currency','scope','basis')} |
                       {'threshold':numeric_string(threshold),'period_end':str(period)})
    if len({identity(c) for c in checked}) != len(checked):
        raise ValueError('不能重复保存同一判据')
    return {'review_on':str(review_on),'criteria':checked, 'policy':'全部判据满足才标记财务判据满足；不自动验证完整投资论点或改写人工状态。'}


def _observe(analysis,c):
    def match(row):
        return all(row.get(k)==c[k] for k in ('metric','period_end','basis','currency','scope')) and row.get('symbol')==analysis['symbol']
    if c['measure']=='yoy':
        row = unique([r for r in analysis['computations'] if match(r) and r['kind']=='yoy'])
    else:
        pool = analysis['quarter_records'] if c['basis']=='single_quarter' else analysis['records']
        raw = unique([r for r in pool if match(r) and r['status']=='ok'])
        derived = unique([r for r in analysis['computations'] if match(r) and r['kind']=='ratio' and r['status']=='ok']) if c['metric']=='gross_margin' else None
        if raw and derived and number(raw['value']) != number(derived['value']):
            return None, '来源毛利率与计算毛利率不一致，需核对口径。'
        row = raw or derived
    if not row or row['status']!='ok':
        return None, '缺少唯一、已披露且口径一致的目标期输入或有效对照期。'
    return row, ''


def evaluate_test(spec,payload,*,as_of):
    checked = validate_test(spec)
    cutoff = availability_date(as_of)
    if cutoff is None or spec.get('symbol') != payload.get('symbol'):
        raise ValueError('复盘日期或财务数据所属公司不一致')
    analysis = analyze_financials(payload,as_of=cutoff)
    observations = []
    with localcontext() as ctx:
        ctx.prec,ctx.rounding=40,ROUND_HALF_EVEN
        for c in checked['criteria']:
            row,reason = _observe(analysis,c)
            value = number(row['value']) if row else None
            threshold = number(c['threshold'])
            met = {'>=':value >= threshold,'>':value > threshold,'<=':value <= threshold,'<':value < threshold}[c['operator']] if value is not None else None
            observations.append({'criterion':c, 'label':METRICS[c['metric']], 'value':numeric_string(value) if value is not None else None,
                                 'unit':'percent' if c['measure']=='yoy' or c['metric']=='gross_margin' else 'currency_unit',
                                 'met':met,'reason':reason,'input_ids':row.get('input_ids') or [row['id']] if row else []})
    available = all(o['met'] is not None for o in observations)
    status = ('not_due' if cutoff < date.fromisoformat(checked['review_on']) else
              'waiting_for_data' if not available else
              'criterion_met' if all(o['met'] for o in observations) else 'criterion_not_met')
    index = financial_evidence(analysis)['inputs']
    inputs = {}
    def follow(key):
        if key in inputs or key not in index:
            return
        inputs[key] = index[key]
        for parent in index[key].get('input_ids',[]):
            follow(parent)
    for observation in observations:
        for key in observation['input_ids']:
            follow(key)
    return {'schema_version':1, 'symbol':spec['symbol'], 'as_of':str(cutoff),
            'review_on':checked['review_on'], 'status':status,'label':TEST_LABELS[status],
            'observations':observations, 'inputs':inputs,'all_data_available':available,
            'policy':checked['policy'], 'limitations':'未检验股价收益、完整因果或投资论点；阈值由用户设置，事后设置判据不是事前预测。'}
