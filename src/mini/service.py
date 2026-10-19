"""Single-process, bounded research service with server-owned user workspaces."""
from datetime import datetime
import json
import os
import re
import threading
from zoneinfo import ZoneInfo

from src.agent import create_agent
from src.background import Runner
from src.financial_analysis import analyze_financials, chart_points
from src.research_state import _to_jsonable
from src.stock_data import normalize_symbol
from src.stock_research import attach_research, symbols_in
from src.storage import ResearchRunRepository
from src.studio_bridge import run_view
from src.workbench import Workbench
from src.mini.identity import Problem, Registry, digest


class Service:
    def __init__(self, settings, *, runner_factory=Runner, clock=None):
        self.settings = settings
        self.registry = Registry(settings, **({'clock': clock} if clock else {}))
        self.factory = runner_factory
        self.workspaces = {}
        self.lock = threading.RLock()

    def workspace(self, uid, *, internal=False):
        if not re.fullmatch(r'[0-9a-f]{32}', uid):
            raise Problem(401, 'invalid_user', '登录身份无效')
        with self.lock:
            if uid not in self.workspaces:
                with self.registry.connect() as db:
                    if not db.execute('SELECT 1 FROM users WHERE id=?' + ('' if internal else ' AND enabled=1'), (uid,)).fetchone():
                        raise Problem(401, 'invalid_user', '登录身份无效')
                root = self.settings.root / 'users' / uid
                self.workspaces[uid] = self.factory(ResearchRunRepository(root / 'research.db'), Workbench(root / 'workbench.db'))
            return self.workspaces[uid]

    def day_start(self):
        now = datetime.fromtimestamp(self.registry.clock(), ZoneInfo('Asia/Shanghai'))
        return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def refresh(self):
        with self.registry.connect() as db:
            rows = db.execute("SELECT * FROM jobs WHERE status='active'").fetchall()
            for row in rows:
                worker = self.workspace(row['user_id'], internal=True)
                if not worker.active(row['id']):
                    state = worker.repo.get_state(row['id'])
                    status = state.status if state and state.status in {'completed', 'failed'} else 'paused'
                    db.execute('UPDATE jobs SET status=? WHERE id=?', (status, row['id']))

    def me(self, uid):
        with self.registry.connect() as db:
            count = db.execute('SELECT COUNT(*) FROM jobs WHERE user_id=? AND created>=?', (uid, self.day_start())).fetchone()[0]
            total = db.execute('SELECT COUNT(*) FROM jobs WHERE user_id=?', (uid,)).fetchone()[0]
        return dict(user_id=uid, mode=self.settings.mode, research_enabled=self.settings.mode == 'demo' or self.ready(),
                    daily_used=count, daily_limit=self.settings.daily_runs, max_searches=self.settings.max_searches,
                    history_count=total, watch_count=len(self.workspace(uid).store.watches()))

    def ready(self):
        return self.settings.research_enabled and bool(os.getenv('OPENAI_API_KEY', '').strip()) and bool(os.getenv('TAVILY_API_KEY', '').strip())

    def owned(self, uid, run_id):
        if not self.registry.owns(uid, run_id):
            raise Problem(404, 'run_not_found', '研究记录不存在')
        worker = self.workspace(uid)
        state = worker.repo.get_state(run_id)
        if not state:
            raise Problem(404, 'run_not_found', '研究记录不存在')
        return worker, state

    def history(self, uid, limit=20, offset=0):
        if not 1 <= limit <= 50 or not 0 <= offset <= 10000:
            raise Problem(422, 'invalid_pagination', '分页参数无效')
        with self.registry.connect() as db:
            rows = db.execute('SELECT id FROM jobs WHERE user_id=? ORDER BY created DESC,id DESC LIMIT ? OFFSET ?', (uid, limit, offset)).fetchall()
            count = db.execute('SELECT COUNT(*) FROM jobs WHERE user_id=?', (uid,)).fetchone()[0]
        result = []
        for row in rows:
            worker, state = self.owned(uid, row['id'])
            view = self.view(worker, state)
            result.append({k: view[k] for k in ('id', 'topic', 'status', 'active', 'completed', 'stage', 'updated_at', 'searches', 'budget', 'versions')})
        return dict(items=result, total=count, limit=limit, offset=offset)

    def view(self, worker, state):
        data = run_view(state, worker.active(state.run_id))
        versions = [dict(id=k, as_of=v.get('as_of'), sections=len(v.get('sections', []))) for k, v in data['versions'].items()]
        # No full evidence bodies, message history or internal preferences in polling.
        return _to_jsonable(dict(id=data['id'], topic=data['topic'], status=data['status'], active=data['active'], completed=data['completed'],
                    stage=data['stage'], updated_at=data['updated_at'], error=data['error'], searches=data['searches'], budget=data['budget'],
                    plan=data['plan'], events=data['events'][-20:], gaps=data['gaps'][:10], versions=versions,
                    trace_summary=data['trace_summary'], demo=self.settings.mode == 'demo'))

    def report(self, uid, run_id, version):
        worker, state = self.owned(uid, run_id)
        snapshot = run_view(state, worker.active(run_id))['versions'].get(version)
        if snapshot is None:
            raise Problem(404, 'version_not_found', '报告版本不存在')
        return dict(id=version, run_id=run_id, topic=state.topic, demo=self.settings.mode == 'demo', **snapshot)

    def check_capacity(self, db, uid, run_id=None):
        active = db.execute("SELECT id,user_id FROM jobs WHERE status='active'").fetchall()
        if any(r['user_id'] == uid and r['id'] != run_id for r in active) or len(active) >= self.settings.global_active:
            raise Problem(429, 'task_capacity', '正在执行的任务已达上限，请等待或暂停后重试')

    def create(self, uid, topic, budget, request_key, symbol=None):
        topic = topic.strip()
        if not topic or len(topic) > 1200 or isinstance(budget, bool) or not 2 <= budget <= self.settings.max_searches:
            raise Problem(422, 'invalid_research', '请输入 1–1200 字问题，并选择允许的搜索次数')
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', request_key or ''):
            raise Problem(422, 'request_key_required', '缺少有效请求标识，请刷新后重试')
        if symbol:
            normalize_symbol(symbol)
        fingerprint = digest(json.dumps([topic, budget, symbol], ensure_ascii=False))
        with self.lock:
            self.refresh()
            worker = self.workspace(uid)
            with self.registry.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                prior = db.execute('SELECT * FROM requests WHERE user_id=? AND request_key=?', (uid, request_key)).fetchone()
                if prior:
                    if prior['fingerprint'] != fingerprint:
                        raise Problem(409, 'request_conflict', '此请求标识已用于不同的研究问题')
                    return self.view(worker, self.owned(uid, prior['run_id'])[1])
                if self.settings.mode != 'demo' and not self.ready():
                    raise Problem(503, 'research_disabled', '服务端尚未启用真实研究或模型/搜索连接未配置')
                self.check_capacity(db, uid)
                used = db.execute('SELECT COUNT(*) FROM jobs WHERE user_id=? AND created>=?', (uid, self.day_start())).fetchone()[0]
                if used >= self.settings.daily_runs:
                    raise Problem(429, 'daily_limit', '今日研究次数已用完')
                candidates = symbols_in(topic, worker.store.directory())
                if symbol and any(code != symbol for code in candidates):
                    raise Problem(422, 'company_scope', '公司研究问题包含其他股票，请分开研究或不指定单家公司')
                assigned = symbol or (candidates[0] if len(candidates) == 1 else None)
                goal = f'{assigned} · {topic}' if assigned and assigned not in topic else topic
                state = create_agent(goal, budget)
                if assigned:
                    attach_research(state, worker.store, worker.repo, assigned)
                state.diagnostics['agent'].update(max_iterations=40, max_search_attempts=16,
                    preferences=worker.store.preferences(), messages=[dict(role='user', content=goal)])
                if self.settings.mode == 'demo':
                    from src.mini.demo import fill_report
                    fill_report(state)
                worker.repo.save_state(state)
                if assigned:
                    worker.store.link_run(assigned, state.run_id)
                db.execute('INSERT INTO jobs VALUES (?,?,?,?)', (state.run_id, uid, self.registry.clock(), 'completed' if self.settings.mode == 'demo' else 'active'))
                db.execute('INSERT INTO requests VALUES (?,?,?,?)', (uid, request_key, fingerprint, state.run_id))
            if self.settings.mode != 'demo':
                try:
                    worker.submit(state.run_id, 'resume')
                except Exception:
                    with self.registry.connect() as db:
                        db.execute("UPDATE jobs SET status='paused' WHERE id=?", (state.run_id,))
                    raise Problem(503, 'start_failed', '任务已保存但未能启动，请在任务中手动恢复') from None
            return self.view(worker, state)

    def command(self, uid, run_id, kind):
        if kind not in {'pause', 'resume'}:
            raise Problem(422, 'invalid_command', '只允许暂停或恢复任务')
        with self.lock:
            worker, state = self.owned(uid, run_id)
            if self.settings.mode == 'demo':
                raise Problem(409, 'demo_completed', '离线报告已生成，无真实后台任务需要暂停或恢复')
            active = worker.active(run_id)
            if kind == 'resume' and state.status == 'completed':
                raise Problem(409, 'task_completed', '已完成的研究无需恢复')
            if (kind == 'resume' and active) or (kind == 'pause' and not active):
                return self.view(worker, state)
            if kind == 'resume':
                if not self.ready():
                    raise Problem(503, 'research_disabled', '服务端未启用真实研究')
                self.refresh()
                with self.registry.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    self.check_capacity(db, uid, run_id)
                    used = db.execute('SELECT COUNT(*) FROM resumes WHERE user_id=? AND created>=?', (uid, self.day_start())).fetchone()[0]
                    if used >= self.settings.daily_resumes:
                        raise Problem(429, 'resume_limit', '今日恢复次数已达上限')
                    db.execute('INSERT INTO resumes VALUES (?,?)', (uid, self.registry.clock()))
                    db.execute("UPDATE jobs SET status='active' WHERE id=?", (run_id,))
            worker.submit(run_id, kind)
            return self.view(worker, state)

    def watch(self, uid, symbol, name):
        normalize_symbol(symbol)
        worker = self.workspace(uid)
        with self.lock:
            if len(worker.store.watches()) >= 50 and symbol not in {w['symbol'] for w in worker.store.watches()}:
                raise Problem(429, 'watch_limit', '最多保存 50 家自选公司')
            worker.store.watch(symbol, name.strip() or symbol)
        return worker.store.watches()

    def company(self, uid, symbol):
        normalize_symbol(symbol)
        worker = self.workspace(uid)
        row = worker.store.financial_dataset(symbol)
        snapshots = worker.store.snapshots(symbol, 1) if not row else []
        payload = row['payload'] if row else snapshots[0]['payload'] if snapshots else {'symbol': symbol}
        analysis = analyze_financials(payload)
        return dict(symbol=symbol, dataset_id=row['id'] if row else None, saved_at=row['created'] if row else None,
                    analysis=analysis, charts={m: chart_points(analysis, m, 'cumulative') for m in ('revenue', 'attributable_net_profit', 'operating_cash_flow')},
                    demo=self.settings.mode == 'demo')
