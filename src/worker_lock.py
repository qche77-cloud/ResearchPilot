"""OS-backed single-writer locks on a local filesystem.

The handle is held throughout a tool/model call. Process death releases it, so
there is no heartbeat expiry that could permit a second writer during a slow API.
All worker processes sharing a database must run this protocol.
"""
import errno
import hashlib
import os
from pathlib import Path


class WorkerLock:
    def __init__(self, database, resource):
        database = Path(database).resolve()
        key = hashlib.sha256(str(resource).encode()).hexdigest()
        self.path = database.parent / (database.name + '.locks') / (key + '.lock')
        self.handle = None

    def acquire(self, create=True):
        if self.handle is not None:
            return True
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        elif not self.path.exists():
            return True  # Probe only: there cannot be an owner without a lock file.
        handle = open(self.path, 'a+b' if create else 'r+b')
        try:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                return False
            raise
        self.handle = handle
        return True

    def release(self):
        if self.handle is None:
            return
        handle, self.handle = self.handle, None
        try:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    @classmethod
    def held(cls, database, resource):
        probe = cls(database, resource)
        if probe.acquire(create=False):
            probe.release()
            return False
        return True
