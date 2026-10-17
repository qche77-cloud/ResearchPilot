"""Explicit offline regression manifest; never run live test_*.py indiscriminately."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
UNIT_MODULES = [
    'scripts.test_agent', 'scripts.test_workbench', 'scripts.test_stock_research',
    'scripts.test_judgments', 'scripts.test_stock_presentation',
    'scripts.test_ui_workspace',
    'scripts.test_studio',
    'scripts.test_worker_reliability',
    'scripts.test_cockpit',
    'scripts.test_offline_guard',
    'scripts.test_quant_foundation',
    'scripts.test_claim_verification',
    'scripts.test_research_tools',
]
SCRIPT_MODULES = [
    'scripts.test_research_health', 'scripts.test_v112_reader_reliability',
    'scripts.test_v121_regression', 'scripts.test_v12_evidence_strategy',
    'scripts.test_v13_research_state', 'scripts.test_v13_sqlite_storage',
    'scripts.test_v13_pipeline_state', 'scripts.test_v13_persisted_research',
    'scripts.test_v13_app_persistence', 'scripts.test_v13_history_queries',
    'scripts.test_v13_history_ui',
]


def make_internal_socketpair(original_connect):
    """Windows socketpair fallback with one private, self-created loopback endpoint.

    This does not allow ordinary loopback connections. Only the two sockets owned
    by this call use the saved connector, so asyncio IPC works under the guard.
    """
    import socket

    def socketpair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
        if family not in (socket.AF_INET, socket.AF_INET6):
            raise ValueError('Only AF_INET and AF_INET6 are supported')
        if type != socket.SOCK_STREAM or proto != 0:
            raise ValueError('Only SOCK_STREAM with protocol zero is supported')
        host = '127.0.0.1' if family == socket.AF_INET else '::1'
        client = accepted = None
        with socket.socket(family, type, proto) as listener:
            listener.settimeout(5)
            listener.bind((host, 0))
            listener.listen(1)
            try:
                client = socket.socket(family, type, proto)
                client.settimeout(5)
                original_connect(client, listener.getsockname())
                accepted, _ = listener.accept()
                client.settimeout(None)
                accepted.settimeout(None)
                return accepted, client
            except BaseException:
                if client is not None:
                    client.close()
                if accepted is not None:
                    accepted.close()
                raise

    return socketpair


def install_guard():
    """Block external/ordinary network and production DB access; permit socketpair IPC."""
    import socket
    import sqlite3
    from urllib.parse import unquote
    os.environ['RESEARCHPILOT_OFFLINE_TEST'] = '1'
    if getattr(socket.socket.connect, '_researchpilot_offline_guard', False):
        return
    original_socket_connect = socket.socket.connect

    def blocked(*args, **kwargs):
        raise RuntimeError('OFFLINE_NETWORK_BLOCKED')

    blocked._researchpilot_offline_guard = True
    # Native socketpair uses local IPC directly. The Python Windows fallback
    # instead calls connect(), which would otherwise trip this offline guard.
    if os.name == 'nt' and socket.socketpair.__module__ == 'socket':
        socket.socketpair = make_internal_socketpair(original_socket_connect)
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.getaddrinfo = blocked
    original_connect = sqlite3.connect

    def connect(database, *args, **kwargs):
        text = os.fsdecode(database)
        if text != ':memory:':
            path = text[5:].split('?', 1)[0] if text.startswith('file:') else text
            resolved = Path(unquote(path)).resolve()
            if resolved == (ROOT / 'data').resolve() or (ROOT / 'data').resolve() in resolved.parents:
                raise RuntimeError('OFFLINE_PRODUCTION_DB_BLOCKED')
        return original_connect(database, *args, **kwargs)

    sqlite3.connect = connect


def child(kind, module):
    install_guard()
    if kind == 'unit':
        import unittest
        suite = unittest.defaultTestLoader.loadTestsFromName(module)
        if suite.countTestCases() == 0:
            raise RuntimeError('ZERO_TESTS_COLLECTED')
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    import runpy
    sys.argv = [module]
    runpy.run_module(module, run_name='__main__')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='artifacts/offline-tests.json')
    parser.add_argument('--child', nargs=2, choices=None, metavar=('KIND', 'MODULE'), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        return child(*args.child)
    modules = [('unit', n) for n in UNIT_MODULES] + [('script', n) for n in SCRIPT_MODULES]
    new_tests = ROOT / 'scripts' / 'test_v2_quality.py'
    if new_tests.is_file():
        modules.append(('unit', 'scripts.test_v2_quality'))
    for name in ('test_v2_financial', 'test_v2_autonomy', 'test_v2_memory'):
        if (ROOT / 'scripts' / (name + '.py')).is_file():
            modules.append(('unit', 'scripts.' + name))
    if (ROOT / 'evals' / 'agent_cases.json').is_file():
        modules.append(('script', 'scripts.evaluate_agent'))
    modules.append(('script', 'scripts.evaluate_claims'))
    modules.append(('script', 'scripts.evaluate_research_tools'))
    rows = []
    for kind, module in modules:
        start = time.perf_counter()
        try:
            process = subprocess.run(
                [sys.executable, '-m', 'scripts.run_offline_tests', '--child', kind, module],
                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90,
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'},
            )
            output = process.stdout + process.stderr
            count = re.search(r'Ran (\d+) tests?', output) if kind == 'unit' else None
            rows.append(dict(module=module, kind=kind, exit_code=process.returncode,
                             passed=process.returncode == 0 and (kind != 'unit' or (count and int(count[1]) > 0)),
                             tests=int(count[1]) if count else None, stdout=process.stdout, stderr=process.stderr,
                             seconds=round(time.perf_counter() - start, 3)))
        except subprocess.TimeoutExpired:
            rows.append(dict(module=module, kind=kind, passed=False, timeout_seconds=90))
        print(f'{"PASS" if rows[-1]["passed"] else "FAIL"} {module}', flush=True)
        if not rows[-1]['passed']:
            detail = (rows[-1].get('stdout', '') + rows[-1].get('stderr', ''))[-8000:]
            if detail:
                print(detail, flush=True)
    result = dict(mode='offline_network_blocked', production_db_access='blocked',
                  network_policy='external_and_ordinary_loopback_blocked; internal_socketpair_allowed', python=sys.version,
                  suites=len(rows), passed_suites=sum(bool(r['passed']) for r in rows),
                  unit_tests=sum(r.get('tests') or 0 for r in rows), results=rows)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{result["passed_suites"]}/{len(rows)} suites; {result["unit_tests"]} unit tests; {target}')
    return 0 if all(r['passed'] for r in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
