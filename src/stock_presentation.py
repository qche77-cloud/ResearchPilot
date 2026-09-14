"""Stock lookup and conservative financial display; never infer missing units."""
import re
from decimal import Decimal, InvalidOperation
from src.stock_data import normalize_symbol


def search_directory(query, rows):
    query = query.strip().casefold()
    if not query:
        return []
    matches = [r for r in rows if query in r['symbol'].casefold() or query in r['name'].casefold()]
    return sorted(matches, key=lambda r: (query not in {r['symbol'].casefold(), r['name'].casefold()}, r['symbol']))[:30]


def financial_summary(rows, period):
    result = []
    seen = set()
    for row in rows:
        if str(row.get('报告期')) != period or row.get('item_value') in (None, ''):
            continue
        title = str(row.get('item_title', '')).strip()
        identity = (row.get('item_field') or title, str(row['item_value']))
        if not title or identity in seen:
            continue
        seen.add(identity)
        unit = str(row.get('item_unit') or '').strip()
        if not unit:
            match = re.search(r'[（(](亿元|万元|元/股|元|%|％|倍)[）)]', title)
            unit = match.group(1) if match else ''
        raw = str(row['item_value']).strip()
        try:
            number = Decimal(raw.replace(',', ''))
            if not number.is_finite():
                raise InvalidOperation()
            if unit in {'元', '万元', '亿元'}:
                yuan = number * {'元': 1, '万元': 10000, '亿元': 100000000}[unit]
                value = f'{yuan / Decimal(100000000):,.2f}'
                display_unit = '亿元'
            else:
                value = f'{number:,.4f}'.rstrip('0').rstrip('.')
                display_unit = unit or '单位待核对'
        except InvalidOperation:
            value, display_unit = raw, unit or '单位待核对'
        result.append({'报告期': period, '指标': title, '展示值': value, '单位': display_unit,
                       '原始值': raw, '单位依据': '源字段或指标名称' if unit else '数据源未明确提供，不换算'})
    return result


def fetch_directory():
    import akshare as ak
    frame = ak.stock_info_a_code_name()
    if not {'code', 'name'}.issubset(frame.columns):
        raise ValueError('股票目录字段发生变化')
    rows = []
    for item in frame.to_dict('records'):
        try:
            symbol, exchange = normalize_symbol(str(item['code']).zfill(6))
        except ValueError:
            continue
        rows.append({'symbol': symbol, 'name': str(item['name']), 'exchange': exchange})
    if not rows:
        raise ValueError('股票目录为空')
    return rows
