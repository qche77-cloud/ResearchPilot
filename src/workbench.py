"""Local portfolio research storage, independent of execution state."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[1] / 'data' / 'workbench.db'


def now():
    return datetime.now(timezone.utc).isoformat()


class Workbench:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS preferences (id INTEGER PRIMARY KEY, content TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS watchlist (symbol TEXT PRIMARY KEY, name TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS theses (id TEXT PRIMARY KEY, symbol TEXT NOT NULL, created TEXT NOT NULL, thesis TEXT NOT NULL, catalyst TEXT NOT NULL, invalidation TEXT NOT NULL, review TEXT NOT NULL, status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS commands (id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending');
                CREATE TABLE IF NOT EXISTS monitors (symbol TEXT PRIMARY KEY, enabled INTEGER NOT NULL, last_attempt REAL NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, created TEXT NOT NULL, content TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS stock_directory (symbol TEXT PRIMARY KEY, name TEXT NOT NULL, exchange TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS stock_profiles (symbol TEXT PRIMARY KEY, focus TEXT NOT NULL, supporting TEXT NOT NULL, contrary TEXT NOT NULL, questions TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS stock_runs (symbol TEXT NOT NULL, run_id TEXT NOT NULL UNIQUE, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS judgment_proposals (id TEXT PRIMARY KEY, symbol TEXT NOT NULL, thesis_id TEXT NOT NULL, run_id TEXT NOT NULL, version TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending');
                CREATE TABLE IF NOT EXISTS thesis_history (id INTEGER PRIMARY KEY, thesis_id TEXT NOT NULL, created TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL, proposal_id TEXT);
                CREATE TABLE IF NOT EXISTS financial_inputs (id TEXT PRIMARY KEY, symbol TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS monitor_settings (symbol TEXT PRIMARY KEY, interval_seconds INTEGER NOT NULL, source_mode TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS monitor_events (id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, created TEXT NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL, detail TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS worker_attempts (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, pid INTEGER NOT NULL, started TEXT NOT NULL, finished TEXT, status TEXT NOT NULL, error_type TEXT);
                CREATE INDEX IF NOT EXISTS worker_attempts_run ON worker_attempts(run_id,started);
                CREATE TABLE IF NOT EXISTS screening_presets (id TEXT PRIMARY KEY, name TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL, revision INTEGER NOT NULL, criteria TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS screening_executions (id TEXT PRIMARY KEY, preset_id TEXT, preset_revision INTEGER, created TEXT NOT NULL, criteria TEXT NOT NULL, input_ids TEXT NOT NULL, result TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def preferences(self):
        with self.connect() as db:
            row = db.execute('SELECT content FROM preferences WHERE id=1').fetchone()
            return row['content'] if row else ''

    def profile(self, symbol):
        with self.connect() as db:
            row = db.execute('SELECT * FROM stock_profiles WHERE symbol=?', (symbol,)).fetchone()
        return dict(row) if row else dict(symbol=symbol, focus='', supporting='', contrary='', questions='', updated='')

    def save_profile(self, symbol, focus, supporting, contrary, questions):
        from src.stock_data import normalize_symbol
        normalize_symbol(symbol)
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO stock_profiles VALUES (?,?,?,?,?,?)',
                       (symbol, focus[:6000], supporting[:6000], contrary[:6000], questions[:6000], now()))

    def link_run(self, symbol, run_id):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO stock_runs VALUES (?,?,?)', (symbol, run_id, now()))

    def stock_runs(self, symbol):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM stock_runs WHERE symbol=? ORDER BY created DESC', (symbol,))]

    def directory(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM stock_directory ORDER BY symbol')]

    def save_directory(self, rows):
        with self.connect() as db:
            db.executemany('INSERT OR REPLACE INTO stock_directory VALUES (?,?,?,?)',
                           [(r['symbol'], r['name'], r['exchange'], now()) for r in rows])

    def save_preferences(self, content):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO preferences VALUES (1,?)', (content[:6000],))

    def save_financial_dataset(self, symbol, payload):
        from src.stock_data import normalize_symbol
        from src.financial_analysis import analyze_financials, identity
        normalize_symbol(symbol)
        if payload.get('symbol') != symbol or payload.get('provenance') == 'synthetic_fixture':
            raise ValueError('数据必须绑定当前股票，合成示例不能保存为真实研究输入')
        if any(str(r.get('symbol') or symbol) != symbol for r in payload.get('financial_records', payload.get('finance', [])) if isinstance(r, dict)):
            raise ValueError('存在其他股票的财务记录，不能混入当前研究')
        analysis = analyze_financials(payload)
        if not analysis['records']:
            raise ValueError('未找到支持的财务指标')
        dataset_id = identity(payload, 'FD')
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO financial_inputs VALUES (?,?,?,?)',
                       (dataset_id, symbol, now(), json.dumps(payload, ensure_ascii=False, allow_nan=False)))
        return dataset_id

    def financial_dataset(self, symbol):
        with self.connect() as db:
            row = db.execute('SELECT * FROM financial_inputs WHERE symbol=? ORDER BY created DESC,rowid DESC LIMIT 1', (symbol,)).fetchone()
        return dict(row, payload=json.loads(row['payload'])) if row else None

    def financial_versions(self, symbol, limit=30):
        with self.connect() as db:
            return [dict(r, payload=json.loads(r['payload'])) for r in db.execute(
                'SELECT * FROM financial_inputs WHERE symbol=? ORDER BY created DESC,rowid DESC LIMIT ?', (symbol, limit))]

    def financial_version(self, symbol, dataset_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM financial_inputs WHERE symbol=? AND id=?', (symbol,dataset_id)).fetchone()
        return dict(row,payload=json.loads(row['payload'])) if row else None

    def save_screening_preset(self, name, criteria, preset_id=None):
        from src.financial_screening import screen_financials
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError('方案名称须为 1–80 字')
        screen_financials({}, **criteria)
        preset_id = preset_id or uuid.uuid4().hex
        with self.connect() as db:
            previous = db.execute('SELECT * FROM screening_presets WHERE id=?', (preset_id,)).fetchone()
            revision = previous['revision'] + 1 if previous else 1
            db.execute('INSERT INTO screening_presets VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,updated=excluded.updated,revision=excluded.revision,criteria=excluded.criteria',
                       (preset_id, name.strip(), previous['created'] if previous else now(), now(), revision, json.dumps(criteria, ensure_ascii=False, allow_nan=False)))
        return preset_id

    def screening_presets(self):
        with self.connect() as db:
            return [dict(r, criteria=json.loads(r['criteria'])) for r in db.execute('SELECT * FROM screening_presets ORDER BY updated DESC')]

    def save_screening_execution(self, result, input_ids, preset=None):
        execution = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO screening_executions VALUES (?,?,?,?,?,?,?)',
                       (execution, preset['id'] if preset else None, preset['revision'] if preset else None, now(),
                        json.dumps(result['parameters'], ensure_ascii=False), json.dumps(input_ids, ensure_ascii=False),
                        json.dumps(result, ensure_ascii=False, allow_nan=False)))
        return execution

    def screening_executions(self, limit=30):
        with self.connect() as db:
            return [dict(r, criteria=json.loads(r['criteria']), input_ids=json.loads(r['input_ids']), result=json.loads(r['result']))
                    for r in db.execute('SELECT * FROM screening_executions ORDER BY created DESC,rowid DESC LIMIT ?', (limit,))]

    def watch(self, symbol, name):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO watchlist VALUES (?,?,?)', (symbol, name, now()))

    def unwatch(self, symbol):
        with self.connect() as db:
            db.execute('DELETE FROM watchlist WHERE symbol=?', (symbol,))

    def watches(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM watchlist ORDER BY created DESC')]

    def save_snapshot(self, symbol, payload):
        with self.connect() as db:
            db.execute('INSERT INTO snapshots(symbol,created,payload) VALUES (?,?,?)',
                       (symbol, now(), json.dumps(payload, ensure_ascii=False, allow_nan=False)))

    def snapshots(self, symbol, limit=2):
        with self.connect() as db:
            return [dict(r, payload=json.loads(r['payload'])) for r in db.execute(
                'SELECT * FROM snapshots WHERE symbol=? ORDER BY id DESC LIMIT ?', (symbol, limit))]

    def add_thesis(self, symbol, thesis, catalyst, invalidation):
        with self.connect() as db:
            db.execute('INSERT INTO theses VALUES (?,?,?,?,?,?,?,?)',
                       (uuid.uuid4().hex, symbol, now(), thesis, catalyst, invalidation, '', '观察中'))

    def theses(self, symbol):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM theses WHERE symbol=? ORDER BY created DESC', (symbol,))]

    def review(self, thesis_id, content, status, expected=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            before = db.execute('SELECT * FROM theses WHERE id=?', (thesis_id,)).fetchone()
            if before is None:
                raise ValueError('投资假设不存在')
            if expected is not None and expected != {'review':before['review'],'status':before['status']}:
                raise ValueError('复盘已变更，请刷新后再保存')
            db.execute('UPDATE theses SET review=?,status=? WHERE id=?', (content, status, thesis_id))
            after = dict(before, review=content, status=status)
            db.execute('INSERT INTO thesis_history(thesis_id,created,before_json,after_json) VALUES (?,?,?,?)',
                       (thesis_id, now(), json.dumps(dict(before), ensure_ascii=False), json.dumps(after, ensure_ascii=False)))

    def save_proposal(self, symbol, thesis_id, run_id, version, payload):
        import hashlib
        identity = json.dumps([symbol, thesis_id, run_id, version, payload['before']], sort_keys=True, ensure_ascii=False)
        pid = hashlib.sha256(identity.encode()).hexdigest()[:24]
        if payload['before']['symbol'] != symbol or payload['before']['id'] != thesis_id:
            raise ValueError('股票或假设不匹配')
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO judgment_proposals(id,symbol,thesis_id,run_id,version,created,payload) VALUES (?,?,?,?,?,?,?)',
                       (pid, symbol, thesis_id, run_id, version, now(), json.dumps(payload, ensure_ascii=False)))
        return pid

    def proposals(self, symbol):
        with self.connect() as db:
            return [dict(r, payload=json.loads(r['payload'])) for r in db.execute(
                'SELECT * FROM judgment_proposals WHERE symbol=? ORDER BY created DESC', (symbol,))]

    def reject_proposal(self, pid):
        with self.connect() as db:
            db.execute("UPDATE judgment_proposals SET status='rejected' WHERE id=? AND status='pending'", (pid,))

    def confirm_proposal(self, pid, verdict, reason):
        if verdict not in {'维持', '增强', '削弱', '待核查'} or not reason.strip():
            raise ValueError('请选择判断并填写确认理由')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM judgment_proposals WHERE id=? AND status='pending'", (pid,)).fetchone()
            if row is None:
                raise ValueError('建议已处理或不存在，请刷新')
            proposal = json.loads(row['payload'])
            current = db.execute('SELECT * FROM theses WHERE id=?', (row['thesis_id'],)).fetchone()
            if current is None or dict(current) != proposal['before']:
                raise ValueError('投资假设或复盘已变更，请重新生成建议，避免覆盖新判断')
            before = dict(current)
            # Do not map weakening to disproven. Preserve the lifecycle status.
            after = dict(before, review=before['review'] + ('\n\n' if before['review'] else '') +
                         f'[{now()}] 用户确认：{verdict}。{reason.strip()}（报告版本 {row["version"]}）')
            db.execute('UPDATE theses SET review=? WHERE id=?', (after['review'], row['thesis_id']))
            db.execute('INSERT INTO thesis_history(thesis_id,created,before_json,after_json,proposal_id) VALUES (?,?,?,?,?)',
                       (row['thesis_id'], now(), json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), pid))
            db.execute("UPDATE judgment_proposals SET status='confirmed' WHERE id=?", (pid,))

    def review_history(self, thesis_id):
        with self.connect() as db:
            return [dict(r, before=json.loads(r['before_json']), after=json.loads(r['after_json'])) for r in db.execute(
                'SELECT * FROM thesis_history WHERE thesis_id=? ORDER BY id DESC', (thesis_id,))]

    def enqueue(self, run_id, kind, content=''):
        with self.connect() as db:
            db.execute('INSERT INTO commands(run_id,kind,content) VALUES (?,?,?)', (run_id, kind, content))

    def pending(self, run_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM commands WHERE run_id=? AND status='pending' ORDER BY id", (run_id,))]

    def ack(self, command_id):
        with self.connect() as db:
            db.execute("UPDATE commands SET status='done' WHERE id=?", (command_id,))

    def begin_worker(self, run_id, pid):
        attempt = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("UPDATE worker_attempts SET status='interrupted',finished=? WHERE run_id=? AND status='running'", (now(), run_id))
            db.execute('INSERT INTO worker_attempts VALUES (?,?,?,?,?,?,?)', (attempt, run_id, pid, now(), None, 'running', None))
        return attempt

    def finish_worker(self, attempt, status, error_type=None):
        with self.connect() as db:
            db.execute('UPDATE worker_attempts SET finished=?,status=?,error_type=? WHERE id=?', (now(), status, error_type, attempt))

    def worker_attempts(self, run_id, limit=10):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM worker_attempts WHERE run_id=? ORDER BY started DESC,rowid DESC LIMIT ?', (run_id, limit))]

    def set_monitor(self, symbol, enabled):
        with self.connect() as db:
            db.execute('INSERT INTO monitors(symbol,enabled) VALUES (?,?) ON CONFLICT(symbol) DO UPDATE SET enabled=excluded.enabled', (symbol, int(enabled)))

    def monitors(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT m.*,COALESCE(s.interval_seconds,72000) AS interval_seconds,COALESCE(s.source_mode,\'daily_and_financials\') AS source_mode FROM monitors m LEFT JOIN monitor_settings s ON s.symbol=m.symbol')]

    def configure_monitor(self, symbol, interval_seconds, source_mode):
        from src.stock_data import normalize_symbol
        normalize_symbol(symbol)
        if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int) or not 3600 <= interval_seconds <= 7 * 86400:
            raise ValueError('监控频率须介于 1 小时和 7 天')
        if source_mode not in {'daily', 'daily_and_financials'}:
            raise ValueError('未知监控来源模式')
        with self.connect() as db:
            db.execute('INSERT INTO monitor_settings VALUES (?,?,?) ON CONFLICT(symbol) DO UPDATE SET interval_seconds=excluded.interval_seconds,source_mode=excluded.source_mode', (symbol, interval_seconds, source_mode))

    def record_monitor_event(self, symbol, status, source, detail):
        with self.connect() as db:
            db.execute('INSERT INTO monitor_events(symbol,created,status,source,detail) VALUES (?,?,?,?,?)',
                       (symbol, now(), status, source, json.dumps(detail, ensure_ascii=False, allow_nan=False)))

    def monitor_events(self, symbol, limit=20):
        with self.connect() as db:
            return [dict(r, detail=json.loads(r['detail'])) for r in db.execute('SELECT * FROM monitor_events WHERE symbol=? ORDER BY id DESC LIMIT ?', (symbol, limit))]

    def monitor_attempt(self, symbol, timestamp):
        with self.connect() as db:
            db.execute('UPDATE monitors SET last_attempt=? WHERE symbol=?', (timestamp, symbol))

    def alert(self, symbol, content):
        with self.connect() as db:
            db.execute('INSERT INTO alerts(symbol,created,content) VALUES (?,?,?)', (symbol, now(), content))

    def alerts(self, symbol):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM alerts WHERE symbol=? ORDER BY id DESC LIMIT 5', (symbol,))]
