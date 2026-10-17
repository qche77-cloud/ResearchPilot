"""Financial questions and arithmetic profit bridges; no causal model or advice."""
from datetime import date
from decimal import Decimal, localcontext, ROUND_HALF_EVEN

from src.financial_analysis import identity, number, numeric_string, parse_period
from src.observability import traced_tool

DEFAULT_THRESHOLDS = {'working_capital_spread_pp': '10', 'gross_margin_drop_pp': '2',
                      'nonrecurring_share_pct': '50'}


def unique(rows):
    return rows[0] if len(rows) == 1 else None


def select_context(analysis, *, basis='cumulative', currency='CNY', scope='consolidated', period_end=None):
    if basis not in {'cumulative', 'single_quarter'} or currency not in {'CNY', 'USD', 'HKD', 'EUR'} or scope not in {'consolidated', 'parent_company'}:
        raise ValueError('请选择明确的累计/单季、币种和报表范围')
    rows = analysis['records'] if basis == 'cumulative' else analysis['quarter_records']
    rows = [r for r in rows if r['status'] == 'ok' and r['symbol'] == analysis['symbol']
            and r['basis'] == basis and r['currency'] == currency and r['scope'] == scope]
    periods = [r['period_end'] for r in rows]
    period = period_end or (max(periods) if periods else None)
    end = parse_period(period)
    if period_end and (not end or (end.month, end.day) not in {(3,31),(6,30),(9,30),(12,31)}):
        raise ValueError('请选择有效财报期末')
    previous = str(date(end.year-1, end.month, end.day)) if end else None
    context = {'symbol': analysis['symbol'], 'basis': basis, 'currency': currency, 'scope': scope,
               'period_end': period, 'previous_period': previous, 'as_of': analysis.get('as_of')}

    def get(metric, when=period):
        # Instant balances are compared at the same year-on-year endpoints.
        pool = analysis['records'] if metric in {'inventory', 'accounts_receivable'} else rows
        return unique([r for r in pool if r['status'] == 'ok' and r['metric'] == metric and r['period_end'] == when
                       and r['symbol'] == analysis['symbol'] and r['currency'] == currency and r['scope'] == scope
                       and r['basis'] == ('instant' if metric in {'inventory', 'accounts_receivable'} else basis)])
    return context, get


def _growth(current, previous):
    if not current or not previous or number(previous['value']) <= 0:
        return None
    value = (number(current['value']) / number(previous['value']) - 1) * 100
    return value if number(value) is not None else None


