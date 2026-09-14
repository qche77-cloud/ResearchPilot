"""Single-server background workers with durable commands and checkpoints.

Workers survive browser disconnection, not server shutdown. Pending commands
are stored in SQLite; restart requires explicit resume. Each run has one writer.
"""
import threading
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from src.agent import tick, steer
from src.agent_chat import respond
from src.report_links import normalize_history, snapshot_report
from src.storage import ResearchRunRepository
from src.workbench import Workbench


class Runner:
    def __init__(self):
        self.repo = ResearchRunRepository()
        self.repo.initialize()
        self.store = Workbench()
        self.threads = {}
        self.lock = threading.Lock()
        self.monitor_thread = None

    def start_monitors(self):
        if self.monitor_thread and self.monitor_thread.is_alive():
            return
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def _monitor_loop(self):
        while True:
            try:
                self.monitor_once()
            except Exception:
                # Isolate transient DB errors from research workers.
                pass
            time.sleep(30)

    def monitor_once(self):
        from src.stock_data import fetch_stock, changes
        local = datetime.now(ZoneInfo('Asia/Shanghai'))
        for config in self.store.monitors():
            if not config['enabled'] or local.weekday() >= 5 or local.hour < 16:
                continue
            if time.time() - config['last_attempt'] < 20 * 3600:
                continue
            symbol = config['symbol']
            self.store.monitor_attempt(symbol, time.time())
            try:
                previous = self.store.snapshots(symbol, 1)
                current = fetch_stock(symbol)
                self.store.save_snapshot(symbol, current)
                if previous and previous[0]['payload']['daily'][-1]['日期'] != current['daily'][-1]['日期']:
                    self.store.alert(symbol, changes(previous[0]['payload'], current))
            except Exception as exc:
                self.store.alert(symbol, f'盘后更新失败：{type(exc).__name__}。保留旧数据，可手动重试。')

    def active(self, run_id):
        with self.lock:
            thread = self.threads.get(run_id)
            return bool(thread and thread.is_alive())

    def read(self, run_id):
        with self.lock:
            state = self.repo.get_state(run_id)
            thread = self.threads.get(run_id)
            active = bool(thread and thread.is_alive())
            if state and not active and normalize_history(state):
                self.repo.save_state(state)
            return state, active

    def submit(self, run_id, kind, content=''):
        with self.lock:
            self.store.enqueue(run_id, kind, content)
            thread = self.threads.get(run_id)
            if thread and thread.is_alive():
                return
            thread = threading.Thread(target=self._run, args=(run_id,), daemon=True)
            self.threads[run_id] = thread
            thread.start()

    def _run(self, run_id):
        state = self.repo.get_state(run_id)
        if state is None:
            return
        a = state.diagnostics['agent']
        running = False
        try:
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
                        # Attach an explicitly mentioned stock's latest cached snapshot.
                        for symbol in re.findall(r'\b\d{6}\b', message + ' ' + state.topic):
                            cached = self.store.snapshots(symbol, 1)
                            if cached:
                                payload = cached[0]['payload']
                                a['market_data'] = {k: payload[k] for k in ['symbol', 'exchange', 'fetched_at', 'adjustment', 'price_unit']}
                                a['market_data']['latest_daily'] = payload['daily'][-1]
                        a.setdefault('messages', []).append({'role': 'user', 'content': message})
                        reply = respond(state, message)
                        answer = {'role': 'assistant', 'content': reply['answer']}
                        if reply.get('citation_check'):
                            answer['citation_check'] = reply['citation_check']
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
                    tick(state)
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
            state.mark_failed(f'执行失败：{type(exc).__name__}。状态已保留，可手动重试。', state.current_stage)
            self.repo.save_state(state)
