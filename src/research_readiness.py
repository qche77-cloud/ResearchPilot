"""Read-only checks of saved financial versions; never initialize a workbench."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
import json
from urllib.parse import urlparse

from src.financial_analysis import analyze_financials
from src.research_signals import DEFAULT_RULES, day, digest, score_archive, score_financials

MAX_BYTES = 2 * 1024 * 1024


def instant(value):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise ValueError('本机保存时间须为带时区的 ISO 时间戳') from None


def synthetic(payload):
    if not isinstance(payload, dict):
        return False
    markers = ('synthetic', 'fixture', 'demo', '虚构', '合成')
    rows = payload.get('financial_records') or []
    if any(marker in str(payload.get('provenance', '')).lower() for marker in markers):
        return True
    for row in rows if isinstance(rows,list) else []:
        if isinstance(row, dict):
            if any(marker in str(row.get('provenance', '')).lower() for marker in markers):
                return True
            host = (urlparse(str(row.get('source_url', ''))).hostname or '').lower()
            if host == 'invalid' or host.endswith('.invalid'):
                return True
    return False


def dataset_row(db, symbol, dataset_id):
    row = db.execute('SELECT id,symbol,created,payload FROM financial_inputs WHERE symbol=? AND id=?',
                     (symbol, dataset_id)).fetchone()
    if row is None:
        raise ValueError('指定财务版本不存在，不能使用最新数据替代')
    if len(row['payload'].encode('utf-8')) > MAX_BYTES:
        raise ValueError('财务版本超过 2 MB，暂不支持登记')
    try:
        return dict(row, payload=json.loads(row['payload']))
    except (ValueError, TypeError):
        raise ValueError('财务版本内容无法读取') from None


class ReadOnlyWorkbench:
    """Query an existing file using SQLite mode=ro, without DDL or mkdir."""
    def __init__(self, path):
        self.path = Path(path).resolve()

    @contextmanager
    def connect(self):
        if not self.path.is_file():
            raise ValueError('本机工作台尚不存在；请先在电脑端保存真实财务资料')
        import sqlite3
        db = None
        try:
            db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=20)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            yield db
        except sqlite3.Error:
            raise ValueError('本机工作台暂不可读取，请确认资料库格式和访问权限') from None
        finally:
            if db is not None:
                db.close()

    def watches(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT symbol,name,created FROM watchlist ORDER BY symbol LIMIT 50')]

    def financial_versions(self, symbol, limit=30):
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError('版本读取数量须为 1–100')
        with self.connect() as db:
            keys = [row['id'] for row in db.execute(
                'SELECT id FROM financial_inputs WHERE symbol=? ORDER BY created DESC,rowid DESC LIMIT ?', (symbol,limit))]
            return [dataset_row(db,symbol,key) for key in keys]

    def financial_version(self, symbol, dataset_id):
        with self.connect() as db:
            return dataset_row(db,symbol,dataset_id)


def audit_version(record, *, as_of, rules=None):
    """A data-readiness check, not source authenticity or investment certification."""
    cutoff = day(as_of)
    if not isinstance(record,dict) or not isinstance(record.get('payload'),dict):
        raise ValueError('需要完整保存的财务版本')
    payload = record['payload']
    problems = []
    def issue(code, message, severity='error'):
        problems.append({'code':code,'message':message,'severity':severity})
    saved = None
    try:
        saved = instant(record.get('created'))
        if day(saved) > cutoff:
            issue('saved_after_cutoff','该版本在所选日期之后才保存')
    except ValueError:
        issue('invalid_saved_time','缺少有效的本机版本保存时间')
    if payload.get('symbol') != record.get('symbol'):
        issue('symbol_mismatch','财务版本与公司代码不一致')
    is_synthetic = synthetic(payload)
    if is_synthetic:
        issue('synthetic_input','此版本带有虚构标识或演示来源，不能登记到真实账本')
    rows = payload.get('financial_records')
    analysis = score = None
    if not isinstance(rows,list) or not rows or len(rows)>1000:
        issue('canonical_records_required','需要 1–1000 条已核对口径的标准财务记录')
    else:
        for row in [payload,*rows]:
            if not isinstance(row,dict):
                issue('invalid_record','存在无法读取的财务记录')
                continue
            fetched = row.get('fetched_at') or payload.get('fetched_at')
            try:
                if not fetched:
                    raise ValueError
                if saved and day(fetched)>day(saved):
                    issue('fetched_after_save','存在本机保存日之后才取得的数据')
                elif saved and 'T' in str(fetched) and instant(fetched)>saved:
                    issue('fetched_after_save','数据取得时刻晚于本机版本保存时刻')
            except ValueError:
                issue('invalid_fetch_time','数据取得日期缺失或无效')
        try:
            analysis = analyze_financials(payload,as_of=cutoff)
            score = score_financials(payload,as_of=cutoff,rules=rules)
        except (ValueError,TypeError,KeyError):
            issue('invalid_financial_contract','财务输入结构或元数据未通过校验')
        if analysis:
            counts = {}
            for row in analysis['records']:
                for code in row.get('issues',[]):
                    counts[code] = counts.get(code,0)+1
            if not analysis['usable_records']:
                issue('no_usable_records','当前没有通过口径、日期和来源校验的财务记录')
            if analysis['blocked_records']:
                issue('blocked_records','部分记录被排除，请核对缺失日期、单位、来源或冲突', 'warning')
            if score and score['status']!='complete':
                issue('incomplete_factors','因子覆盖不完整，综合分保留未知','warning')
            if score and score['coverage_weight']=='0':
                issue('no_comparable_factors','所选币种、报表范围或期间口径没有可比较因子')
            if score and score['period_end'] and (cutoff-day(score['period_end'])).days>550:
                issue('old_financial_period','最新可比财报距检查日超过 550 天，请核对是否缺少更新资料','warning')
        else:
            counts = {}
    if analysis is None:
        counts = {}
    # Collapse repeated failures without exposing arbitrary provider error text.
    unique = {p['code']:p for p in problems}
    problems = list(unique.values())
    forward_ready = not any(p['severity']=='error' for p in problems)
    archive_ready = False
    if saved and day(saved)<cutoff and forward_ready:
        try:
            score_archive({'id':record['id'],'captured_at':record['created'],'payload':payload}, decision_on=cutoff)
            archive_ready = True
        except ValueError:
            pass
    return {'schema_version':1,'symbol':record.get('symbol'),'dataset_id':record.get('id'),
            'saved_at':record.get('created'),'payload_hash':digest(payload),'synthetic':is_synthetic,
            'as_of':str(cutoff),'period_end':score['period_end'] if score else None,
            'financial_age_days':(cutoff-day(score['period_end'])).days if score and score['period_end'] else None,
            'usable_records':analysis['usable_records'] if analysis else 0,
            'blocked_records':analysis['blocked_records'] if analysis else len(rows) if isinstance(rows,list) else 0,
            'score':score,'forward_ready':forward_ready,'archive_ready':archive_ready,
            'record_issues':counts,'issues':problems,
            'policy':'只读检查保存版本与声明元数据，不认证来源真实性；缺失值不补造。'}


def audit_workbench(path, *, as_of):
    store = ReadOnlyWorkbench(path)
    companies = store.watches()
    reports, missing = [],[]
    for company in companies:
        versions = store.financial_versions(company['symbol'],1)
        if versions:
            reports.append(audit_version(versions[0],as_of=as_of))
        else:
            missing.append(company['symbol'])
    return {'as_of':str(day(as_of)),'company_count':len(companies),'saved_versions_checked':len(reports),
            'missing_versions':missing,'forward_ready':sum(r['forward_ready'] for r in reports),
            'archive_ready':sum(r['archive_ready'] for r in reports),'reports':reports,
            'policy':'只检查自选公司的最新明确版本；不写库、不抓取、不调用模型。'}