def _bridge(context, get):
    r0, r1 = get('revenue', context['previous_period']), get('revenue')
    c0, c1 = get('cost_of_revenue', context['previous_period']), get('cost_of_revenue')
    p0, p1 = get('net_profit', context['previous_period']), get('net_profit')
    required = [r0, r1, c0, c1, p0, p1]
    base = {'context': context, 'unit': 'currency_unit', 'status': 'unavailable', 'steps': [],
            'policy': '会计金额恒等分解，不证明业务因果；净利润为同范围净利润，不能以归母利润替代。'}
    if not all(required):
        return {**base, 'reason': '缺少唯一同口径的两期营业收入、营业成本或净利润；未用归母利润替代净利润。'}
    if number(r0['value']) <= 0:
        return {**base, 'reason': '基期营业收入不为正，无法进行收入与毛利率分解。'}
    rv0, rv1, cv0, cv1, pv0, pv1 = [number(r['value']) for r in required]
    # Round only the revenue contribution to one cent. Compute the margin and
    # unexplained remainder by subtraction so the displayed ledger reconciles.
    unrounded = (rv1-rv0) * (rv0-cv0) / rv0
    if number(unrounded) is None:
        return {**base, 'reason':'分解金额超出安全计算范围。'}
    revenue_effect = unrounded.quantize(Decimal('.01'), rounding=ROUND_HALF_EVEN)
    margin_effect = ((rv1-cv1)-(rv0-cv0)) - revenue_effect
    e0, e1 = get('expense', context['previous_period']), get('expense')
    expense_effect = -(number(e1['value'])-number(e0['value'])) if e0 and e1 else None
    residual = (pv1-pv0) - revenue_effect - margin_effect - (expense_effect if expense_effect is not None else 0)
    parts = [dict(key='opening', label='上年同期净利润', value=pv0, input_ids=[p0['id']], formula='P0'),
             dict(key='revenue', label='收入变化贡献', value=revenue_effect, input_ids=[r0['id'], r1['id'], c0['id']], formula='(R1-R0) × (R0-C0)/R0; ROUND_HALF_EVEN to 0.01'),
             dict(key='margin', label='毛利率变化贡献', value=margin_effect, input_ids=[r0['id'], r1['id'], c0['id'], c1['id']], formula='Δ(R-C) - revenue contribution')]
    if expense_effect is not None:
        parts.append(dict(key='expense', label='期间费用变化贡献', value=expense_effect, input_ids=[e0['id'], e1['id']], formula='-(E1-E0)'))
    inputs = [r['id'] for r in required + ([e0, e1] if expense_effect is not None else [])]
    parts.extend([dict(key='residual', label='未解释差额' if expense_effect is not None else '未解释差额（含未拆费用）', value=residual, input_ids=inputs,
                       formula='ΔP - revenue contribution - margin contribution - available expense contribution'),
                  dict(key='closing', label='本期净利润', value=pv1, input_ids=[p1['id']], formula='P1')])
    if any(number(p['value']) is None for p in parts):
        return {**base, 'reason': '分解金额超出安全计算范围。'}
    running = pv0
    for part in parts:
        if part['key'] in {'opening', 'closing'}:
            start, end = Decimal(0), part['value']
        else:
            start, end = running, running + part['value']
            running = end
        part.update(value=numeric_string(part['value']), start=numeric_string(start), end=numeric_string(end),
                    id=identity([context, part['key'], part['input_ids']], 'PB'))
    if running != pv1:
        return {**base, 'reason':'当前 Decimal 精度下金额未能勾稽，不输出图表。'}
    return {**base, 'status': 'ok', 'reason': '', 'steps': parts, 'input_ids': inputs,
            'change': numeric_string(pv1-pv0), 'reconciled': running == pv1,
            'missing_components': [] if expense_effect is not None else ['两期期间费用'],
            'rounding': 'Decimal precision=40, ROUND_HALF_EVEN; revenue contribution rounded to 0.01 currency unit',
            'unexplained': '差额可能包含税费、减值、投资收益及其他项目，未据此自动判定任何原因。'}


