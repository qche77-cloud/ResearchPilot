"""Deterministic, date-scoped financial screening inputs; no ranking or trading."""
from decimal import localcontext, ROUND_HALF_EVEN
from src.financial_analysis import (analyze_financials, availability_date, identity,
                                    number, numeric_string, ratio)


def financial_quality(payload, *, as_of=None, basis='cumulative', currency='CNY', scope='consolidated'):
    if basis not in {'cumulative', 'single_quarter'}:
        raise ValueError('quality basis must be cumulative or single_quarter')
    if currency not in {'CNY', 'USD', 'HKD', 'EUR'} or scope not in {'consolidated', 'parent_company'}:
        raise ValueError('explicit supported currency and scope required')
    cutoff = availability_date(as_of if as_of is not None else payload.get('fetched_at'))
    if cutoff is None:
        raise ValueError('quality requires a valid as_of or fetched_at')
    analysis = analyze_financials(payload, as_of=cutoff)
    rows = analysis['records'] if basis == 'cumulative' else analysis['quarter_records']
    rows = [r for r in rows if r['status'] == 'ok' and r['basis'] == basis
            and r['currency'] == currency and r['scope'] == scope and r['symbol'] == payload.get('symbol')]
    periods = [r['period_end'] for r in rows if r['metric'] in {'revenue', 'attributable_net_profit', 'net_profit', 'operating_cash_flow'}]
    period = max(periods) if periods else None

    def unique(items):
        return items[0] if len(items) == 1 else None

    def raw(metric):
        return unique([r for r in rows if r['period_end'] == period and r['metric'] == metric])

    def yoy(metric):
        return unique([c for c in analysis['computations'] if c['kind'] == 'yoy' and c['metric'] == metric
                       and c['period_end'] == period and c['basis'] == basis and c['currency'] == currency
                       and c['scope'] == scope and c['symbol'] == payload.get('symbol')])

    factors = []
    def add(key, label, calculation, unit='percent', reason='missing_comparable_inputs'):
        calculation = calculation or {}
        ok = calculation.get('status') == 'ok'
        inputs = calculation.get('input_ids', [])
        factors.append({'id': identity([key, str(cutoff), period, inputs, basis, currency, scope], 'Q'),
                        'key': key, 'label': label, 'value': calculation.get('value') if ok else None,
                        'unit': unit, 'status': 'ok' if ok else 'unavailable',
                        'reason': '' if ok else calculation.get('reason') or reason,
                        'period_end': period, 'basis': 'ttm' if key == 'cash_conversion' else basis,
                        'currency': currency, 'scope': scope, 'input_ids': inputs,
                        'formula': calculation.get('formula')})

    revenue_growth, profit_growth = yoy('revenue'), yoy('attributable_net_profit')
    add('revenue_yoy', '营业收入同比', revenue_growth)
    add('attributable_profit_yoy', '归母净利润同比', profit_growth)
    revenue, cost, net = raw('revenue'), raw('cost_of_revenue'), raw('net_profit')
    add('gross_margin', '毛利率', ratio(cost, revenue, 'gross_margin', subtract=True) if revenue and cost else None)
    add('net_margin', '净利率（合并净利润）' if scope == 'consolidated' else '净利率（母公司）',
        ratio(net, revenue, 'net_margin') if revenue and net else None)
    ttm = [r for r in analysis['ttm_records'] if r['status'] == 'ok' and r['period_end'] == period
           and r['currency'] == currency and r['scope'] == scope and r['symbol'] == payload.get('symbol')]
    cash = unique([r for r in ttm if r['metric'] == 'operating_cash_flow'])
    profit = unique([r for r in ttm if r['metric'] == 'net_profit'])
    conversion = None
    if cash and profit:
        conversion = {'status': 'blocked', 'reason': 'nonpositive_denominator',
                      'input_ids': [cash['id'], profit['id']], 'formula': 'OCF TTM / net profit TTM'}
        if number(profit['value']) > 0:
            with localcontext() as ctx:
                ctx.prec, ctx.rounding = 40, ROUND_HALF_EVEN
                value = number(cash['value']) / number(profit['value'])
                if number(value) is not None:
                    conversion.update(status='ok', value=numeric_string(value), reason='')
                else:
                    conversion['reason'] = 'abnormal_ratio_magnitude'
    add('cash_conversion', '现金兑现率（TTM）', conversion, unit='multiple')
    flags = []
    if revenue_growth and profit_growth and revenue_growth['status'] == profit_growth['status'] == 'ok':
        if number(revenue_growth['value']) > 0 and number(profit_growth['value']) <= 0:
            flags.append({'code': 'revenue_profit_divergence', 'message': '收入同比增长，归母净利润同比未增长；需核查成本、费用与业务结构。',
                          'input_ids': revenue_growth['input_ids'] + profit_growth['input_ids']})
    if conversion and conversion['status'] == 'ok' and number(conversion['value']) < 1:
        flags.append({'code': 'cash_below_profit', 'message': '经营现金流 TTM 低于同范围净利润 TTM；需核查营运资金与一次性项目，不直接断言财务质量差。',
                      'input_ids': conversion['input_ids']})
    inputs = {r['id']: r for r in analysis['records'] + analysis['quarter_records'] + analysis['ttm_records']}
    return {'schema_version': 1, 'symbol': payload.get('symbol'), 'as_of': str(cutoff), 'period_end': period,
            'basis': basis, 'currency': currency, 'scope': scope, 'factors': factors, 'flags': flags,
            'available_factors': sum(f['status'] == 'ok' for f in factors), 'total_factors': len(factors),
            'inputs': inputs, 'blocked_records': analysis['blocked_records'],
            'provenance': payload.get('provenance', 'provider_snapshot'),
            'policy': '日期级财务体检；无综合分、买卖信号或回测收益。未知披露日期不可用于体检；available_at 用于显式延迟可用版本。'}
