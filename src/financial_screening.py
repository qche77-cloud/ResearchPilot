"""Bounded financial filtering over supplied stock datasets; no data fetching."""
from src.financial_analysis import identity, number, numeric_string
from src.financial_quality import financial_quality
from src.stock_data import normalize_symbol

KEYS = {'revenue_yoy', 'attributable_profit_yoy', 'gross_margin', 'net_margin', 'cash_conversion'}


def screen_financials(payloads, *, as_of, minimums=None, basis='cumulative', currency='CNY', scope='consolidated'):
    if len(payloads) > 50:
        raise ValueError('一次最多筛选 50 家公司')
    minimums = minimums or {}
    if not set(minimums) <= KEYS or any(number(v) is None for v in minimums.values()):
        raise ValueError('筛选条件必须是支持指标的有限数值')
    thresholds = {k: numeric_string(number(v)) for k, v in minimums.items()}
    rows = []
    for symbol in sorted(payloads):
        normalize_symbol(symbol)
        payload = payloads[symbol]
        if payload.get('symbol') != symbol:
            raise ValueError('股票池与输入股票不一致')
        quality = financial_quality(payload, as_of=as_of, basis=basis, currency=currency, scope=scope)
        factors = {f['key']: f for f in quality['factors']}
        reasons = ['没有可计算指标'] if not quality['available_factors'] else []
        for key, threshold in thresholds.items():
            f = factors[key]
            if f['status'] != 'ok':
                reasons.append(f['label'] + '不可计算：' + f['reason'])
            elif number(f['value']) < number(threshold):
                reasons.append(f['label'] + '低于下限 ' + threshold)
        rows.append({'symbol': symbol, 'matched': not reasons, 'reasons': reasons, 'quality': quality})
    params = dict(as_of=str(as_of), basis=basis, currency=currency, scope=scope, minimums=thresholds)
    return {'id': identity([payloads, params], 'QS'), 'parameters': params, 'rows': rows,
            'matched_count': sum(r['matched'] for r in rows), 'stock_count': len(rows),
            'policy': '仅筛选给定股票池；无行业自动分类、收益回测、综合评分或交易执行；指标缺失不补零。'}
