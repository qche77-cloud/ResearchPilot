"""Optional authenticated HTTP boundary, not imported by Streamlit."""
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
import threading
import time
from typing import Literal

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from src.mini.config import Settings
from src.mini.identity import Problem, exchange_wechat
from src.mini.service import Service
from src.worker_lock import WorkerLock


class LimitedBody:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        chunks, length = [], 0
        while True:
            part = await receive()
            if part['type'] == 'http.disconnect':
                return
            chunk = part.get('body', b'')
            length += len(chunk)
            if length > 32768:
                return await JSONResponse({'error': {'code': 'body_too_large', 'message': '请求内容过大'}}, 413)(scope, receive, send)
            chunks.append(chunk)
            if not part.get('more_body', False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
            return await receive()

        return await self.app(scope, replay, send)


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Login(Input):
    code: str = Field(min_length=1, max_length=256)
    invitation: str = Field(default='', max_length=128)


class DemoLogin(Input):
    identity: Literal['A', 'B'] = 'A'


class Research(Input):
    topic: str = Field(min_length=1, max_length=1200)
    budget: int = Field(default=2, ge=2, le=16)
    symbol: str | None = Field(default=None, pattern=r'^\d{6}$')


class Command(Input):
    kind: Literal['pause', 'resume']


class Watch(Input):
    symbol: str = Field(pattern=r'^\d{6}$')
    name: str = Field(default='', max_length=40)


def create_app(settings=None, *, service=None, exchange=None):
    settings = settings or Settings.from_env()
    service = service or Service(settings)
    exchange = exchange or exchange_wechat
    guard = WorkerLock(service.registry.path, 'mini_api_server')

    @asynccontextmanager
    async def lifespan(app):
        if not guard.acquire():
            raise RuntimeError('A mini-program API already owns this data root; use one worker')
        try:
            yield
        finally:
            # Running daemon tasks are checkpointed by Runner. Do not release a
            # separate process-wide quota lock during hot reload of live tasks.
            guard.release()

    app = FastAPI(title='ResearchPilot Mobile', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.service = service
    app.add_middleware(LimitedBody)
    calls = defaultdict(deque)
    limiter_lock = threading.Lock()

    @app.middleware('http')
    async def boundary(request, call_next):
        if request.url.path.startswith('/v1/'):
            peer = request.client.host if request.client else 'unknown'
            kind = 'login' if request.url.path.startswith('/v1/auth/') else 'api'
            key = (peer, kind)
            now = time.monotonic()
            with limiter_lock:
                if len(calls) > 2048:
                    for old in list(calls):
                        if not calls[old] or calls[old][-1] < now - 60:
                            del calls[old]
                    if len(calls) > 2048 and key not in calls:
                        return JSONResponse({'error': {'code': 'rate_limit', 'message': '访问较多，请稍后重试'}}, 429)
                queue = calls[key]
                while queue and queue[0] < now - 60:
                    queue.popleft()
                if len(queue) >= (10 if kind == 'login' else 120):
                    return JSONResponse({'error': {'code': 'rate_limit', 'message': '访问较多，请稍后重试'}}, 429)
                queue.append(now)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.exception_handler(Problem)
    async def problem(request, error):
        return JSONResponse({'error': {'code': error.code, 'message': error.message}}, error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error):
        # Pydantic's default error output contains submitted auth codes/tokens.
        return JSONResponse({'error': {'code': 'invalid_input', 'message': '请求字段或格式不正确'}}, 422)

    @app.exception_handler(ValueError)
    async def bad_value(request, error):
        return JSONResponse({'error': {'code': 'invalid_value', 'message': '输入内容未通过校验'}}, 422)

    @app.exception_handler(Exception)
    async def unavailable(request, error):
        return JSONResponse({'error': {'code': 'unavailable', 'message': '服务暂不可用，请稍后重试'}}, 503)

    def bearer(authorization: str | None = Header(default=None)):
        if not authorization or not authorization.startswith('Bearer '):
            raise Problem(401, 'login_required', '请先登录')
        return authorization[7:]

    def user(token=Depends(bearer)):
        return service.registry.authenticate(token)

    @app.get('/health')
    def health():
        return dict(status='ok', mode=settings.mode, lan_demo=settings.lan_demo)

    @app.post('/v1/auth/wechat')
    def login(data: Login):
        if settings.mode != 'wechat':
            raise Problem(403, 'wechat_disabled', '离线演示服务不进行微信登录')
        result = service.registry.login(exchange(settings, data.code), data.invitation)
        result['mode'] = 'wechat'
        return result

    @app.post('/v1/auth/demo')
    def demo_login(data: DemoLogin):
        if settings.mode != 'demo':
            raise Problem(403, 'demo_disabled', '正式服务不允许演示登录')
        result = service.registry.login('explicit-demo-' + data.identity, trusted_demo=True)
        from src.mini.demo import seed
        with service.lock:
            seed(service, result['user_id'])
        result['mode'] = 'demo'
        return result

    @app.post('/v1/auth/logout')
    def logout(uid=Depends(user), token=Depends(bearer)):
        service.registry.logout(token)
        return {'logged_out': True}

    @app.get('/v1/me')
    def me(uid=Depends(user)):
        return service.me(uid)

    @app.get('/v1/runs')
    def runs(limit: int = 20, offset: int = 0, uid=Depends(user)):
        return service.history(uid, limit, offset)

    @app.post('/v1/runs', status_code=202)
    def create(data: Research, uid=Depends(user), idempotency_key: str | None = Header(default=None)):
        return service.create(uid, data.topic, data.budget, idempotency_key, data.symbol)

    @app.get('/v1/runs/{run_id}')
    def run(run_id: str, uid=Depends(user)):
        worker, state = service.owned(uid, run_id)
        return service.view(worker, state)

    @app.post('/v1/runs/{run_id}/commands')
    def command(run_id: str, data: Command, uid=Depends(user)):
        return service.command(uid, run_id, data.kind)

    @app.get('/v1/runs/{run_id}/reports/{version}')
    def report(run_id: str, version: str, uid=Depends(user)):
        return service.report(uid, run_id, version)

    @app.get('/v1/watchlist')
    def watchlist(uid=Depends(user)):
        return dict(items=service.workspace(uid).store.watches())

    @app.post('/v1/watchlist')
    def watch(data: Watch, uid=Depends(user)):
        return dict(items=service.watch(uid, data.symbol, data.name))

    @app.delete('/v1/watchlist/{symbol}')
    def unwatch(symbol: str, uid=Depends(user)):
        from src.stock_data import normalize_symbol
        normalize_symbol(symbol)
        service.workspace(uid).store.unwatch(symbol)
        return {'removed': True}

    @app.get('/v1/companies/{symbol}')
    def company(symbol: str, uid=Depends(user)):
        return service.company(uid, symbol)

    if settings.mode == 'demo':
        app.mount('/preview', StaticFiles(directory=Path(__file__).resolve().parents[2] / 'mobile-preview', html=True), name='preview')
    return app
