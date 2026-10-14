"""Real process contention/crash checks plus checkpoint and failure contracts."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from src.agent import create_agent
from src.background import Runner
from src.storage import ResearchRunRepository
from src.workbench import Workbench
from src.worker_lock import WorkerLock


class WorkerReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = ResearchRunRepository(Path(self.tmp.name) / 'research.db')
        self.repo.initialize()
        self.store = Workbench(Path(self.tmp.name) / 'workbench.db')
        self.state = create_agent('离线可靠性测试')
        self.repo.save_state(self.state)
        self.runner = Runner(self.repo, self.store)

    def join(self, runner):
        thread = runner.threads.get(self.state.run_id)
        if thread:
            thread.join(8)
            self.assertFalse(thread.is_alive())

    def test_os_lock_excludes_other_handles_and_releases(self):
        first, second = [WorkerLock(self.repo.db_path, self.state.run_id) for _ in range(2)]
        self.assertTrue(first.acquire())
        self.addCleanup(first.release)
        self.assertFalse(second.acquire())
        self.assertTrue(WorkerLock.held(self.repo.db_path, self.state.run_id))
        first.release()
        self.assertTrue(second.acquire())
        second.release()

    def test_killed_process_releases_lock_without_expiry(self):
        code = "from src.worker_lock import WorkerLock; import sys; g=WorkerLock(sys.argv[1],sys.argv[2]); assert g.acquire(); print('LOCKED',flush=True); sys.stdin.readline()"
        process = subprocess.Popen([sys.executable, '-c', code, str(self.repo.db_path), self.state.run_id], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        self.assertEqual(process.stdout.readline().strip(), 'LOCKED')
        self.assertTrue(self.runner.active(self.state.run_id))
        process.terminate()
        process.communicate(timeout=10)
        self.assertFalse(self.runner.active(self.state.run_id))

    def test_two_processes_apply_durable_commands_once(self):
        code = """from scripts.run_offline_tests import install_guard
install_guard()
from src.background import Runner
from src.storage import ResearchRunRepository
from src.workbench import Workbench
import sys
r=Runner(ResearchRunRepository(sys.argv[1]),Workbench(sys.argv[2]))
r.submit(sys.argv[3],'budget')
t=r.threads.get(sys.argv[3])
if t: t.join(15); assert not t.is_alive()
assert not r.worker_errors
"""
        processes = [subprocess.Popen([sys.executable, '-c', code, str(self.repo.db_path), str(self.store.path), self.state.run_id], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        for process in processes:
            self.addCleanup(lambda p=process: p.kill() if p.poll() is None else None)
            _, error = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, error)
        restored = self.repo.get_state(self.state.run_id)
        self.assertEqual(restored.diagnostics['agent']['budget'], 8)
        self.assertEqual(len(restored.diagnostics['agent']['processed_commands']), 2)
        self.assertEqual(self.store.pending(self.state.run_id), [])

    def test_two_runners_do_not_overlap_model_calls(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def respond(state, message):
            calls.append(message)
            entered.set()
            self.assertTrue(release.wait(5))
            return {'action': 'answer', 'answer': '离线合成回答'}
        other = Runner(self.repo, self.store)
        with patch('src.background.respond', side_effect=respond):
            self.runner.submit(self.state.run_id, 'chat', '第一条')
            self.assertTrue(entered.wait(5))
            other.submit(self.state.run_id, 'chat', '第二条')
            self.assertEqual(calls, ['第一条'])
            self.assertTrue(other.active(self.state.run_id))
            release.set()
            self.join(self.runner)
            self.join(other)
        self.assertEqual(calls, ['第一条', '第二条'])

    def test_pending_command_survives_restart_and_is_replayed_once(self):
        self.store.enqueue(self.state.run_id, 'budget')
        restarted = Runner(self.repo, self.store)
        restarted.submit(self.state.run_id, 'pause')
        self.join(restarted)
        self.assertEqual(self.repo.get_state(self.state.run_id).diagnostics['agent']['budget'], 5)
        restarted._run(self.state.run_id)
        self.assertEqual(self.repo.get_state(self.state.run_id).diagnostics['agent']['budget'], 5)

    def test_failure_is_durable_and_keeps_unacknowledged_command(self):
        with patch('src.background.respond', side_effect=ConnectionError('must-not-leak-private-data')):
            self.runner.submit(self.state.run_id, 'chat', '核查')
            self.join(self.runner)
        state = self.repo.get_state(self.state.run_id)
        self.assertEqual(state.status, 'failed')
        self.assertNotIn('must-not-leak', state.error)
        self.assertEqual(len(self.store.pending(state.run_id)), 1)
        self.assertEqual(self.store.worker_attempts(state.run_id)[0]['status'], 'failed')
        self.assertEqual(self.store.worker_attempts(state.run_id)[0]['error_type'], 'ConnectionError')
        with patch('src.background.respond', return_value={'action': 'answer', 'answer': '离线重试成功'}):
            self.runner.submit(state.run_id, 'pause')
            self.join(self.runner)
        self.assertEqual(self.store.pending(state.run_id), [])
        self.assertEqual(sum(m['role']=='user' and m['content']=='核查' for m in self.repo.get_state(state.run_id).diagnostics['agent']['messages']),1)

    def test_remote_owner_read_does_not_write_normalization(self):
        guard = WorkerLock(self.repo.db_path, self.state.run_id)
        self.assertTrue(guard.acquire())
        try:
            with patch.object(self.repo, 'save_state') as save:
                _, active = self.runner.read(self.state.run_id)
                self.assertTrue(active)
                save.assert_not_called()
        finally:
            guard.release()


if __name__ == '__main__':
    unittest.main()
