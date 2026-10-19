"""HTTP integration with in-process transport and temporary workspaces only."""
from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from src.mini.api import create_app
from src.mini.config import Settings
from src.mini.service import Service
from scripts.test_mini_core import FakeRunner


class MiniApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings(root=Path(self.tmp.name), research_enabled=True)
        self.service = Service(self.settings, runner_factory=FakeRunner)
        self.app = create_app(self.settings, service=self.service, exchange=lambda settings, code: 'test-app:' + code)
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        env = patch.dict(os.environ, {'OPENAI_API_KEY': 'offline-test', 'TAVILY_API_KEY': 'offline-test'})
        env.start()
        self.addCleanup(env.stop)

    def login(self, code='a'):
        result = self.client.post('/v1/auth/wechat', json={'code': code, 'invitation': self.service.registry.invitation()})
        self.assertEqual(result.status_code, 200, result.text)
        return {'Authorization': 'Bearer ' + result.json()['token']}, result.json()['user_id']

    def create(self, auth):
        result = self.client.post('/v1/runs', headers={**auth, 'Idempotency-Key': 'http-request-key-000001'}, json={'topic':'仅离线测试', 'budget':2})
        self.assertEqual(result.status_code, 202, result.text)
        return result.json()

    def test_protected_reads_and_writes_require_login(self):
        for path in ['/v1/me', '/v1/runs', '/v1/watchlist', '/v1/companies/000001', '/v1/runs/foreign']:
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.post('/v1/runs', json={'topic':'test', 'budget':2}).status_code, 401)
        with self.service.registry.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], 0)

    def test_demo_login_is_unavailable_on_real_server(self):
        self.assertEqual(self.client.post('/v1/auth/demo', json={'identity':'A'}).status_code, 403)
        self.assertEqual(self.client.get('/preview/').status_code, 404)

    def test_cross_user_access_returns_404_and_watchlists_are_private(self):
        a, _ = self.login('a')
        b, _ = self.login('b')
        run = self.create(a)
        for suffix in ['', '/reports/unknown']:
            self.assertEqual(self.client.get('/v1/runs/' + run['id'] + suffix, headers=b).status_code, 404)
        self.assertEqual(self.client.post('/v1/runs/' + run['id'] + '/commands', headers=b, json={'kind':'pause'}).status_code, 404)
        self.assertEqual(self.client.get('/v1/runs', headers=b).json()['total'], 0)
        self.client.post('/v1/watchlist', headers=a, json={'symbol':'000001','name':'A 的自选'})
        self.assertEqual(self.client.get('/v1/watchlist', headers=b).json()['items'], [])

    def test_idempotency_header_is_required_and_conflicts_are_reported(self):
        auth, _ = self.login()
        self.assertEqual(self.client.post('/v1/runs', headers=auth, json={'topic':'test'}).status_code, 422)
        first, second = self.create(auth), self.create(auth)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(self.client.post('/v1/runs', headers={**auth,'Idempotency-Key':'http-request-key-000001'}, json={'topic':'different'}).status_code, 409)

    def test_request_validation_never_echoes_private_login_code(self):
        result = self.client.post('/v1/auth/wechat', json={'code':'must-not-leak','invitation':{},'extra':'private'})
        self.assertEqual(result.status_code, 422)
        self.assertNotIn('must-not-leak', result.text)

    def test_oversized_and_chunked_requests_are_rejected(self):
        for data in ['x' * 32769, iter([b'x' * 16000, b'y' * 17000])]:
            result = self.client.post('/v1/auth/wechat', content=data, headers={'Content-Type':'application/json'})
            self.assertEqual(result.status_code, 413, result.text)

    def test_logout_revokes_token_and_sensitive_responses_are_not_cached(self):
        auth, _ = self.login()
        response = self.client.get('/v1/me', headers=auth)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.post('/v1/auth/logout', headers=auth).status_code, 200)
        self.assertEqual(self.client.get('/v1/me', headers=auth).status_code, 401)

    def test_invalid_symbol_budget_and_pagination_are_rejected(self):
        auth, _ = self.login()
        self.assertEqual(self.client.post('/v1/watchlist', headers=auth, json={'symbol':'999999','name':'x'}).status_code, 422)
        self.assertEqual(self.client.get('/v1/runs?limit=1000', headers=auth).status_code, 422)
        self.assertEqual(self.client.post('/v1/runs', headers=auth, json={'topic':'x','budget':True}).status_code, 422)
        self.assertEqual(self.client.post('/v1/runs/foreign/commands', headers=auth, json={'kind':'budget'}).status_code, 422)

    def test_login_requests_are_rate_limited(self):
        results = [self.client.post('/v1/auth/demo', json={'identity':'A'}).status_code for _ in range(11)]
        self.assertEqual(results[-1], 429)

    def test_demo_flow_and_report_version_reads_are_immutable(self):
        with TemporaryDirectory() as folder:
            settings = Settings(root=Path(folder), mode='demo')
            app = create_app(settings)
            with TestClient(app) as client:
                login = client.post('/v1/auth/demo', json={'identity':'A'})
                self.assertEqual(login.status_code, 200, login.text)
                auth = {'Authorization':'Bearer ' + login.json()['token']}
                run = client.get('/v1/runs', headers=auth).json()['items'][0]
                worker, state = app.state.service.owned(login.json()['user_id'], run['id'])
                before = worker.repo.get_run(run['id'])
                version = run['versions'][0]['id']
                path = '/v1/runs/' + run['id'] + '/reports/' + version
                report = client.get(path, headers=auth).json()
                self.assertIn('虚构', report['sections'][0]['content'])
                self.assertEqual(report['id'], version)
                self.assertEqual(report['cards'][0]['eid'], 'E1')
                self.assertEqual(worker.repo.get_run(run['id']), before)
                self.assertEqual(client.get('/preview/').status_code, 200)
                self.assertEqual(client.post('/v1/auth/wechat', json={'code':'real'}).status_code, 403)
                self.assertTrue(client.get('/v1/companies/000001', headers=auth).json()['analysis']['usable_records'])

    def test_real_runner_receives_the_authenticated_users_workbench(self):
        with TemporaryDirectory() as folder:
            settings = replace(self.settings, root=Path(folder))
            service = Service(settings)
            app = create_app(settings, service=service, exchange=lambda settings, code: 'offline-verified-user')
            entered = threading.Event()
            stores = []

            def offline_step(state, *, store):
                stores.append(store.path)
                state.mark_completed()
                entered.set()

            with patch('src.background.tick', side_effect=offline_step), TestClient(app) as client:
                result = client.post('/v1/auth/wechat', json={'code':'offline-code','invitation':service.registry.invitation()}).json()
                auth = {'Authorization':'Bearer ' + result['token'], 'Idempotency-Key':'real-worker-fixture-0001'}
                created = client.post('/v1/runs', headers=auth, json={'topic':'离线后台集成测试','budget':2})
                self.assertEqual(created.status_code, 202, created.text)
                self.assertTrue(entered.wait(3))
                worker = service.workspace(result['user_id'])
                deadline = time.monotonic() + 3
                while worker.active(created.json()['id']) and time.monotonic() < deadline:
                    time.sleep(.01)
                final = client.get('/v1/runs/' + created.json()['id'], headers=auth).json()
                self.assertTrue(final['completed'])
                self.assertFalse(final['active'])
                self.assertEqual(stores, [worker.store.path])
                self.assertEqual(worker.store.pending(final['id']), [])


if __name__ == '__main__':
    unittest.main()
