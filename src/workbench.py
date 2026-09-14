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

    def review(self, thesis_id, content, status):
        with self.connect() as db:
            db.execute('UPDATE theses SET review=?,status=? WHERE id=?', (content, status, thesis_id))

    def enqueue(self, run_id, kind, content=''):
        with self.connect() as db:
            db.execute('INSERT INTO commands(run_id,kind,content) VALUES (?,?,?)', (run_id, kind, content))

    def pending(self, run_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM commands WHERE run_id=? AND status='pending' ORDER BY id", (run_id,))]

    def ack(self, command_id):
        with self.connect() as db:
            db.execute("UPDATE commands SET status='done' WHERE id=?", (command_id,))

    def set_monitor(self, symbol, enabled):
        with self.connect() as db:
            db.execute('INSERT INTO monitors(symbol,enabled) VALUES (?,?) ON CONFLICT(symbol) DO UPDATE SET enabled=excluded.enabled', (symbol, int(enabled)))

    def monitors(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM monitors')]

    def monitor_attempt(self, symbol, timestamp):
        with self.connect() as db:
            db.execute('UPDATE monitors SET last_attempt=? WHERE symbol=?', (timestamp, symbol))

    def alert(self, symbol, content):
        with self.connect() as db:
            db.execute('INSERT INTO alerts(symbol,created,content) VALUES (?,?,?)', (symbol, now(), content))

    def alerts(self, symbol):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM alerts WHERE symbol=? ORDER BY id DESC LIMIT 5', (symbol,))]
