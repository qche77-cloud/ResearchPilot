"""Conservative financial row proposals; explicit confirmation before persistence."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone, date
from urllib.parse import urlsplit
from src.financial_analysis import LABELS, METRICS, STOCK_METRICS, identity, availability_date, number, analyze_financials
from src.stock_data import normalize_symbol

METHOD = 'pdf_financial_rows_v1'
ALIASES = {**LABELS, '归属于上市公司股东的净利润':'attributable_net_profit',
           '归属于母公司股东的净利润':'attributable_net_profit',
           '归属于上市公司股东的扣除非经常性损益的净利润':'attributable_profit_excluding_nonrecurring',
           '归属于上市公司股东的净资产':'attributable_net_assets'}


def extract_pdf(content):
    if not isinstance(content, bytes) or not content.startswith(b'%PDF') or len(content) > 12 * 1024 * 1024:
        raise ValueError('请选择不超过 12 MB 的 PDF 文件')
    try:
        run = subprocess.run([sys.executable, '-m', 'src.financial_import_worker'], input=content,
                             capture_output=True, timeout=45,cwd=Path(__file__).resolve().parents[1])
    except subprocess.TimeoutExpired as exc:
        raise ValueError('PDF 读取超时，请拆分文件后重试') from exc
    try:
        result = json.loads(run.stdout)
    except (ValueError, UnicodeError) as exc:
        raise ValueError('PDF 读取失败，请检查文件') from exc
    if run.returncode or result.get('error'):
        raise ValueError(result.get('error') or 'PDF 读取失败')
    return result['pages']


def propose_rows(pages, period_end):
    """Only exact metric labels followed by standalone numeric cells qualify.

    The first cell is a proposal for the user-selected period, never an automatic
    year/column assertion. Split labels are joined over at most three lines.
    Duplicate and conflicting candidates remain visible for explicit selection.
    """
    period = date.fromisoformat(period_end)
    if (period.month, period.day) not in {(3,31),(6,30),(9,30),(12,31)}:
        raise ValueError('请选择财报季末日期')
    rows = []
    for page in pages:
        lines = page['text'].splitlines()
        for i, line in enumerate(lines):
            for size in (1, 2, 3, 4, 5):
                excerpt = ' '.join(lines[i:i+size]).strip()
                match = re.match(r'^\s*(.+?)\s+([（(]?[-−]?\d[\d,]*(?:\.\d+)?[）)]?)(?:\s|$)', excerpt)
                if not match:
                    continue
                label = re.sub(r'\s|[（(](?:人民币)?(?:元|万元|亿元|%|％)[）)]', '', match[1])
                label = re.sub(r'^[一二三四五六七八九十]+[、.．]', '', label)
                metric = ALIASES.get(label)
                if not metric:
                    continue
                value = match[2].replace('−','-').replace(',','')
                if value.startswith(('(','（')):
                    value = '-' + value[1:-1]
                if number(value) is None:
                    continue
                context = '\n'.join(lines[max(0,i-12):i+size+2])
                units = re.findall(r'单位\s*[:：]\s*(?:人民币)?(亿元|万元|元)', page['text'])
                row = dict(metric=metric, label=METRICS[metric], value=value, page=page['page'],
                           excerpt=excerpt, context=context, period_end=period_end,
                           suggested_unit=units[0] if len(set(units)) == 1 else None,
                           suggested_scope='parent_company' if '母公司利润表' in context else None,
                           warning='请核对首列是否对应所选财报期、单位和报表范围')
                row['id'] = identity(row, 'PC')
                if not any(r['page']==row['page'] and r['metric']==metric and r['value']==value for r in rows):
                    rows.append(row)
                    # A clearly labelled annual current/prior header permits a
                    # second proposal. Preserve column evidence; user confirms.
                    header=re.search(r'主要会计数据\s+(20\d{2})\s*年\s+(20\d{2})\s*年',page['text'])
                    tail=excerpt[match.start(2):]
                    cells=re.findall(r'(?<![\d.])(?:[（(][-−]?\d[\d,]*\.\d+[）)]|[-−]?\d[\d,]*\.\d+)(?![\d.])',tail)
                    if header and period.month==12 and period.day==31 and int(header[1])==period.year and int(header[2])==period.year-1 and len(cells)>=2:
                        prior_value=cells[1].replace(',','').replace('−','-')
                        if prior_value.startswith(('(','（')): prior_value='-'+prior_value[1:-1]
                        prior=dict(row,value=prior_value,period_end=f'{header[2]}-12-31',
                                   warning='上一年列候选；请核对表头及是否经过重述')
                        prior['id']=identity(prior,'PC')
                        rows.append(prior)
                break
    return rows[:500]


def prepare_import(content, *, symbol, period_end, published_at, source_url, filename, extractor=None):
    normalize_symbol(symbol)
    published = availability_date(published_at)
    period = date.fromisoformat(period_end)
    url = urlsplit(source_url)
    if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password:
        raise ValueError('请填写原始财报的公开来源链接')
    if not published or not period <= published <= datetime.now(timezone.utc).date():
        raise ValueError('披露日期须在财报期末与今天之间')
    pages = (extractor or extract_pdf)(content)
    candidates = propose_rows(pages,period_end)
    if not candidates:
        raise ValueError('未提取到支持的财务行，请使用现有 JSON 导入；未保存任何数据')
    return dict(id=hashlib.sha256(content).hexdigest(), method=METHOD, symbol=symbol,
                filename=str(filename).replace('\\','/').split('/')[-1][:180],
                source_url=source_url, period_end=period_end, published_at=published_at,
                fetched_at=datetime.now(timezone.utc).isoformat(), page_count=len(pages),
                symbol_found=bool(re.search(r'(?<!\d)'+symbol+r'(?!\d)', '\n'.join(p['text'] for p in pages[:3]))),
                candidates=candidates, pages=pages)


def confirmed_payload(proposal, selections, *, unit, currency, scope, basis, confirmed):
    if confirmed is not True or not isinstance(selections,list) or not selections:
        raise ValueError('请逐项核对并确认所选数值、公司、报告期、币种及报表范围')
    if unit not in {'元','万元','亿元'} or currency not in {'CNY','USD','HKD','EUR'} or scope not in {'consolidated','parent_company'} or basis not in {'cumulative','single_quarter'}:
        raise ValueError('请明确单位、币种、报表范围和期间口径')
    candidates={r['id']:r for r in proposal['candidates']}
    if len(set(selections)) != len(selections) or any(k not in candidates for k in selections):
        raise ValueError('候选记录已变化，请重新选择')
    chosen=[candidates[k] for k in selections]
    if len({(r['metric'],r['period_end']) for r in chosen}) != len(chosen):
        raise ValueError('同一指标只能选择一条，冲突值请对照原文后选择')
    rows=[]
    for r in chosen:
        if r.get('suggested_unit') and r['metric']!='gross_margin' and r['suggested_unit']!=unit:
            raise ValueError('所选单位与原文标注不同，请按页面单位分别导入')
        if r.get('suggested_scope') and r['suggested_scope']!=scope:
            raise ValueError('所选报表范围与原文标题不同，请重新核对')
        rows.append(dict(symbol=proposal['symbol'],metric=r['metric'],value=r['value'],unit='%' if r['metric']=='gross_margin' else unit,
                         currency=currency,scope=scope,basis='instant' if r['metric'] in STOCK_METRICS else basis,
                         period_end=r['period_end'],published_at=proposal['published_at'],
                         available_at=proposal['published_at'],fetched_at=proposal['fetched_at'],
                         source_url=proposal['source_url'],document_sha256=proposal['id'],source_page=r['page'],
                         source_excerpt=r['excerpt'],confirmed_by='user',extraction_method=METHOD))
    payload=dict(symbol=proposal['symbol'],provenance='user_confirmed_pdf',fetched_at=proposal['fetched_at'],financial_records=rows,
                 document=dict(sha256=proposal['id'],filename=proposal['filename'],source_url=proposal['source_url'],
                               page_count=proposal['page_count'],method=METHOD))
    analysis=analyze_financials(payload)
    if analysis['blocked_records']:
        raise ValueError('所选数据未通过财务校验，请检查日期、数值和单位')
    return payload