@traced_tool('financial.research_diagnostics')
def research_diagnostics(analysis, *, thresholds=None, **options):
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    if set(thresholds) != set(DEFAULT_THRESHOLDS) or any(number(v) is None or not 0 <= number(v) <= 100 for v in thresholds.values()):
        raise ValueError('异常阈值须为 0–100 的明确数值')
    thresholds = {k:numeric_string(number(v)) for k,v in thresholds.items()}
    context, get = select_context(analysis, **options)
    with localcontext() as ctx:
        ctx.prec, ctx.rounding = 40, ROUND_HALF_EVEN
        rules = []
        def add(code, label, rows, condition, values, question, threshold=None):
            available = all(rows) and condition is not None and all(number(v) is not None for v in values.values() if v is not None)
            rules.append({'id': identity([context, code, thresholds], 'FA'), 'code': code, 'label': label,
                          'status': 'triggered' if available and condition else 'clear' if available else 'unavailable',
                          'observations': {k: numeric_string(v) for k,v in values.items() if v is not None and number(v) is not None},
                          'input_ids': list(dict.fromkeys(r['id'] for r in rows if r)), 'question': question,
                          'threshold': threshold, 'reason': '' if available else '缺少唯一同口径输入，或分母不适合比较。'})
        prev = context['previous_period']
        r0, r1 = get('revenue', prev), get('revenue')
        profit_metric = 'attributable_net_profit' if get('attributable_net_profit') else 'net_profit'
        p0, p1 = get(profit_metric, prev), get(profit_metric)
        dr = number(r1['value'])-number(r0['value']) if r0 and r1 else None
        dp = number(p1['value'])-number(p0['value']) if p0 and p1 else None
        add('revenue_profit_divergence', '收入增加而利润减少', [r0,r1,p0,p1], dr > 0 and dp < 0 if dr is not None and dp is not None else None,
            {'revenue_change': dr, profit_metric+'_change': dp}, '毛利率、期间费用或业务结构能否解释利润变化？')
        net, cash = get('net_profit'), get('operating_cash_flow')
        ratio = number(cash['value']) / number(net['value']) if net and cash and number(net['value']) > 0 else None
        add('cash_below_profit', '经营现金流低于同期正净利润', [net,cash], ratio < 1 if ratio is not None else None,
            {'cash_profit_ratio':ratio}, '应收、存货和其他营运资金变化能否解释现金与利润差异？')
        rg = _growth(r1,r0)
        for metric, label in [('inventory','存货'),('accounts_receivable','应收账款')]:
            a0, a1 = get(metric,prev), get(metric)
            growth = _growth(a1,a0)
            spread = growth-rg if growth is not None and rg is not None else None
            add(metric+'_outpaces_revenue', label+'余额增速高于收入增速', [a0,a1,r0,r1], spread > number(thresholds['working_capital_spread_pp']) if spread is not None else None,
                {'balance_yoy_pct':growth,'revenue_yoy_pct':rg,'spread_pp':spread},
                '这是期末余额与同期收入增速的比较线索；需核对账龄、订单和备货季节性，不能据此断言积压或坏账。', thresholds['working_capital_spread_pp']+' 个百分点')
        c0,c1 = get('cost_of_revenue',prev),get('cost_of_revenue')
        margin0 = (1-number(c0['value'])/number(r0['value']))*100 if r0 and c0 and number(r0['value'])>0 else None
        margin1 = (1-number(c1['value'])/number(r1['value']))*100 if r1 and c1 and number(r1['value'])>0 else None
        drop = margin0-margin1 if margin0 is not None and margin1 is not None else None
        add('gross_margin_drop', '毛利率较上年同期下降', [r0,r1,c0,c1], drop >= number(thresholds['gross_margin_drop_pp']) if drop is not None else None,
            {'previous_margin_pct':margin0,'current_margin_pct':margin1,'drop_pp':drop}, '产品结构、定价或成本变化是否有原始披露支持？', thresholds['gross_margin_drop_pp']+' 个百分点')
        rd0,rd1 = get('rd_expense',prev),get('rd_expense')
        rdchange = number(rd1['value'])-number(rd0['value']) if rd0 and rd1 else None
        add('rd_expense_down', '收入增加但费用化研发费用减少', [r0,r1,rd0,rd1], dr > 0 and rdchange < 0 if dr is not None and rdchange is not None else None,
            {'revenue_change':dr,'rd_expense_change':rdchange}, '是否存在研发资本化或项目周期变化？费用化研发下降不等于研发投入下降。')
        attr, deducted = get('attributable_net_profit'),get('attributable_profit_excluding_nonrecurring')
        share = (number(attr['value'])-number(deducted['value']))/number(attr['value'])*100 if attr and deducted and number(attr['value'])>0 else None
        add('nonrecurring_profit_share', '归母与扣非利润差额占比较高', [attr,deducted], share >= number(thresholds['nonrecurring_share_pct']) if share is not None else None,
            {'difference_share_pct':share}, '差额具体包含哪些已披露项目？不能直接归因为资产处置。', thresholds['nonrecurring_share_pct']+'%')
        bridge = _bridge(context,get)
    return {'schema_version':1, 'context':context, 'thresholds':thresholds, 'rules':rules,
            'triggered_count':sum(r['status']=='triggered' for r in rules),
            'unavailable_count':sum(r['status']=='unavailable' for r in rules), 'profit_bridge':bridge,
            'policy':'异常是需要解释的研究线索，不是财务造假、经营因果或买卖判断。缺失数据不等于没有异常。'}
