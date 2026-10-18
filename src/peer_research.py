"""Fixed-period peer comparison and source-bound research questions. No models."""
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from src.financial_analysis import availability_date, parse_period, identity, number, numeric_string
from src.financial_quality import financial_quality
from src.stock_data import normalize_symbol

KEYS=('revenue_yoy','attributable_profit_yoy','gross_margin','net_margin','cash_conversion')


def validate_group(name, symbols):
    if not isinstance(name,str) or not name.strip() or len(name)>80 or not isinstance(symbols,list) or not 2 <= len(symbols) <= 50:
        raise ValueError('请填写比较组名称和 2–50 家不重复的公司代码')
    if len(set(symbols)) != len(symbols):
        raise ValueError('比较组公司不能重复')
    for symbol in symbols:
        normalize_symbol(symbol)
    return name.strip(), sorted(symbols)


def compare_peers(payloads, *, symbols, period_end, as_of, basis='cumulative', currency='CNY', scope='consolidated'):
    validate_group('comparison',symbols)
    period,cutoff=parse_period(period_end),availability_date(as_of)
    if not period or str(period)!=period_end or (period.month,period.day) not in {(3,31),(6,30),(9,30),(12,31)} or not cutoff or period>cutoff:
        raise ValueError('请选择有效的财报季末和资料截止日期')
    # Validate even when every company is missing inputs.
    if basis not in {'cumulative','single_quarter'} or currency not in {'CNY','USD','HKD','EUR'} or scope not in {'consolidated','parent_company'}:
        raise ValueError('比较期间、币种或报表范围无效')
    rows=[]
    for symbol in sorted(symbols):
        payload=payloads.get(symbol)
        if payload is None:
            rows.append(dict(symbol=symbol,factors=[],reason='缺少已保存的财务数据',inputs={}))
            continue
        if payload.get('symbol')!=symbol:
            raise ValueError('公司代码与财务输入不一致')
        # Keep history for YoY/TTM, remove later reporting periods before quality
        # chooses a period. If only an older report remains, abstain explicitly.
        source=payload.get('financial_records',payload.get('finance',[]))
        selected=[r for r in source if parse_period(r.get('period_end') or r.get('报告期')) and
                  parse_period(r.get('period_end') or r.get('报告期')) <= period]
        fixed=dict(payload,financial_records=selected)
        quality=financial_quality(fixed,as_of=as_of,basis=basis,currency=currency,scope=scope)
        same=quality['period_end']==period_end
        factors=quality['factors'] if same else []
        rows.append(dict(symbol=symbol,factors=factors,reason='' if same else '所选财报期暂无可比数据',inputs=quality['inputs']))
    summaries={}
    leads=[]
    with localcontext() as ctx:
        ctx.prec,ctx.rounding=40,ROUND_HALF_EVEN
        for key in KEYS:
            valid=[(r,next((f for f in r['factors'] if f['key']==key and f['status']=='ok'),None)) for r in rows]
            valid=[(r,f) for r,f in valid if f is not None]
            values=sorted(number(f['value']) for _,f in valid)
            n=len(values)
            median=(values[n//2] if n%2 else (values[n//2-1]+values[n//2])/2) if n else None
            summaries[key]=dict(count=n,total=len(symbols),median=numeric_string(median) if median is not None else None,
                                policy='比较组中位数；不是全行业统计，样本不足 3 家不产生横向异常线索')
            for r,f in valid:
                f['group_delta']=numeric_string(number(f['value'])-median)
                if key=='gross_margin' and n>=3 and number(f['group_delta'])<=-5:
                    leads.append(dict(symbol=r['symbol'],kind='gross_margin_peer_gap',title='毛利率低于比较组中位数至少 5 个百分点',
                                      question='毛利率差异来自产品结构、售价、原材料还是会计口径？查找支持与反面证据，不预设原因。',
                                      factor_keys=[key],threshold='-5',unit='percentage_points'))
        for r in rows:
            fs={f['key']:f for f in r['factors'] if f['status']=='ok'}
            if all(k in fs for k in ('revenue_yoy','attributable_profit_yoy')) and number(fs['revenue_yoy']['value'])>0 and number(fs['attributable_profit_yoy']['value'])<=0:
                leads.append(dict(symbol=r['symbol'],kind='revenue_profit_divergence',title='营收增长，归母净利润未增长',
                                  question='核查毛利率、费用、非经常性损益和业务结构，并寻找反例。方向背离不证明原因。',
                                  factor_keys=['revenue_yoy','attributable_profit_yoy'],threshold='0',unit='percent'))
            if 'cash_conversion' in fs and number(fs['cash_conversion']['value'])<1:
                leads.append(dict(symbol=r['symbol'],kind='cash_below_profit',title='近12个月经营现金流低于同范围净利润',
                                  question='核查应收、存货、回款及一次性项目，比较历史季节性，不直接判断财务质量。',
                                  factor_keys=['cash_conversion'],threshold='1',unit='multiple'))
    parameters=dict(period_end=period_end,as_of=str(cutoff),basis=basis,currency=currency,scope=scope,symbols=sorted(symbols))
    for lead in leads:
        row=next(r for r in rows if r['symbol']==lead['symbol'])
        lead['factors']=[f for f in row['factors'] if f['key'] in lead['factor_keys']]
        lead['id']=identity([parameters,lead],'L')
    return dict(schema_version=1,parameters=parameters,rows=rows,summaries=summaries,leads=leads,
                policy='用户自行选择比较组，不自动认定同业；缺失不补零；不同财报期不混排；无综合评分或收益预测。')


def attach_peer_evidence(state, result, lead):
    import json
    from src.models import Source, EvidenceDocument
    rows=[]
    for row in result['rows']:
        factors=[f for f in row['factors'] if f['key'] in lead['factor_keys']]
        inputs={}
        def follow(key):
            if key in inputs or key not in row['inputs']: return
            item=row['inputs'][key];inputs[key]=item
            for child in item.get('input_ids',[]): follow(child)
        for f in factors:
            for key in f['input_ids']: follow(key)
        rows.append(dict(symbol=row['symbol'],factors=factors,inputs=inputs,reason=row['reason']))
    body=dict(label='同业比较研究线索',lead=lead,comparison=dict(parameters=result['parameters'],
               summaries={k:result['summaries'][k] for k in lead['factor_keys']},rows=rows,policy=result['policy']))
    text=json.dumps(body,ensure_ascii=False)
    urls=[i['source_url'] for r in rows for i in r['inputs'].values() if i.get('source_url')]
    if not urls:
        raise ValueError('比较结果缺少原始来源')
    source=Source('固定版本财务比较与待核查问题',urls[0],text[:300],'financial_calculation',1,
                  source_id=f'S{len(state.sources)+1}',research_task='financial_data')
    state.sources.append(source)
    state.documents.append(EvidenceDocument(source,text,len(text.split()),'success',extraction_status='FULL_TEXT'))
    state.diagnostics['peer_research']=body
