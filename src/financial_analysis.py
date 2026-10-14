"""Deterministic financial tools with explicit accounting basis and input lineage."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext, ROUND_HALF_EVEN
import hashlib
import json
import re
import math
from src.observability import traced_tool

METRICS = {
    'revenue': '营业收入', 'total_revenue': '营业总收入',
    'net_profit': '净利润', 'attributable_net_profit': '归母净利润',
    'cost_of_revenue': '营业成本', 'total_operating_cost': '营业总成本',
    'operating_cash_flow': '经营现金流', 'gross_margin': '毛利率',
    'net_assets': '净资产', 'attributable_net_assets': '归母净资产',
    'expense': '期间费用',
}
SOURCE_FIELDS = {'BIZTOTINCO': 'total_revenue', 'BIZINCO': 'revenue',
                 'PARENETP': 'attributable_net_profit', 'NETPROFIT': 'net_profit',
                 # Sina's total cost must NEVER be mistaken for cost of revenue.
                 'BIZTOTCOST': 'total_operating_cost', 'BIZCOST': 'cost_of_revenue',
                 'NETCASHOPERATE': 'operating_cash_flow'}
LABELS = {'营业收入': 'revenue', '营业总收入': 'total_revenue', '净利润': 'net_profit',
          '归母净利润': 'attributable_net_profit', '营业成本': 'cost_of_revenue',
          '营业总成本': 'total_operating_cost', '经营现金流量净额': 'operating_cash_flow',
          '经营活动产生的现金流量净额': 'operating_cash_flow', '毛利率': 'gross_margin',
          '股东权益合计(净资产)': 'net_assets', '净资产': 'net_assets',
          '归母净资产': 'attributable_net_assets', '期间费用': 'expense'}
MONEY_UNITS = {'元': Decimal(1), '万元': Decimal(10000), '亿元': Decimal(100000000),
               'yuan': Decimal(1), 'thousand': Decimal(1000), 'million': Decimal(1000000)}
STOCK_METRICS = {'net_assets', 'attributable_net_assets'}
QUARTER_ENDS = {(3, 31): 1, (6, 30): 2, (9, 30): 3, (12, 31): 4}


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def identity(value, prefix='F'):
    encoded = json.dumps(json_safe(value), sort_keys=True, ensure_ascii=False, allow_nan=False, default=str).encode()
    return prefix + hashlib.sha256(encoded).hexdigest()[:20]


def number(value):
    if value is None or isinstance(value, bool) or str(value).strip() in {'', '-', '--', 'N/A', 'None'}:
        return None
    try:
        result = Decimal(str(value).replace(',', '').strip())
        if not result.is_finite() or len(result.as_tuple().digits) > 100 or abs(result.as_tuple().exponent) > 100:
            return None
        return result if result.copy_abs() <= Decimal('1e25') else None
    except InvalidOperation:
        return None


def numeric_string(value):
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def parse_period(value):
    text = str(value or '').strip()[:10]
    try:
        return date.fromisoformat(text) if '-' in text else date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except (ValueError, TypeError):
        return None


def quarter_start(end):
    quarter = QUARTER_ENDS.get((end.month, end.day))
    return date(end.year, 3 * quarter - 2, 1) if quarter else None


def availability_date(value):
    """Strict ISO date/datetime for observation metadata, unlike provider periods."""
    if value is None or value == '':
        return None
    try:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).date()
    except (ValueError, TypeError):
        return None


def normalize_financials(payload, *, as_of=None):
    """Accept canonical records or legacy Sina rows plus user-verified metadata.

    Historical values are never reinterpreted from an undocumented provider
    assumption. Verification metadata is explicit and retained in each record.
    """
    meta = payload.get('finance_metadata') or {}
    cutoff = availability_date(as_of) if as_of is not None else None
    if as_of is not None and cutoff is None:
        raise ValueError('as_of must be an ISO date or datetime')
    verified = meta.get('verified') is True and bool(meta.get('basis_evidence'))
    rows = payload.get('financial_records', payload.get('finance', []))
    records = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get('item_title', '')).strip()
        cleaned_title = re.sub(r'[（(](?:人民币)?(?:亿元|万元|元|%|％)[）)]', '', title).strip()
        metric = raw.get('metric') or SOURCE_FIELDS.get(raw.get('item_field')) or LABELS.get(cleaned_title)
        if metric not in METRICS:
            continue
        symbol = str(raw.get('symbol') or payload.get('symbol') or '')
        end = parse_period(raw.get('period_end') or raw.get('报告期'))
        currency = raw.get('currency') or (meta.get('currency') if verified else None)
        unit = raw.get('unit') or raw.get('item_unit')
        if not unit:
            match = re.search(r'[（(](?:人民币)?(亿元|万元|元|%|％)[）)]', title)
            unit = match[1] if match else None
        if not unit and verified and metric != 'gross_margin':
            unit = meta.get('money_unit')
        basis = raw.get('basis') or (('instant' if metric in STOCK_METRICS else meta.get('flow_basis')) if verified else None)
        scope = raw.get('scope') or (meta.get('scope') if verified else None)
        value = number(raw.get('value', raw.get('item_value')))
        issues = []
        if payload.get('symbol') and symbol != str(payload['symbol']):
            issues.append('symbol_mismatch')
        if raw.get('metric') and raw.get('item_field') in SOURCE_FIELDS and raw['metric'] != SOURCE_FIELDS[raw['item_field']]:
            issues.append('metric_definition_conflict')
        if not symbol:
            issues.append('missing_symbol')
        if not end or (end.month, end.day) not in QUARTER_ENDS:
            issues.append('invalid_reporting_period')
        if currency not in {'CNY', 'USD', 'HKD', 'EUR'}:
            issues.append('unknown_currency')
        if scope not in {'consolidated', 'parent_company'}:
            issues.append('unknown_accounting_scope')
        if basis not in ({'instant'} if metric in STOCK_METRICS else {'single_quarter', 'cumulative'}):
            issues.append('unknown_period_basis')
        if value is None:
            issues.append('missing_or_invalid_value')
        canonical_unit = 'percent' if metric == 'gross_margin' else 'currency_unit'
        with localcontext() as ctx:
            ctx.prec = 40
            ctx.rounding = ROUND_HALF_EVEN
            if metric == 'gross_margin':
                if unit not in {'%', '％', 'percent'}:
                    issues.append('unknown_unit')
                elif value is not None and value > 100:
                    issues.append('abnormal_margin')
            elif unit not in MONEY_UNITS:
                issues.append('unknown_unit')
            elif value is not None:
                value *= MONEY_UNITS[unit]
                if number(value) is None:
                    value = None
                    issues.append('abnormal_amount_magnitude')
        start = parse_period(raw.get('period_start'))
        expected_start = (date(end.year, 1, 1) if basis == 'cumulative' else quarter_start(end)) if end else None
        if basis == 'instant':
            expected_start = end
        if start and expected_start and start != expected_start:
            issues.append('invalid_period_start')
        source_url = raw.get('source_url') or payload.get('finance_source_url')
        if not source_url:
            source_url = f'https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_FinanceSummary/stockid/{symbol}.phtml' if 'item_field' in raw else None
        fetched_at = raw.get('fetched_at') or payload.get('fetched_at')
        fetched_day = availability_date(fetched_at)
        if not source_url or not str(source_url).startswith(('https://', 'http://')):
            issues.append('missing_source')
        if not fetched_at:
            issues.append('missing_update_time')
        else:
            try:
                datetime.fromisoformat(str(fetched_at).replace('Z', '+00:00'))
                fetched_day = parse_period(fetched_at)
                if end and fetched_day and end > fetched_day:
                    issues.append('future_reporting_period')
            except ValueError:
                issues.append('invalid_update_time')
        published = availability_date(raw.get('published_at'))
        available = availability_date(raw.get('available_at')) if raw.get('available_at') else published
        if raw.get('published_at') and published is None:
            issues.append('invalid_publication_date')
        if raw.get('available_at') and available is None:
            issues.append('invalid_availability_date')
        if published and end and published < end:
            issues.append('publication_before_period_end')
        if published and fetched_day and published > fetched_day:
            issues.append('publication_after_fetch')
        if available and published and available < published:
            issues.append('availability_before_publication')
        if available and fetched_day and available > fetched_day:
            issues.append('availability_after_fetch')
        if cutoff:
            if not published or not available:
                issues.append('publication_required_for_as_of')
            elif available > cutoff:
                issues.append('not_available_as_of')
            if end and end > cutoff:
                issues.append('report_period_after_as_of')
        record = {'id': identity([symbol, raw, fetched_at]), 'symbol': symbol, 'metric': metric,
                  'label': METRICS[metric], 'value': numeric_string(value) if value is not None else None,
                  'unit': canonical_unit, 'raw_unit': unit, 'currency': currency, 'basis': basis,
                  'scope': scope, 'period_start': str(start or expected_start) if start or expected_start else None,
                  'period_end': str(end) if end else str(raw.get('period_end') or raw.get('报告期') or ''),
                  'source_url': source_url, 'fetched_at': fetched_at, 'raw': json_safe(dict(raw)),
                  'published_at': raw.get('published_at'),
                  'available_at': raw.get('available_at') or raw.get('published_at'),
                  'metadata_evidence': meta.get('basis_evidence') if verified else 'explicit_source_fields',
                  'status': 'ok' if not issues else 'blocked', 'issues': issues, 'input_ids': []}
        if value is not None and metric in {'revenue', 'total_revenue', 'cost_of_revenue', 'total_operating_cost'} and value < 0:
            record['status'] = 'blocked'
            record['issues'].append('abnormal_negative_amount')
        records.append(record)
    # An identical duplicate is harmless; conflicting rows with the same scope
    # cannot be resolved by taking the last row or asking an LLM to choose.
    deduped = {r['id']: r for r in records}
    groups = {}
    for r in deduped.values():
        if r['status'] != 'ok':
            continue
        key = tuple(r[k] for k in ('symbol', 'metric', 'period_end', 'currency', 'basis', 'scope'))
        groups.setdefault(key, []).append(r)
    for group in groups.values():
        if len({r['value'] for r in group}) > 1:
            for r in group:
                r['status'] = 'blocked'
                r['issues'].append('conflicting_duplicate')
    return sorted(deduped.values(), key=lambda r: (r['period_end'], r['metric'], r['id']))


def _key(record):
    return tuple(record[k] for k in ('symbol', 'metric', 'currency', 'scope', 'unit'))


def single_quarters(records):
    """Convert cumulative flows by adjacent YTD subtraction within one year."""
    results = []
    for row in records:
        if row['basis'] == 'instant':
            continue
        if row['basis'] == 'single_quarter' or row['status'] != 'ok':
            results.append(dict(row))
            continue
        end = parse_period(row['period_end'])
        previous_month = end.month - 3
        candidates = [r for r in records if _key(r) == _key(row) and r['basis'] == 'cumulative'
                      and r['period_end'] == str(date(end.year, previous_month, 30 if previous_month in {6, 9} else 31))] if previous_month else []
        derived = dict(row, id=identity([row['id'], 'single_quarter'], 'D'), basis='single_quarter',
                       period_start=str(quarter_start(end)), input_ids=[row['id']], formula='Q1 = YTD Q1')
        if row['metric'] == 'gross_margin':
            derived.update(status='blocked', value=None, issues=['ratio_cannot_be_differenced'])
            results.append(derived)
            continue
        if previous_month:
            good = [r for r in candidates if r['status'] == 'ok']
            if len(good) != 1:
                derived.update(status='blocked', value=None, issues=['missing_or_ambiguous_previous_cumulative'])
            else:
                previous = good[0]
                with localcontext() as ctx:
                    ctx.prec = 40
                    ctx.rounding = ROUND_HALF_EVEN
                    derived['value'] = numeric_string(number(row['value']) - number(previous['value']))
                derived['input_ids'].append(previous['id'])
                derived['formula'] = 'quarter = current YTD - preceding YTD'
                publications = [parse_period(r.get('published_at')) for r in (row, previous)]
                derived['published_at'] = str(max(publications)) if all(publications) else None
                available_dates = [availability_date(r.get('available_at')) for r in (row, previous)]
                derived['available_at'] = str(max(available_dates)) if all(available_dates) else None
                derived_number = number(derived['value'])
                if derived_number is None:
                    derived.update(status='blocked', issues=['abnormal_derived_magnitude'])
                elif derived_number < 0 and row['metric'] in {'revenue', 'total_revenue', 'cost_of_revenue', 'total_operating_cost'}:
                    derived.update(status='blocked', issues=['abnormal_negative_derived_amount'])
        results.append(derived)
    return results


def growth(current, previous, mode='yoy'):
    result = {'id': identity([current['id'], previous['id'] if previous else None, mode], 'C'),
              'metric': current['metric'], 'symbol': current['symbol'], 'period_end': current['period_end'],
              'basis': current['basis'], 'kind': mode, 'value': None, 'unit': 'percent',
              'currency': current['currency'], 'scope': current['scope'],
              'comparison_period': previous['period_end'] if previous else None,
              'input_ids': [current['id']] + ([previous['id']] if previous else []),
              'formula': '(current - previous) / previous * 100', 'status': 'blocked', 'reason': ''}
    if previous is None:
        result['reason'] = 'missing_comparison_period'
        return result
    if current['status'] != 'ok' or previous['status'] != 'ok':
        result['reason'] = 'invalid_input'
        return result
    if _key(current) != _key(previous) or current['basis'] != previous['basis']:
        result['reason'] = 'incomparable_scope'
        return result
    cend, pend = parse_period(current['period_end']), parse_period(previous['period_end'])
    if mode == 'yoy':
        valid = cend.year == pend.year + 1 and (cend.month, cend.day) == (pend.month, pend.day)
    elif mode == 'qoq':
        valid = current['basis'] == 'single_quarter' and cend.year * 4 + QUARTER_ENDS[(cend.month, cend.day)] == pend.year * 4 + QUARTER_ENDS[(pend.month, pend.day)] + 1
    else:
        raise ValueError('mode must be yoy or qoq')
    if not valid or current['metric'] == 'gross_margin':
        result['reason'] = 'incomparable_period_or_ratio'
        return result
    base = number(previous['value'])
    if base <= 0:
        result['reason'] = 'zero_base' if base == 0 else 'negative_base_not_conventional_growth'
        return result
    with localcontext() as ctx:
        ctx.prec = 40
        ctx.rounding = ROUND_HALF_EVEN
        computed = (number(current['value']) - base) / base * 100
        if number(computed) is None:
            result['reason'] = 'abnormal_growth_magnitude'
        else:
            result.update(value=numeric_string(computed), status='ok')
    return result


def ratio(numerator, denominator, metric, subtract=False):
    result = {'id': identity([numerator['id'], denominator['id'], metric], 'C'), 'metric': metric,
              'symbol': denominator['symbol'], 'period_end': denominator['period_end'], 'basis': denominator['basis'],
              'kind': 'ratio', 'value': None, 'unit': 'percent', 'input_ids': [numerator['id'], denominator['id']],
              'formula': '(revenue - cost_of_revenue) / revenue * 100' if subtract else 'numerator / denominator * 100',
              'status': 'blocked', 'reason': 'incomparable_scope'}
    keys = ('symbol', 'currency', 'scope', 'basis', 'period_start', 'period_end', 'unit')
    if any(numerator[k] != denominator[k] for k in keys) or any(r['status'] != 'ok' for r in (numerator, denominator)):
        return result
    if subtract and (numerator['metric'] != 'cost_of_revenue' or denominator['metric'] != 'revenue'):
        result['reason'] = 'gross_margin_requires_revenue_and_cost_of_revenue'
        return result
    base = number(denominator['value'])
    if base <= 0:
        result['reason'] = 'nonpositive_denominator'
        return result
    with localcontext() as ctx:
        ctx.prec = 40
        ctx.rounding = ROUND_HALF_EVEN
        value = number(numerator['value']) / base * 100
        value = 100 - value if subtract else value
        if number(value) is None:
            result['reason'] = 'abnormal_ratio_magnitude'
        else:
            result.update(value=numeric_string(value), status='ok', reason='')
    return result


def valuation(market, denominator, kind):
    """PE uses parent-attributable TTM/annual profit; PB uses parent net assets."""
    if kind not in {'pe', 'pb'}:
        raise ValueError('kind must be pe or pb')
    result = {'id': identity([market, denominator, kind], 'V'), 'kind': kind, 'value': None, 'unit': 'multiple',
              'formula': 'market_cap / attributable_' + ('profit' if kind == 'pe' else 'net_assets'),
              'input_ids': [market.get('id'), denominator.get('id')], 'status': 'blocked', 'reason': 'incomparable_scope'}
    if any(not market.get(k) or market.get(k) != denominator.get(k) for k in ('symbol', 'currency')):
        return result
    market_date, report_date = availability_date(market.get('as_of')), parse_period(denominator.get('period_end'))
    if not market_date or not report_date or report_date > market_date or not str(market.get('source_url', '')).startswith(('https://', 'http://')):
        result['reason'] = 'invalid_valuation_date_or_source'
        return result
    published = availability_date(denominator.get('published_at'))
    available = availability_date(denominator.get('available_at') or denominator.get('published_at'))
    if not published or not available or published > market_date or available > market_date:
        result['reason'] = 'publication_date_required_for_point_in_time_valuation'
        return result
    expected = 'attributable_net_profit' if kind == 'pe' else 'attributable_net_assets'
    if denominator.get('metric') != expected or denominator.get('status') != 'ok' or denominator.get('scope') != 'consolidated':
        return result
    if kind == 'pe' and not (denominator.get('basis') == 'ttm' or denominator.get('basis') == 'cumulative' and report_date.month == 12):
        result['reason'] = 'pe_requires_ttm_or_annual_profit'
        return result
    if kind == 'pb' and denominator.get('basis') != 'instant':
        return result
    base, cap = number(denominator.get('value')), number(market.get('value'))
    scale = MONEY_UNITS.get(market.get('unit'))
    if base is None or cap is None or scale is None or base <= 0 or cap <= 0:
        result['reason'] = 'missing_or_nonpositive_value_or_unknown_unit'
        return result
    with localcontext() as ctx:
        ctx.prec = 40
        ctx.rounding = ROUND_HALF_EVEN
        computed = cap * scale / base
        if number(computed) is None:
            result['reason'] = 'abnormal_valuation_magnitude'
        else:
            result.update(value=numeric_string(computed), status='ok', reason='',
                          valuation_date=str(market_date), financial_period=str(report_date))
    return result


@traced_tool('financial.analyze')
def analyze_financials(payload, *, as_of=None):
    records = normalize_financials(payload, as_of=as_of)
    quarters = single_quarters(records)
    computations = []
    candidates = records + [q for q in quarters if q['id'] not in {r['id'] for r in records}]
    for row in candidates:
        end = parse_period(row['period_end'])
        if not end or row['basis'] == 'instant':
            continue
        for mode in ('yoy', 'qoq'):
            if mode == 'qoq' and row['basis'] != 'single_quarter':
                continue
            if mode == 'yoy':
                wanted = str(date(end.year - 1, end.month, end.day))
            else:
                year, month = (end.year - 1, 12) if end.month == 3 else (end.year, end.month - 3)
                wanted = str(date(year, month, 30 if month in {6, 9} else 31))
            previous = [r for r in candidates if _key(r) == _key(row) and r['basis'] == row['basis'] and r['period_end'] == wanted]
            computations.append(growth(row, previous[0] if len(previous) == 1 else None, mode))
    for revenue in [r for r in candidates if r['metric'] == 'revenue' and r['status'] == 'ok']:
        for metric, result_metric, subtract in [('cost_of_revenue', 'gross_margin', True), ('expense', 'expense_ratio', False), ('net_profit', 'net_margin', False)]:
            matches = [r for r in candidates if r['metric'] == metric and r['period_end'] == revenue['period_end'] and r['basis'] == revenue['basis'] and r['scope'] == revenue['scope']]
            if len(matches) == 1:
                computations.append(ratio(matches[0], revenue, result_metric, subtract))
    result = {'schema_version': 1, 'symbol': payload.get('symbol'), 'fetched_at': payload.get('fetched_at'),
            'as_of': str(availability_date(as_of)) if as_of is not None else None,
            'records': records, 'quarter_records': quarters, 'computations': computations,
            'ttm_records': trailing_twelve_months(quarters),
            'usable_records': sum(r['status'] == 'ok' for r in records),
            'blocked_records': sum(r['status'] != 'ok' for r in records),
            'sources': sorted({r['source_url'] for r in records if r['source_url']}),
            'calculation_policy': 'Decimal precision=40; explicit currency/unit/basis/scope; negative bases return unknown'}
    market = payload.get('market_valuation')
    if isinstance(market, dict):
        market = dict(market)
        market.setdefault('id', identity(market, 'M'))
    result['market_input'] = market if isinstance(market, dict) else None
    result['valuations'] = []
    if isinstance(market, dict):
        for kind, metric in [('pe', 'attributable_net_profit'), ('pb', 'attributable_net_assets')]:
            market_day = availability_date(market.get('as_of'))
            eligible = [r for r in records + result['ttm_records'] if r['metric'] == metric and r['status'] == 'ok'
                        and r['symbol'] == market.get('symbol') and r['currency'] == market.get('currency')
                        and r['scope'] == 'consolidated'
                        and (kind == 'pb' and r['basis'] == 'instant' or kind == 'pe' and
                             (r['basis'] == 'ttm' or r['basis'] == 'cumulative' and parse_period(r['period_end']).month == 12))]
            available = [r for r in eligible if market_day and availability_date(r.get('available_at') or r.get('published_at'))
                         and availability_date(r.get('available_at') or r.get('published_at')) <= market_day
                         and parse_period(r['period_end']) <= market_day]
            eligible = available or eligible  # Preserve explicit blocked reasons if nothing was publicly available.
            if eligible:
                chosen = max(eligible, key=lambda r: (r['period_end'], r['basis'] == 'ttm'))
                result['valuations'].append(valuation(market, chosen, kind))
    return result


def chart_points(analysis, metric, basis):
    rows = analysis['quarter_records'] if basis == 'single_quarter' else analysis['records']
    return [{'period': r['period_end'], 'metric': r['metric'], 'basis': r['basis'], 'currency': r['currency'],
             'scope': r['scope'], 'unit': r['unit'], 'value': r['value'], 'record_id': r['id'],
             'input_ids': r['input_ids'] or [r['id']], 'source_url': r['source_url'], 'fetched_at': r['fetched_at']}
            for r in rows if r['metric'] == metric and r['basis'] == basis and r['status'] == 'ok']


def financial_evidence(analysis):
    """Paste-ready structured corpus, not values to be recalculated by an LLM."""
    inputs = {r['id']: r for r in analysis['records'] + analysis['quarter_records'] + analysis.get('ttm_records', [])}
    if analysis.get('market_input'):
        market = analysis['market_input']
        inputs[market['id']] = market
    computations = [c for c in analysis['computations'] + analysis.get('valuations', []) if c['status'] == 'ok']
    return {'symbol': analysis['symbol'], 'fetched_at': analysis['fetched_at'], 'as_of': analysis.get('as_of'),
            'inputs': inputs, 'calculations': computations,
            'blocked': [{'id': r['id'], 'issues': r['issues']} for r in analysis['records'] if r['status'] != 'ok'],
            'policy': '只能引用这些已计算数值；未知单位、币种、口径或缺失值不可推断；所有计算保留 input_ids 和 formula。'}


def trailing_twelve_months(quarters):
    result = []
    for current in quarters:
        if current['status'] != 'ok' or current['metric'] == 'gross_margin':
            continue
        end = parse_period(current['period_end'])
        periods = []
        for offset in range(4):
            qnumber = end.year * 4 + QUARTER_ENDS[(end.month, end.day)] - 1 - offset
            year, q = divmod(qnumber, 4)
            month = (q + 1) * 3
            periods.append(str(date(year, month, 30 if month in {6, 9} else 31)))
        rows = []
        for period in periods:
            matches = [r for r in quarters if r['status'] == 'ok' and _key(r) == _key(current) and r['basis'] == 'single_quarter' and r['period_end'] == period]
            if len(matches) != 1:
                break
            rows.append(matches[0])
        if len(rows) != 4:
            continue
        with localcontext() as ctx:
            ctx.prec = 40
            ctx.rounding = ROUND_HALF_EVEN
            total = sum((number(r['value']) for r in rows), Decimal(0))
        publications = [parse_period(r.get('published_at')) for r in rows]
        available_dates = [availability_date(r.get('available_at')) for r in rows]
        result.append(dict(current, id=identity([r['id'] for r in rows], 'T'), value=numeric_string(total),
                           basis='ttm', period_start=rows[-1]['period_start'], input_ids=[r['id'] for r in rows],
                           status='ok' if number(total) is not None else 'blocked',
                           published_at=str(max(publications)) if all(publications) else None,
                           available_at=str(max(available_dates)) if all(available_dates) else None,
                           formula='TTM = sum of four consecutive single quarters'))
    return result


def agent_financial_summary(analysis):
    return {'symbol': analysis.get('symbol'), 'fetched_at': analysis.get('fetched_at'),
            'usable_records': analysis['usable_records'], 'blocked_records': analysis['blocked_records'],
            'recent_calculations': sorted([c for c in analysis['computations'] if c['status'] == 'ok'],
                                           key=lambda c: c['period_end'], reverse=True)[:16],
            'valuations': analysis.get('valuations', []),
            'quality': analysis.get('quality'),
            'sources': analysis['sources'], 'policy': analysis['calculation_policy']}


def attach_financial_analysis(state, payload):
    from src.models import Source, EvidenceDocument
    analysis = analyze_financials(payload)
    state.diagnostics['financial_analysis'] = analysis
    groups = {}
    for row in analysis['records'] + analysis['quarter_records']:
        if row['status'] == 'ok':
            groups.setdefault((row['metric'], row['basis'], row['currency'], row['scope']), {})[row['id']] = row
    for (metric, basis, currency, scope), grouped in groups.items():
        rows = sorted(grouped.values(), key=lambda r: r['period_end'])
        row_ids = set(grouped)
        calculations = [c for c in analysis['computations'] if c['basis'] == basis and c['status'] == 'ok' and
                        (c['metric'] == metric or c['metric'] in {'gross_margin', 'expense_ratio', 'net_margin'} and any(i in row_ids for i in c['input_ids']))]
        content = {'symbol': payload['symbol'], 'metric': metric, 'label': METRICS[metric], 'basis': basis,
                   'currency': currency, 'scope': scope, 'source_url': rows[-1]['source_url'],
                   'fetched_at': rows[-1]['fetched_at'], 'origin': payload.get('provenance', 'provider_snapshot'),
                   'calculations': sorted(calculations, key=lambda c: c['period_end'], reverse=True),
                   'values': [{k: r[k] for k in ('id', 'value', 'unit', 'period_start', 'period_end', 'input_ids')} for r in rows],
                   'ttm_values': [r for r in analysis['ttm_records'] if r['metric'] == metric and r['status'] == 'ok'],
                   'policy': '数值由 Python 计算，引用 input_ids 可追溯；获取时间不等于财报发布日期。'}
        text = json.dumps(content, ensure_ascii=False)
        sid = f'S{len(state.sources) + 1}'
        published = rows[-1].get('published_at')
        source = Source(f'{payload["symbol"]} {METRICS[metric]}：{basis}（结构化财务）', rows[-1]['source_url'],
                        text[:300], 'financial_calculation', 1, source_id=sid, research_task='financial_data',
                        published_date=str(published)[:10] if published else None)
        state.sources.append(source)
        state.documents.append(EvidenceDocument(source, text, len(text.split()), 'success', extraction_status='FULL_TEXT',
                                               extracted_char_count=len(text)))
    valid_valuations = [v for v in analysis.get('valuations', []) if v['status'] == 'ok']
    if valid_valuations:
        text = json.dumps({'symbol': payload['symbol'], 'market_input': analysis['market_input'],
                           'valuations': valid_valuations, 'policy': '由 Python 根据明确市值时点和已披露财务口径计算'}, ensure_ascii=False)
        source = Source(f'{payload["symbol"]} 基础估值计算', payload['market_valuation']['source_url'], text[:300],
                        'financial_calculation', 1, source_id=f'S{len(state.sources)+1}', research_task='financial_data')
        state.sources.append(source)
        state.documents.append(EvidenceDocument(source, text, len(text.split()), 'success', extraction_status='FULL_TEXT'))
    from src.financial_quality import financial_quality
    if availability_date(payload.get('fetched_at')):
        quality = financial_quality(payload)
        state.diagnostics['financial_quality'] = quality
        analysis['quality'] = {k: quality[k] for k in ('as_of', 'period_end', 'factors', 'flags', 'available_factors', 'policy')}
        if quality['available_factors']:
            text = json.dumps(dict(label='财务质量', **quality), ensure_ascii=False)
            source = Source(f'{payload["symbol"]} 财务质量体检（确定性计算）', analysis['sources'][0],
                            text[:300], 'financial_calculation', 1, source_id=f'S{len(state.sources)+1}', research_task='financial_data')
            state.sources.append(source)
            state.documents.append(EvidenceDocument(source, text, len(text.split()), 'success', extraction_status='FULL_TEXT'))
    return analysis


def bind_financial_tasks(state):
    if not state.plan:
        return
    for source in state.sources:
        if source.source_type != 'financial_calculation':
            continue
        document = next((d for d in state.documents if d.source.source_id == source.source_id), None)
        if not document:
            continue
        content = json.loads(document.extracted_text)
        label = content.get('label', '估值')
        candidates = [s for s in state.plan.steps if label in s.title + s.description or
                      any(k in s.title + s.description for k in ('财务', '业绩', '现金流', '利润', '收入'))]
        source.research_task = (candidates or state.plan.steps)[0].title if state.plan.steps else 'financial_data'
