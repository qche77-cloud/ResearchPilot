"""Hashed bearer sessions and one-person invitations; no client-selected paths."""
from contextlib import contextmanager
import hashlib
import secrets
import sqlite3
import time
import uuid


class Problem(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(code)


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class Registry:
    def __init__(self, settings, clock=time.time):
        self.settings, self.clock = settings, clock
        settings.root.mkdir(parents=True, exist_ok=True)
        self.path = settings.root / 'identity.db'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, identity_hash TEXT UNIQUE NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS invites (hash TEXT PRIMARY KEY, expires REAL NOT NULL, used_by TEXT);
                CREATE TABLE IF NOT EXISTS sessions (hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires);
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, created REAL NOT NULL, status TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(user_id,created);
                CREATE TABLE IF NOT EXISTS requests (user_id TEXT NOT NULL, request_key TEXT NOT NULL, fingerprint TEXT NOT NULL, run_id TEXT NOT NULL, PRIMARY KEY(user_id,request_key));
                CREATE TABLE IF NOT EXISTS resumes (user_id TEXT NOT NULL, created REAL NOT NULL);
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

    def invitation(self, hours=48):
        if not 1 <= hours <= 720:
            raise ValueError('invitation lifetime must be 1..720 hours')
        code = secrets.token_urlsafe(24)
        with self.connect() as db:
            db.execute('INSERT INTO invites VALUES (?,?,NULL)', (digest(code), self.clock() + hours * 3600))
        return code

    def login(self, identity, invitation='', *, trusted_demo=False):
        """Called only after verified code exchange, or explicit isolated demo mode."""
        if trusted_demo and self.settings.mode != 'demo':
            raise Problem(403, 'demo_disabled', '正式服务不允许演示登录')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            user = db.execute('SELECT * FROM users WHERE identity_hash=?', (digest(identity),)).fetchone()
            if user and not user['enabled']:
                raise Problem(403, 'access_disabled', '此体验账号已停用')
            if not user:
                invite = db.execute('SELECT * FROM invites WHERE hash=?', (digest(invitation),)).fetchone()
                if not trusted_demo and (not invite or invite['used_by'] or invite['expires'] <= self.clock()):
                    raise Problem(403, 'invitation_invalid', '邀请码无效、已使用或已过期')
                if db.execute('SELECT COUNT(*) FROM users').fetchone()[0] >= self.settings.max_users:
                    raise Problem(429, 'user_limit', '体验名额已满')
                uid = uuid.uuid4().hex
                db.execute('INSERT INTO users VALUES (?,?,1)', (uid, digest(identity)))
                if not trusted_demo:
                    db.execute('UPDATE invites SET used_by=? WHERE hash=?', (uid, digest(invitation)))
            else:
                uid = user['id']
            token = secrets.token_urlsafe(32)
            expires = self.clock() + self.settings.session_seconds
            db.execute('DELETE FROM sessions WHERE expires<=?', (self.clock(),))
            # A bounded number of devices/sessions per invited account.
            db.execute('DELETE FROM sessions WHERE user_id=? AND hash NOT IN (SELECT hash FROM sessions WHERE user_id=? ORDER BY expires DESC LIMIT 4)', (uid, uid))
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (digest(token), uid, expires))
        return dict(token=token, expires_at=expires, user_id=uid)

    def authenticate(self, token):
        if not isinstance(token, str) or not 32 <= len(token) <= 128:
            raise Problem(401, 'login_required', '请先登录')
        with self.connect() as db:
            user = db.execute('SELECT u.id FROM sessions s JOIN users u ON s.user_id=u.id WHERE s.hash=? AND s.expires>? AND u.enabled=1', (digest(token), self.clock())).fetchone()
        if not user:
            raise Problem(401, 'session_expired', '登录已失效，请重新登录')
        return user['id']

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE hash=?', (digest(token),))

    def disable(self, uid):
        with self.connect() as db:
            db.execute('UPDATE users SET enabled=0 WHERE id=?', (uid,))
            db.execute('DELETE FROM sessions WHERE user_id=?', (uid,))

    def owns(self, uid, run_id):
        with self.connect() as db:
            return bool(db.execute('SELECT 1 FROM jobs WHERE user_id=? AND id=?', (uid, run_id)).fetchone())


def exchange_wechat(settings, code):
    """Never return or log session_key, upstream bodies, URLs or credentials."""
    import requests
    if not settings.appid or not settings.appsecret:
        raise Problem(503, 'wechat_not_configured', '服务端尚未配置微信登录')
    try:
        response = requests.get('https://api.weixin.qq.com/sns/jscode2session', params={
            'appid': settings.appid, 'secret': settings.appsecret,
            'js_code': code, 'grant_type': 'authorization_code'}, timeout=(5, 10), allow_redirects=False)
        response.raise_for_status()
        data = response.json()
    except Exception:
        raise Problem(503, 'wechat_unavailable', '微信登录暂不可用，请稍后重试') from None
    if not isinstance(data, dict) or data.get('errcode') or not isinstance(data.get('openid'), str) or not data['openid']:
        raise Problem(401, 'wechat_code_invalid', '微信登录凭证无效或已过期')
    return settings.appid + ':' + data['openid']
