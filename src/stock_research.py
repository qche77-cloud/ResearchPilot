"""Stock-scoped context, conservative dates and immutable update baselines."""
import json
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo
from src.stock_data import normalize_symbol


def is_listing_source(url):
    """Known rolling index pages are not dated individual announcements."""
    return bool(re.search(r'notices/stock/|vCB_AllBulletin/|vCB_AllNewsStock/|vCB_Bulletin/|/yjyg\.shtml', url or '', re.I))


def today():
    return datetime.now(ZoneInfo('Asia/Shanghai')).date()


def parse_date(value):
    value = str(value or '').strip()
    try:
        if re.fullmatch(r'\d{8}', value):
            return datetime.strptime(value, '%Y%m%d').date()
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def symbols_in(text, directory=()):
    result = set()
    for code in re.findall(r'(?<!\d)\d{6}(?!\d)', text):
        try:
            result.add(normalize_symbol(code)[0])
        except ValueError:
            pass
    for row in directory:
        if row['name'] and row['name'] in text:
            result.add(row['symbol'])
    return sorted(result)


def date_status(value, max_age, as_of=None):
    current = as_of or today()
    parsed = parse_date(value)
    if parsed is None:
        return '日期未知'
    age = (current - parsed).days
    if age < 0:
        return '日期异常（晚于当前日期）'
    return f'距今 {age} 天，需更新核查' if age > max_age else f'距今 {age} 天；不保证为最新'


def freshness(payload, as_of=None):
    daily = payload.get('daily') or []
    periods = sorted({str(r.get('报告期')) for r in payload.get('finance', []) if parse_date(r.get('报告期'))})
    trading = daily[-1].get('日期') if daily else None
    return {
        '检查日期': str(as_of or today()), '查询时间': payload.get('fetched_at', '未知'),
        '行情日期': trading or '未知', '行情时效': date_status(trading, 7, as_of),
        '财报期间': periods[-1] if periods else '未知',
        '财务时效': date_status(periods[-1] if periods else None, 180, as_of),
        '口径': '财报期间不是公告日期；单季/累计、币种和单位需核对，未知时不可直接比较。',
        '阈值说明': '7/180 天仅为日历日提醒阈值，不判断交易日、披露期限或数据是否最新。',
    }


def stock_history(store, repo, symbol):
    """Reuse explicit links and unambiguous legacy code-based history, no rewriting."""
    ids = {r['run_id'] for r in store.stock_runs(symbol)}
    offset = 0
    while True:
        batch = repo.list_runs(limit=100, offset=offset, topic_query=symbol)
        ids.update(r.run_id for r in batch if symbols_in(r.topic) == [symbol])
        if len(batch) < 100:
            break
        offset += 100
    states = [repo.get_state(rid) for rid in ids]
    return sorted((s for s in states if s), key=lambda s: str(s.created_at), reverse=True)


def attach_research(state, store, repo, symbol, update=False):
    a = state.diagnostics['agent']
    a['stock_symbol'] = symbol
    a['stock_profile'] = store.profile(symbol)
    a['stock_theses'] = store.theses(symbol)
    a['update_mode'] = update
    prior = next((s for s in stock_history(store, repo, symbol) if s.report and s.status == 'completed'), None)
    if update and prior:
        from src.report_links import snapshot_report
        version = snapshot_report(prior)
        summary = '；'.join(f.finding for f in (prior.synthesis.key_findings if prior.synthesis else [])[:2])
        a['baseline'] = {'run_id': prior.run_id, 'version': version,
                         'as_of': prior.diagnostics.get('agent', {}).get('report_as_of', str(prior.updated_at)),
                         'summary': summary[:700] or '旧报告暂无简述，请打开历史版本核对。',
                         'snapshot': prior.diagnostics['agent']['report_versions'][version],
                         'urls': [s.url for s in prior.sources]}
        a['prior_hypotheses'] = prior.diagnostics['agent']['report_versions'][version].get('hypotheses', [])
    context = {'当前日期': str(today()), '股票': symbol, '用户维护档案（非已核实事实）': a['stock_profile'],
               '投资假设': a['stock_theses'],
               '上次研究': {k: v for k, v in a.get('baseline', {}).items() if k not in {'snapshot', 'urls'}}}
    a['instructions'].append('研究背景：' + json.dumps(context, ensure_ascii=False)[:16000] +
        '\n优先交易所和公司公告，分清事实、推断和待验证信息。明确公告日期、财报期间、行情日期。'
        '未知单位或单季/累计口径不得强行比较。若为更新研究，只将有日期且晚于基线的资料称为新增；'
        '分别说明新增信息、对原判断的支持/削弱/证据不足、待核查事项。不把本次没搜到等同没有新公告。'
        '任何判断变更仅作为待确认建议，不覆盖用户档案。')


