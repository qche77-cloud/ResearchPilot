"""Single-server background workers with durable commands and checkpoints.

Workers survive browser disconnection, not server shutdown. Pending commands
are stored in SQLite; restart requires explicit resume. Each run has one writer.
"""
import threading
import re
import time
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from src.agent import tick, steer
from src.agent_chat import respond
from src.report_links import normalize_history, snapshot_report
from src.storage import ResearchRunRepository
from src.workbench import Workbench
from src.stock_research import followup_scope
from src.worker_lock import WorkerLock

logger = logging.getLogger(__name__)


class Runner:
    def __init__(self, repo=None, store=None):
        self.repo = repo if repo is not None else ResearchRunRepository()
        self.repo.initialize()
        self.store = store if store is not None else Workbench()
        self.threads = {}
        self.lock = threading.Lock()
        self.monitor_thread = None
        self.worker_errors = {}
        self.worker_error_types = {}

    def start_monitors(self):
        if self.monitor_thread and self.monitor_thread.is_alive():
            return
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def _monitor_loop(self):
        while True:
            try:
                self.monitor_once()
            except Exception as exc:
                # Isolate transient DB errors from research workers.
                logger.warning('Monitor loop unavailable: %s', type(exc).__name__)
            time.sleep(30)

    def monitor_once(self):
        guard = WorkerLock(self.store.path, 'monitor_scheduler')
        if not guard.acquire():
            return
        try:
            self._monitor_once()
        finally:
            guard.release()

    def _monitor_once(self):
        from src.stock_data import fetch_stock, changes
        from src.research_memory import snapshot_changes
        local = datetime.now(ZoneInfo('Asia/Shanghai'))
        for config in self.store.monitors():
            if not config['enabled'] or local.weekday() >= 5 or local.hour < 16:
                continue
            if time.time() - config['last_attempt'] < config['interval_seconds']:
                continue
            symbol = config['symbol']
            self.store.monitor_attempt(symbol, time.time())
            try:
                previous = self.store.snapshots(symbol, 1)
                current = fetch_stock(symbol)
                self.store.save_snapshot(symbol, current)
                comparison = snapshot_changes(previous[0]['payload'] if previous else {}, current)
                if previous and comparison['price_changed']:
                    self.store.alert(symbol, changes(previous[0]['payload'], current))
                if comparison['finance_changed'] and config['source_mode'] == 'daily_and_financials':
                    self.store.alert(symbol, '财务来源记录发生变化，即使交易日期相同也已记录；请更新研究核对财报期、单位和口径。')
                status = 'partial' if comparison['finance_unavailable'] and config['source_mode'] == 'daily_and_financials' else 'success'
                self.store.record_monitor_event(symbol, status, current.get('provider', 'AKShare / 东方财富 / 新浪'), comparison)
            except Exception as exc:
                self.store.alert(symbol, f'盘后更新失败：{type(exc).__name__}。保留旧数据，可手动重试。')
                self.store.record_monitor_event(symbol, 'failed', 'AKShare / 东方财富 / 新浪', {'error_type': type(exc).__name__})

    def active(self, run_id):
        if WorkerLock.held(self.repo.db_path, run_id):
            return True
        with self.lock:
            thread = self.threads.get(run_id)
            return bool(thread and thread.is_alive())

    def read(self, run_id):
        with self.lock:
            state = self.repo.get_state(run_id)
            thread = self.threads.get(run_id)
            active = bool(thread and thread.is_alive()) or WorkerLock.held(self.repo.db_path, run_id)
            if state and not active and run_id in self.worker_errors:
                state.mark_failed(self.worker_errors[run_id], state.current_stage)
                return state, active
            if state and not active:
                guard = WorkerLock(self.repo.db_path, run_id)
                if not guard.acquire():
                    return self.repo.get_state(run_id), True
                try:
                    state = self.repo.get_state(run_id)
                    if state and normalize_history(state):
                        self.repo.save_state(state)
                finally:
                    guard.release()
            return state, active

    def submit(self, run_id, kind, content=''):
        if kind not in {'pause', 'resume', 'budget', 'chat'}:
            raise ValueError('未知任务命令')
        if not self.repo.exists(run_id):
            raise ValueError('研究任务不存在')
        with self.lock:
            self.worker_errors.pop(run_id, None)
            self.worker_error_types.pop(run_id, None)
            self.store.enqueue(run_id, kind, content)
            thread = self.threads.get(run_id)
            if thread and thread.is_alive():
                return
            thread = threading.Thread(target=self._run, args=(run_id,), daemon=True)
            self.threads[run_id] = thread
            thread.start()

    def _run(self, run_id):
        guard = WorkerLock(self.repo.db_path, run_id)
        attempt = None
        try:
            # A process that submits just as another exits keeps trying until
            # the durable command is drained or it can become the next writer.
            deadline = time.monotonic() + 300
            while not guard.acquire():
                if not self.store.pending(run_id) or time.monotonic() >= deadline:
                    return
                time.sleep(.2)
            attempt = self.store.begin_worker(run_id, os.getpid())
            self._run_owned(run_id)
            state = self.repo.get_state(run_id)
            result = 'failed' if run_id in self.worker_errors else ('completed' if state and state.status == 'completed' else 'paused')
            self.store.finish_worker(attempt, result, self.worker_error_types.get(run_id) if result == 'failed' else None)
        except Exception as exc:
            with self.lock:
                self.worker_errors[run_id] = f'任务启动或收尾失败：{type(exc).__name__}。命令保留，可手动重试。'
            if attempt:
                try:
                    self.store.finish_worker(attempt, 'failed', type(exc).__name__)
                except Exception:
                    logger.error('Worker attempt persistence failed')
        finally:
            guard.release()
            with self.lock:
                if self.threads.get(run_id) is threading.current_thread():
                    self.threads.pop(run_id, None)

    def _run_owned(self, run_id):
        state = None
        try:
            state = self.repo.get_state(run_id)
            if state is None:
                return
            a = state.diagnostics['agent']
            running = False
            while True:
                for cmd in self.store.pending(run_id):
                    # State commit before ack; replay after an interrupted commit is idempotent.
                    done = a.setdefault('processed_commands', [])
                    if cmd['id'] in done:
                        self.store.ack(cmd['id'])
                        continue
                    kind = cmd['kind']
                    if kind == 'pause':
                        running = False
                    elif kind == 'resume':
                        state.error = None
                        if state.status != 'completed':
                            state.mark_running(state.current_stage)
                            running = True
                    elif kind == 'budget':
                        a['budget'] = min(16, a['budget'] + 3)
                    elif kind == 'chat':
                        message = cmd['content']
                        a['preferences'] = self.store.preferences()
                        scope_warning = followup_scope(state, message, self.store)
                        messages = a.setdefault('messages', [])
                        if not any(m.get('command_id') == cmd['id'] and m.get('role') == 'user' for m in messages):
                            messages.append({'role': 'user', 'content': message, 'command_id': cmd['id']})
                        reply = {'action': 'answer', 'answer': scope_warning} if scope_warning else respond(state, message)
                        answer = {'role': 'assistant', 'content': reply['answer']}
                        if reply.get('citation_check'):
                            answer['citation_check'] = reply['citation_check']
                        if reply.get('verification'):
                            answer['verification'] = reply['verification']
                        if state.report and reply['action'] == 'answer':
                            answer['report_version'] = snapshot_report(state)
                        a['messages'].append(answer)
                        if reply['action'] == 'research':
                            if a['searches'] >= a['budget']:
                                a['messages'].append({'role': 'assistant', 'content': '搜索预算已用完；增加预算后可再次发送补查要求。'})
                            else:
                                steer(state, str(reply.get('instruction') or message))
                                a['report_in_chat'] = False
                                running = True
                    done.append(cmd['id'])
                    self.repo.save_state(state)
                    self.store.ack(cmd['id'])
                if running:
                    tick(state, store=self.store)
                    if state.status in {'completed', 'failed'}:
                        running = False
                        normalize_history(state)
                    self.repo.save_state(state)
                else:
                    # Close the enqueue/exit race under the same submit lock.
                    with self.lock:
                        if not self.store.pending(run_id):
                            self.threads.pop(run_id, None)
                            return
        except Exception as exc:
            message = f'执行失败：{type(exc).__name__}。请检查持久化状态后手动重试。'
            if state is not None:
                state.mark_failed(message, state.current_stage)
                try:
                    self.repo.save_state(state)
                except Exception as save_error:
                    message = f'状态保存失败：{type(save_error).__name__}。本次进度可能未落盘，持久化命令未确认时将保留待处理。'
            with self.lock:
                self.worker_errors[run_id] = message
                self.worker_error_types[run_id] = type(exc).__name__
            logger.error('Research worker failed: %s', type(exc).__name__)
