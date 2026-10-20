"""Append-only local prospective research. No API calls or automatic scheduling.

The application assigns timestamps; hashes and SQL triggers detect accidental
changes, not a database administrator or an independently certified wall clock.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import sqlite3
import uuid

from src.financial_analysis import analyze_financials
from src.research_memory import compare_snapshots, financial_snapshot
from src.research_readiness import ReadOnlyWorkbench, audit_version, dataset_row, instant, synthetic
from src.research_signals import (DEFAULT_RULES, _baseline, _metrics, checked_rules, day, digest,
                                  score_archive, signal_criterion)
from src.thesis_tracking import evaluate_test

REGISTER_TABLE = 'signal_registrations'
REVIEW_TABLE = 'signal_reviews'
POLICY = '本机前向登记；时间由应用记录，不是独立授时认证。仅手动复盘，不调用外部服务。'


def _clock():
    return datetime.now(timezone.utc)


def _schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS signal_registrations (
        id TEXT PRIMARY KEY, created TEXT NOT NULL, request_key TEXT UNIQUE NOT NULL,
        observation_key TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
        body TEXT NOT NULL, checksum TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS signal_reviews (
        id TEXT PRIMARY KEY, registration_id TEXT NOT NULL, created TEXT NOT NULL,
        as_of TEXT NOT NULL, dataset_id TEXT, body TEXT NOT NULL, checksum TEXT NOT NULL,
        FOREIGN KEY(registration_id) REFERENCES signal_registrations(id))''')
    db.execute('CREATE INDEX IF NOT EXISTS signal_reviews_registration ON signal_reviews(registration_id,created)')
    for table in (REGISTER_TABLE,REVIEW_TABLE):
        for action in ('UPDATE','DELETE'):
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()}
                BEFORE {action} ON {table} BEGIN
                SELECT RAISE(ABORT,'forward research records are append-only'); END''')


def _exists(db,table):
    return db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',('table',table)).fetchone() is not None


def _decode(row):
    try:
        body = json.loads(row['body'])
        if digest(body)!=row['checksum'] or body['id']!=row['id'] or body['created_at']!=row['created']:
            raise ValueError
        return body
    except (ValueError,TypeError,KeyError):
        raise ValueError('账本内容校验失败，停止使用这条记录') from None


def replay_review(package):
    """Recompute a saved review without reading any current database values."""
    if not isinstance(package,dict) or package.get('schema_version')!=1:
        raise ValueError('前向复盘包格式无效')
    registration = package.get('registration')
    if not isinstance(registration,dict) or digest(registration)!=package.get('registration_hash'):
        raise ValueError('登记快照校验失败')
    cutoff = day(package['as_of'])
    decision = day(registration['decision_on'])
    outcome = package.get('outcome_version')
    observation = None
    label = None
    status = 'awaiting_decision' if cutoff<decision else 'not_due' if cutoff<day(registration['criterion']['review_on']) else 'waiting_for_data'
    change = None
    if outcome is not None:
        if not isinstance(outcome,dict) or outcome.get('symbol')!=registration['symbol'] or digest(outcome['payload'])!=package.get('outcome_payload_hash'):
            raise ValueError('复盘版本与登记公司或保存哈希不一致')
        if day(outcome['created'])>cutoff:
            raise ValueError('该财务版本在复盘截止日之后才保存')
        audit = audit_version(outcome,as_of=cutoff,rules=registration['rules'])
        unsafe = [p for p in audit['issues'] if p['severity']=='error' and p['code'] not in {'synthetic_input','no_usable_records','no_comparable_factors'}]
        if unsafe:
            raise ValueError('所选复盘版本的保存时间或结构未通过检查')
        if synthetic(outcome['payload']) and registration['mode']!='synthetic_fixture':
            raise ValueError('真实登记不能使用虚构复盘数据')
        if cutoff>=decision:
            observation = evaluate_test(dict(registration['criterion'],symbol=registration['symbol']),outcome['payload'],as_of=cutoff)
            status = observation['status']
            if status in {'criterion_met','criterion_not_met'}:
                label = status=='criterion_met'
        previous = financial_snapshot(analyze_financials(registration['snapshot']['payload'],as_of=decision))
        current = financial_snapshot(analyze_financials(outcome['payload'],as_of=cutoff))
        change = compare_snapshots({'as_of':str(decision),'financial_analysis':previous},
                                   {'as_of':str(cutoff),'financial_analysis':current})
        # Existing comparisons use set intersections; freeze deterministic order.
        change['changed_financial_values'].sort(key=lambda r:(r['after']['period_end'],r['after']['metric'],r['after']['id']))
    previous_change = None
    previous = package.get('previous_outcome_version')
    if previous is not None and outcome is not None:
        if previous.get('symbol')!=registration['symbol'] or digest(previous['payload'])!=package.get('previous_outcome_payload_hash') or day(previous['created'])>cutoff:
            raise ValueError('前次复盘来源校验失败')
        before = financial_snapshot(analyze_financials(previous['payload'],as_of=package['previous_as_of']))
        after = financial_snapshot(analyze_financials(outcome['payload'],as_of=cutoff))
        previous_change = compare_snapshots({'as_of':package['previous_as_of'],'financial_analysis':before},
                                            {'as_of':str(cutoff),'financial_analysis':after})
        previous_change['changed_financial_values'].sort(key=lambda r:(r['after']['period_end'],r['after']['metric'],r['after']['id']))
    return {'schema_version':1,'registration_id':registration['id'],'as_of':str(cutoff),
            'status':status,'label':label,'observation':observation,'financial_diff':change,
            'previous_review_diff':previous_change,'previous_review_id':package.get('previous_review_id'),
            'predictions':deepcopy(registration['predictions']),
            'registration_hash':package['registration_hash'],
            'outcome_payload_hash':package.get('outcome_payload_hash'),'policy':POLICY}


class ForwardLedger:
    def __init__(self,store,*,clock=None,allow_synthetic=False):
        self.path = Path(getattr(store,'path',store)).resolve()
        self.clock = clock or _clock
        self.allow_synthetic = allow_synthetic

    def now(self):
        return instant(self.clock())

    @contextmanager
    def connect(self,*,write=False):
        if not self.path.is_file():
            raise ValueError('请先在电脑工作台保存财务版本；账本不会自动创建空工作台')
        db = None
        try:
            db = sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=20)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            if not write:
                db.execute('PRAGMA query_only=ON')
            if write:
                db.execute('BEGIN IMMEDIATE')
                _schema(db)
            yield db
            if write:
                db.commit()
        except sqlite3.Error:
            if write and db is not None:
                db.rollback()
            raise ValueError('账本暂不可访问，本次保存未完成；可使用相同请求重试') from None
        except Exception:
            if write and db is not None:
                db.rollback()
            raise
        finally:
            if db is not None:
                db.close()

    def _check_clock(self,db,now):
        times = [db.execute(f'SELECT MAX(created) FROM {table}').fetchone()[0] for table in (REGISTER_TABLE,REVIEW_TABLE)]
        if any(value and instant(value)>now for value in times):
            raise ValueError('本机时间早于已有账本时间，请校准后再保存')

    def _prepare(self,version,*,now,decision,rules):
        if decision<=day(now) or (decision-day(now)).days>366:
            raise ValueError('决策日须在本机今日之后的一年内，不能补记过去判断')
        if instant(version['created'])>now:
            raise ValueError('财务版本保存时间晚于本机当前时间')
        audit = audit_version(version,as_of=day(now),rules=rules)
        errors = [p for p in audit['issues'] if p['severity']=='error' and not (self.allow_synthetic and p['code']=='synthetic_input')]
        if errors:
            raise ValueError('所选财务版本尚不适合登记：'+'；'.join(p['message'] for p in errors))
        frozen_rules = dict(rules,frozen_at=str(day(now)))
        if audit['synthetic']:
            frozen_rules['version']='synthetic-forward-v1'
        snapshot = {'id':version['id'],'captured_at':version['created'],'payload':deepcopy(version['payload'])}
        score = score_archive(snapshot,decision_on=decision,rules=frozen_rules)
        return audit,frozen_rules,snapshot,score

    def preview(self,symbol,dataset_id,*,decision_on,rules=None):
        with self.connect() as db:
            version = dataset_row(db,symbol,dataset_id)
        audit,frozen,snapshot,score = self._prepare(version,now=self.now(),decision=day(decision_on),rules=checked_rules(rules))
        return {'symbol':symbol,'dataset_id':dataset_id,'payload_hash':audit['payload_hash'],
                'saved_at':version['created'],'score':score,'rules':frozen,'decision_on':str(day(decision_on))}

    def register(self,*,symbol,dataset_id,expected_payload_hash,decision_on,criterion,request_key,
                 prediction=None,note='',evidence_ids=None,rules=None):
        if not isinstance(symbol,str) or not re.fullmatch(r'\d{6}',symbol):
            raise ValueError('请选择六位公司代码')
        if not isinstance(dataset_id,str) or not 1<=len(dataset_id)<=128:
            raise ValueError('请选择明确的财务版本')
        if not isinstance(expected_payload_hash,str) or not re.fullmatch(r'[0-9a-f]{64}',expected_payload_hash):
            raise ValueError('需要所选版本的预览哈希')
        if not isinstance(request_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}',request_key):
            raise ValueError('缺少有效的保存请求标识')
        if prediction is not None and not isinstance(prediction,bool):
            raise ValueError('人工判断须为明确的是、否或未判断')
        if not isinstance(note,str) or len(note)>4000 or prediction is not None and not note.strip():
            raise ValueError('有判断时请填写依据，最多 4000 字')
        evidence_ids = evidence_ids or []
        if not isinstance(evidence_ids,list) or len(evidence_ids)>20 or any(not isinstance(k,str) for k in evidence_ids):
            raise ValueError('请从所选版本选择最多 20 条证据')
        if len(set(evidence_ids))!=len(evidence_ids):
            raise ValueError('证据编号不能重复')
        decision = day(decision_on)
        original_rules = checked_rules(rules)
        checked = signal_criterion(criterion,decision_on=decision,rules=original_rules)
        fingerprint = digest([symbol,dataset_id,expected_payload_hash,str(decision),checked,prediction,note.strip(),sorted(evidence_ids),original_rules])
        with self.connect(write=True) as db:
            old = db.execute('SELECT * FROM signal_registrations WHERE request_key=?',(request_key,)).fetchone()
            if old:
                if old['fingerprint']!=fingerprint:
                    raise ValueError('同一保存请求内容发生变化，请重新预览后保存')
                return _decode(old)
            now = self.now()
            self._check_clock(db,now)
            version = dataset_row(db,symbol,dataset_id)
            if digest(version['payload'])!=expected_payload_hash:
                raise ValueError('财务版本内容已变化，请重新检查后登记')
            audit,frozen_rules,snapshot,score = self._prepare(version,now=now,decision=decision,rules=original_rules)
            if any(key not in score['inputs'] for key in evidence_ids) or prediction is not None and not evidence_ids:
                raise ValueError('人工判断须关联本版本内至少一条有效证据')
            if score['period_end'] and any(day(c['period_end'])<=day(score['period_end']) for c in checked['criteria']):
                raise ValueError('目标期必须晚于已保存财报期')
            observation_key = digest([symbol,str(decision),checked])
            if db.execute('SELECT 1 FROM signal_registrations WHERE observation_key=?',(observation_key,)).fetchone():
                raise ValueError('同公司、决策日和判据已登记；原判断保留，请为新的决策日另行登记')
            key = 'FR'+uuid.uuid4().hex
            body = {'schema_version':1,'id':key,'created_at':now.isoformat(),'symbol':symbol,
                    'mode':'synthetic_fixture' if audit['synthetic'] else 'local_prospective',
                    'dataset_id':dataset_id,'dataset_saved_at':version['created'],'payload_hash':expected_payload_hash,
                    'decision_on':str(decision),'criterion':checked,'rules':frozen_rules,'snapshot':snapshot,
                    'score':score,'predictions':{'baseline':_baseline(score),'rules':score['prediction'],'manual':prediction},
                    'manual_judgment':{'note':note.strip(),'evidence_ids':sorted(evidence_ids),'origin':'manual_entry'},'policy':POLICY}
            db.execute('INSERT INTO signal_registrations VALUES (?,?,?,?,?,?,?)',
                       (key,body['created_at'],request_key,observation_key,fingerprint,json.dumps(body,ensure_ascii=False,allow_nan=False),digest(body)))
            return body

    def registrations(self,limit=100):
        if not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=200:
            raise ValueError('一次最多读取 200 条登记')
        with self.connect() as db:
            if not _exists(db,REGISTER_TABLE):
                return []
            return [_decode(row) for row in db.execute('SELECT * FROM signal_registrations ORDER BY created DESC,rowid DESC LIMIT ?',(limit,))]

    def registration(self,key):
        with self.connect() as db:
            if not _exists(db,REGISTER_TABLE):
                raise ValueError('尚未登记研究')
            row = db.execute('SELECT * FROM signal_registrations WHERE id=?',(key,)).fetchone()
            if row is None:
                raise ValueError('未找到指定登记')
            return _decode(row)

    def review(self,key,*,outcome_dataset_id=None,as_of=None):
        with self.connect(write=True) as db:
            row = db.execute('SELECT * FROM signal_registrations WHERE id=?',(key,)).fetchone()
            if row is None:
                raise ValueError('未找到指定登记')
            registration = _decode(row)
            now = self.now()
            self._check_clock(db,now)
            cutoff = day(as_of) if as_of is not None else day(now)
            if cutoff>day(now) or cutoff<day(registration['created_at']):
                raise ValueError('复盘截止日不能早于登记日或晚于本机今日')
            outcome = dataset_row(db,registration['symbol'],outcome_dataset_id) if outcome_dataset_id else None
            if outcome and outcome['id']==registration['dataset_id'] and digest(outcome['payload'])!=registration['payload_hash']:
                raise ValueError('登记源版本被原地修改，请另存财务新版本后复盘')
            if outcome and instant(outcome['created'])>now:
                raise ValueError('复盘版本保存时间晚于本机当前时间')
            package = {'schema_version':1,'registration':registration,'registration_hash':digest(registration),
                       'as_of':str(cutoff),'outcome_version':outcome,
                       'outcome_payload_hash':digest(outcome['payload']) if outcome else None}
            review_id = 'RV'+digest([key,package])[:32]
            existing = db.execute('SELECT * FROM signal_reviews WHERE id=?',(review_id,)).fetchone()
            if existing:
                return _decode(existing)
            for prior_row in db.execute('SELECT * FROM signal_reviews WHERE registration_id=? AND as_of<=? ORDER BY created DESC,rowid DESC LIMIT 200',(key,str(cutoff))):
                prior = _decode(prior_row)
                previous_outcome = prior['replay'].get('outcome_version')
                if outcome and previous_outcome and previous_outcome['id']==outcome['id'] and digest(previous_outcome['payload'])!=digest(outcome['payload']):
                    raise ValueError('旧复盘的源版本被原地修改，请另存新版本')
                if previous_outcome is not None:
                    package.update(previous_review_id=prior['id'],previous_outcome_version=previous_outcome,
                                   previous_outcome_payload_hash=digest(previous_outcome['payload']),previous_as_of=prior['as_of'])
                    break
            result = replay_review(package)
            body = {'schema_version':1,'id':review_id,'created_at':now.isoformat(),
                    'registration_id':key,'as_of':str(cutoff),'dataset_id':outcome_dataset_id,
                    'result':result,'replay':package}
            db.execute('INSERT INTO signal_reviews VALUES (?,?,?,?,?,?,?)',
                       (review_id,key,body['created_at'],str(cutoff),outcome_dataset_id,
                        json.dumps(body,ensure_ascii=False,allow_nan=False),digest(body)))
            return body

    def reviews(self,key,limit=50):
        if not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=200:
            raise ValueError('一次最多读取 200 条复盘')
        return self._reviews(key,limit)

    def _reviews(self,key,limit=None):
        with self.connect() as db:
            if not _exists(db,REVIEW_TABLE):
                return []
            results = []
            sql='SELECT * FROM signal_reviews WHERE registration_id=? ORDER BY created DESC,rowid DESC'
            parameters=(key,)
            if limit is not None:
                sql+=' LIMIT ?'
                parameters+=(limit,)
            for row in db.execute(sql,parameters):
                item = _decode(row)
                if item['result']!=replay_review(item['replay']):
                    raise ValueError('复盘重放校验失败，停止展示该结果')
                results.append(item)
            return results

    def summary(self,*,as_of=None,review_policy='first_known'):
        cutoff = day(as_of) if as_of is not None else day(self.now())
        if cutoff>day(self.now()) or review_policy not in {'first_known','latest'}:
            raise ValueError('统计日期或复盘口径无效')
        rows = []
        for registration in self.registrations(200):
            if day(registration['created_at'])>cutoff:
                continue
            # UI pagination must not discard the earliest known outcome.
            history = [r for r in self._reviews(registration['id'])
                       if day(r['created_at'])<=cutoff and day(r['as_of'])<=cutoff]
            known = [r for r in history if isinstance(r['result']['label'],bool)]
            # History is newest-first, including SQLite insertion order on ties.
            first = min(reversed(known),key=lambda r:r['created_at']) if known else None
            latest = max(history,key=lambda r:(r['as_of'],r['created_at'])) if history else None
            selected = first if review_policy=='first_known' else latest
            state = ('awaiting_decision' if cutoff<day(registration['decision_on']) else
                     'not_due' if cutoff<day(registration['criterion']['review_on']) else 'review_due')
            if selected:
                state = selected['result']['status']
            rows.append({'id':registration['id'],'symbol':registration['symbol'],'mode':registration['mode'],
                         'created_at':registration['created_at'],'decision_on':registration['decision_on'],
                         'review_on':registration['criterion']['review_on'],'status':state,
                         'label':selected['result']['label'] if selected else None,
                         'review_id':selected['id'] if selected else None,
                         'predictions':registration['predictions'],'score':registration['score']['score'],
                         'coverage_weight':registration['score']['coverage_weight'],
                         'result_revised':bool(first and any(r['result']['label']!=first['result']['label'] for r in known))})
        def cohort(items,methods):
            eligible = [r for r in items if isinstance(r['label'],bool) and all(isinstance(r['predictions'][m],bool) for m in methods)]
            return {'n':len(eligible),'case_ids':[r['id'] for r in eligible],
                    'metrics':{method:_metrics(eligible,method) for method in methods}}
        groups = {}
        for mode in ('local_prospective','synthetic_fixture'):
            items = [r for r in rows if r['mode']==mode]
            groups[mode] = {'count':len(items),'rule_baseline':cohort(items,['baseline','rules']),
                            'with_manual':cohort(items,['baseline','rules','manual'])}
        return {'as_of':str(cutoff),'review_policy':review_policy,'rows':rows,'groups':groups,
                'count':len(rows),'due_count':sum(r['status']=='review_due' for r in rows),
                'revised_count':sum(r['result_revised'] for r in rows),
                'policy':'只统计本机截至当日已保存的登记与复盘；默认使用首次已知结果，修订结果可另选查看。最多显示 200 条。'}