def update_brief(state):
    a = state.diagnostics['agent']
    baseline = a.get('baseline', {})
    since = parse_date(baseline.get('as_of'))
    candidates = [s for s in state.sources if not is_listing_source(s.url) and s.url not in baseline.get('urls', []) and
                  s.source_type not in {'market_data', 'financial_data'} and parse_date(s.published_date) and
                  since and since < parse_date(s.published_date) <= today()]
    if state.status not in {'completed', 'failed'}:
        finding = '更新尚未结束，请勿将中间结果视为最终结论。'
    elif state.status == 'failed':
        finding = '本次更新失败，不能据此判断没有新信息。'
    elif not since:
        finding = '无可用的上次报告基线，本次作为首次研究。'
    elif candidates:
        finding = f'检索到 {len(candidates)} 条日期晚于基线的新来源候选（发布日期仍需核对原文）。'
    else:
        finding = '本次未检索到日期可确认、晚于基线的新来源，不代表没有新公告。'
    excerpt = ''
    if state.status == 'completed' and state.synthesis:
        fresh_urls = {s.url for s in candidates}
        ids = {eid for eid, item in state.synthesis.evidence_index.items()
               if item.source.url in fresh_urls and item.document.read_status == 'success'}
        findings = [f.finding for f in state.synthesis.key_findings if set(f.evidence_ids) & ids and f.finding_type != 'gap']
        if findings:
            excerpt = '\n\n本轮有新来源支持的分析（待确认）：' + '；'.join(findings[:2])[:220]
    return (f'新增信息：{finding}\n\n判断变化：尚未自动确认；请核对报告中的支持、反例和推断，档案未被修改。'
            f'{excerpt}\n\n待确认：来源日期、财务口径及证据缺口。搜索 {a.get("searches", 0)}/{a.get("budget", 2)}，不保证穷尽。')


def followup_scope(state, message, store):
    a = state.diagnostics['agent']
    explicit = symbols_in(message, store.directory())
    original = symbols_in(state.topic, store.directory())
    bound = a.get('stock_symbol') or (original[0] if len(original) == 1 else None)
    if len(explicit) > 1 or (not explicit and not bound and len(original) > 1):
        return '这段对话涉及多家公司，请明确本次追问的股票名称或六位代码。'
    if explicit and bound and explicit[0] != bound:
        return f'当前对话绑定 {bound}。请为 {explicit[0]} 新建研究，避免混用现有报告与证据。'
    if explicit and not bound:
        return '现有研究未绑定单一个股，请从「个股与自选」为该公司新建研究。'
    if bound:
        a['stock_symbol'] = bound
        a['stock_profile'] = store.profile(bound)
        a['stock_theses'] = store.theses(bound)
        a.pop('market_data', None)
        cached = store.snapshots(bound, 1)
        a['freshness'] = freshness(cached[0]['payload'] if cached else {})
        if cached:
            payload = cached[0]['payload']
            a['market_data'] = {k: payload.get(k) for k in ['symbol', 'exchange', 'fetched_at', 'adjustment', 'price_unit']}
            a['market_data']['latest_daily'] = (payload.get('daily') or [None])[-1]
    return None
