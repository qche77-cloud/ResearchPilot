"""A-share daily data adapter. No invented fallback prices."""
import json
import re
import requests
from datetime import datetime, timedelta


def data_error_message(exc):
    if isinstance(exc, requests.exceptions.Timeout):
        return '数据源响应超时，请稍后重试。'
    if isinstance(exc, requests.exceptions.ConnectionError):
        return '无法连接数据源，请检查网络或代理后重试。'
    if isinstance(exc, requests.exceptions.HTTPError):
        return '数据源暂时拒绝请求或服务异常，请稍后重试。'
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return '数据为空、格式变化或校验未通过，本次数据未采用。'
    return '更新未完成，请稍后重试；若持续失败，请检查服务日志。'


def normalize_symbol(symbol):
    code = symbol.strip()
    if not re.fullmatch(r'\d{6}', code):
        raise ValueError('请输入六位 A 股代码，例如 002837。')
    if code.startswith(('60', '68')):
        return code, 'SH'
    if code.startswith(('00', '30')):
        return code, 'SZ'
    if code.startswith(('4', '8', '92')):
        return code, 'BJ'
    raise ValueError('暂不支持该证券代码，请输入 A 股股票代码。')


def frame_records(frame):
    # Pandas JSON converts NaN/NaT to null; do not persist non-standard NaN JSON.
    return json.loads(frame.to_json(orient='records', force_ascii=False, date_format='iso'))


def fetch_stock(symbol):
    import akshare as ak
    code, exchange = normalize_symbol(symbol)
    end = datetime.now()
    start = end - timedelta(days=180)
    hist = ak.stock_zh_a_hist(symbol=code, period='daily', start_date=start.strftime('%Y%m%d'),
                             end_date=end.strftime('%Y%m%d'), adjust='', timeout=15)
    if hist is None or hist.empty:
        raise ValueError('数据源未返回日线，请检查股票代码或稍后重试。')
    needed = {'日期', '开盘', '收盘', '最高', '最低', '成交量'}
    if not needed.issubset(hist.columns):
        raise ValueError('日线数据源字段发生变化，已停止展示。')
    hist = hist.sort_values('日期').drop_duplicates('日期')
    if hist[['开盘', '收盘', '最高', '最低']].isna().any().any() or (hist[['开盘', '收盘', '最高', '最低']] <= 0).any().any():
        raise ValueError('日线存在缺失或非正价格，不能用于展示。')
    warnings = []
    info = []
    finance = []
    try:
        info = frame_records(ak.stock_individual_info_em(symbol=code, timeout=15))
    except Exception as exc:
        warnings.append(f'公司概况暂不可用：{type(exc).__name__}')
    try:
        # AKShare's current financial helper hardcodes the SH prefix. Use its
        # documented upstream endpoint with the actual exchange and a timeout.
        response = requests.get('https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022',
            params={'paperCode': exchange.lower() + code, 'source': 'gjzb', 'type': '0', 'page': '1', 'num': '8'}, timeout=15)
        response.raise_for_status()
        reports = response.json()['result']['data']['report_list']
        finance = [{'报告期': period, **item} for period, report in reports.items() for item in report['data']]
    except Exception as exc:
        warnings.append(f'财务摘要暂不可用：{type(exc).__name__}')
    return {'symbol': code, 'exchange': exchange, 'provider': 'AKShare / 东方财富（日线、概况）及新浪（财务摘要）',
            'adjustment': '不复权', 'price_unit': '人民币元', 'volume_unit': '手',
            'fetched_at': end.astimezone().isoformat(), 'daily': frame_records(hist),
            'info': info, 'finance': finance, 'warnings': warnings}


def changes(previous, current):
    old, new = previous['daily'][-1], current['daily'][-1]
    if old['日期'] == new['日期']:
        return '最新交易日期相同，本次刷新不构成新的日线变化。'
    close_old, close_new = float(old['收盘']), float(new['收盘'])
    if close_old <= 0:
        return '上次收盘价无效，无法计算变化。'
    return (f"从 {old['日期']} 到 {new['日期']}，不复权收盘价从 {close_old:.2f} 到 {close_new:.2f} 元，"
            f"变化 {(close_new / close_old - 1) * 100:+.2f}%。除权除息可能影响比较，不代表投资逻辑变化。")
