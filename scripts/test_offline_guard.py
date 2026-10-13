"""Regression for Windows asyncio IPC under offline test isolation."""
import asyncio
import socket
import sqlite3
import unittest
from scripts.run_offline_tests import install_guard, ROOT


class OfflineGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_guard()

    def test_socketpair_roundtrip_does_not_enable_other_connections(self):
        a, b = socket.socketpair()
        with a, b:
            a.settimeout(5)
            b.settimeout(5)
            a.sendall(b'private-ipc')
            self.assertEqual(b.recv(64), b'private-ipc')
        with socket.socket() as sock:
            with self.assertRaisesRegex(RuntimeError, 'OFFLINE_NETWORK_BLOCKED'):
                sock.connect(('127.0.0.1', 8504))

    def test_asyncio_loop_initializes_and_runs_with_network_guard(self):
        loop = asyncio.new_event_loop()
        try:
            self.assertEqual(loop.run_until_complete(asyncio.sleep(0, result='ok')), 'ok')
        finally:
            loop.close()

    def test_direct_connections_and_dns_remain_blocked(self):
        for address in [('127.0.0.1', 8504), ('::1', 8504), ('192.0.2.1', 443)]:
            for method in ('connect', 'connect_ex'):
                with socket.socket() as sock:
                    with self.assertRaisesRegex(RuntimeError, 'OFFLINE_NETWORK_BLOCKED'):
                        getattr(sock, method)(address)
        with self.assertRaisesRegex(RuntimeError, 'OFFLINE_NETWORK_BLOCKED'):
            socket.getaddrinfo('example.invalid', 443)

    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows fallback argument contract')
    def test_socketpair_rejects_non_ip_families_datagrams_and_protocols(self):
        for kwargs in ({'family': -1}, {'type': socket.SOCK_DGRAM}, {'proto': 1}):
            with self.assertRaises(ValueError):
                socket.socketpair(**kwargs)

    def test_install_is_idempotent_without_capturing_the_blocked_connector(self):
        before = socket.socket.connect
        install_guard()
        self.assertIs(socket.socket.connect, before)
        a, b = socket.socketpair()
        a.close()
        b.close()

    def test_production_database_stays_blocked(self):
        for path in (ROOT / 'data' / 'research.db', 'file:' + (ROOT / 'data' / 'research.db').as_posix() + '?mode=ro'):
            with self.assertRaisesRegex(RuntimeError, 'OFFLINE_PRODUCTION_DB_BLOCKED'):
                sqlite3.connect(path)


if __name__ == '__main__':
    unittest.main()
