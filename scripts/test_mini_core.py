"""Offline identity, isolation, quotas and restart contracts for mobile."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src.mini.config import Settings
from src.mini.identity import Problem, Registry, digest, exchange_wechat
from src.mini.service import Service


class FakeRunner:
    """Explicit offline task transport, never a simulated model result."""
    def __init__(self, repo, store):
        self.repo, self.store = repo, store
        repo.initialize()
        self.running, self.submissions = set(), []

    def active(self, run_id):
        return run_id in self.running

    def submit(self, run_id, kind):
        self.submissions.append((run_id, kind))
        if kind == 'resume':
            self.running.add(run_id)
        elif kind == 'pause':
            self.running.discard(run_id)


class MiniCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings(root=Path(self.tmp.name), research_enabled=True, daily_runs=2, daily_resumes=2)
        self.now = [1792400000.0]
        self.service = Service(self.settings, runner_factory=FakeRunner, clock=lambda: self.now[0])
        self.registry = self.service.registry
        env = patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-test', 'TAVILY_API_KEY': 'offline-test'})
        env.start()
        self.addCleanup(env.stop)

    def login(self, identity='user-a'):
        return self.registry.login(identity, self.registry.invitation())

    def research(self, uid, key='research-request-00001', **kwargs):
        return self.service.create(uid, '离线接口任务，不调用模型', 2, key, **kwargs)

    def assert_problem(self, code, function, *args, **kwargs):
        with self.assertRaises(Problem) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_invitation_is_single_use_and_expires(self):
        invitation = self.registry.invitation(hours=1)
        first = self.registry.login('a', invitation)
        self.assert_problem('invitation_invalid', self.registry.login, 'b', invitation)
        self.assertEqual(self.registry.login('a')['user_id'], first['user_id'])
        expired = self.registry.invitation(hours=1)
        self.now[0] += 3601
        self.assert_problem('invitation_invalid', self.registry.login, 'c', expired)

    def test_concurrent_redemption_allows_one_new_user(self):
        invitation = self.registry.invitation()
        def attempt(identity):
            try:
                return self.registry.login(identity, invitation)['user_id']
            except Problem:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(attempt, ['a', 'b']))
        self.assertEqual(sum(value is not None for value in ids), 1)

    def test_sessions_are_hashed_expiring_and_revocable(self):
        auth = self.login()
        with self.registry.connect() as db:
            row = dict(db.execute('SELECT * FROM sessions').fetchone())
            self.assertEqual(row['hash'], digest(auth['token']))
            self.assertNotIn(auth['token'], str(row))
        self.assertEqual(self.registry.authenticate(auth['token']), auth['user_id'])
        self.registry.logout(auth['token'])
        self.assert_problem('session_expired', self.registry.authenticate, auth['token'])
        auth = self.registry.login('user-a')
        self.now[0] += self.settings.session_seconds + 1
        self.assert_problem('session_expired', self.registry.authenticate, auth['token'])

    def test_disabling_user_revokes_sessions(self):
        auth = self.login()
        self.registry.disable(auth['user_id'])
        self.assert_problem('session_expired', self.registry.authenticate, auth['token'])
        self.assert_problem('access_disabled', self.registry.login, 'user-a')

    def test_workspaces_and_watchlists_are_separate(self):
        a, b = self.login('a')['user_id'], self.login('b')['user_id']
        self.service.watch(a, '000001', '仅 A 可见')
        self.assertEqual(self.service.workspace(b).store.watches(), [])
        self.assertNotEqual(self.service.workspace(a).repo.db_path, self.service.workspace(b).repo.db_path)
        self.assert_problem('invalid_user', self.service.workspace, '../../data')

    def test_idempotent_creation_does_not_start_twice_or_charge_quota_twice(self):
        uid = self.login()['user_id']
        first, second = self.research(uid), self.research(uid)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(len(self.service.workspace(uid).submissions), 1)
        self.assertEqual(self.service.me(uid)['daily_used'], 1)
        self.assert_problem('request_conflict', self.service.create, uid, '不同问题', 2, 'research-request-00001')

    def test_foreign_run_is_inaccessible_to_read_report_and_command(self):
        a, b = self.login('a')['user_id'], self.login('b')['user_id']
        run = self.research(a)
        self.assertEqual(self.service.history(b)['total'], 0)
        self.assert_problem('run_not_found', self.service.owned, b, run['id'])
        self.assert_problem('run_not_found', self.service.report, b, run['id'], 'anything')
        self.assert_problem('run_not_found', self.service.command, b, run['id'], 'pause')

    def test_user_and_global_concurrency_limits(self):
        ids = [self.login(identity)['user_id'] for identity in ['a', 'b', 'c']]
        self.research(ids[0])
        self.assert_problem('task_capacity', self.research, ids[0], 'second-request-00001')
        self.research(ids[1])
        self.assert_problem('task_capacity', self.research, ids[2])

    def test_daily_quota_and_resume_quota_are_enforced(self):
        uid = self.login()['user_id']
        run = self.research(uid)
        for _ in range(2):
            self.service.command(uid, run['id'], 'pause')
            self.service.command(uid, run['id'], 'resume')
        self.service.command(uid, run['id'], 'pause')
        self.assert_problem('resume_limit', self.service.command, uid, run['id'], 'resume')
        second = self.research(uid, 'second-request-00001')
        self.service.command(uid, second['id'], 'pause')
        self.assert_problem('daily_limit', self.research, uid, 'third-request-000001')

    def test_restart_preserves_task_without_automatic_network_resume(self):
        uid = self.login()['user_id']
        run = self.research(uid)
        restarted = Service(self.settings, runner_factory=FakeRunner, clock=lambda: self.now[0])
        replayed = restarted.create(uid, '离线接口任务，不调用模型', 2, 'research-request-00001')
        self.assertEqual(replayed['id'], run['id'])
        self.assertFalse(replayed['active'])
        self.assertEqual(restarted.workspace(uid).submissions, [])
        restarted.command(uid, run['id'], 'resume')
        self.assertEqual(len(restarted.workspace(uid).submissions), 1)

    def test_disabled_user_does_not_block_other_users_capacity_refresh(self):
        a, b = self.login('a')['user_id'], self.login('b')['user_id']
        run = self.research(a)
        self.registry.disable(a)
        self.service.workspace(a, internal=True).running.clear()
        self.assertTrue(self.research(b)['id'])

    def test_research_is_opt_in_and_unknown_commands_are_rejected(self):
        uid = self.login()['user_id']
        disabled = Service(replace(self.settings, research_enabled=False), runner_factory=FakeRunner)
        self.assert_problem('research_disabled', disabled.create, uid, '离线', 2, 'disabled-request-0001')
        self.assert_problem('invalid_command', self.service.command, uid, 'none', 'budget')
        self.assert_problem('invalid_research', self.service.create, uid, ' ', 2, 'blank-request-0000001')
        self.assert_problem('invalid_research', self.service.create, uid, '问题', 7, 'large-budget-0000001')

    def test_wechat_failure_does_not_expose_upstream_secrets(self):
        settings = replace(self.settings, appid='appid', appsecret='must-not-leak')
        with patch('requests.get', side_effect=ConnectionError('must-not-leak')):
            self.assert_problem('wechat_unavailable', exchange_wechat, settings, 'private-code')
        with patch('requests.get') as get:
            get.return_value.json.return_value = {'openid': 'verified-user', 'session_key': 'must-not-leak'}
            self.assertEqual(exchange_wechat(settings, 'private-code'), 'appid:verified-user')
            self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_real_mode_never_accepts_demo_identity(self):
        self.assert_problem('demo_disabled', self.registry.login, 'demo-a', trusted_demo=True)

    def test_company_subject_is_in_goal_and_other_symbols_are_rejected(self):
        uid = self.login()['user_id']
        run = self.service.create(uid, '核查现金流', 2, 'company-request-00001', '000001')
        state = self.service.workspace(uid).repo.get_state(run['id'])
        self.assertIn('000001', state.topic)
        self.assertEqual(state.diagnostics['agent']['stock_symbol'], '000001')
        self.assertEqual(self.service.workspace(uid).store.stock_runs('000001')[0]['run_id'], run['id'])
        self.service.command(uid, run['id'], 'pause')
        self.assert_problem('company_scope', self.service.create, uid, '研究000002', 2, 'other-company-000001', '000001')

    def test_lan_demo_requires_opt_in_and_an_explicit_private_interface(self):
        from scripts.serve_miniprogram import validate_binding
        validate_binding('127.0.0.1', demo=True, lan_demo=False)
        validate_binding('192.168.1.2', demo=True, lan_demo=True)
        for host in ('0.0.0.0', '8.8.8.8', '::', 'localhost', '169.254.1.2', '100.64.1.2'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                validate_binding(host, demo=True, lan_demo=True)
        with self.assertRaises(ValueError):
            validate_binding('192.168.1.2', demo=True, lan_demo=False)
        with self.assertRaises(ValueError):
            validate_binding('192.168.1.2', demo=False, lan_demo=True)

    def test_real_settings_cannot_enable_demo_lan_mode(self):
        with self.assertRaises(ValueError):
            replace(self.settings, lan_demo=True)


if __name__ == '__main__':
    unittest.main()
