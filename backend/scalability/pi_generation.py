"""One PI generator per database across threads and worker processes."""
from functools import wraps
import errno
import os
from pathlib import Path
from threading import Lock

from flask import jsonify
from backend import database

_guard = Lock()
_threads = {}


def serialized_generation(function):
    @wraps(function)
    def generate(*args, **kwargs):
        path = str(Path(database.DB_PATH).resolve()) + '.pi-generation.lock'
        with _guard:
            lock = _threads.setdefault(path, Lock())
        def waiting():
            response = jsonify(status='waiting', retry_after_ms=1000,
                               message='Another PI is being generated. Waiting for it to finish…')
            response.status_code = 202
            response.headers['Retry-After'] = '1'
            response.headers['Cache-Control'] = 'no-store'
            return response
        if not lock.acquire(blocking=False):
            return waiting()
        handle = None
        acquired = False
        try:
            handle = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            if os.fstat(handle).st_size == 0:
                os.write(handle, b'0')
            os.lseek(handle, 0, os.SEEK_SET)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as error:
                if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    return waiting()
                raise
            return function(*args, **kwargs)
        finally:
            if handle is not None:
                try:
                    if acquired:
                        if os.name == 'nt':
                            import msvcrt
                            os.lseek(handle, 0, os.SEEK_SET)
                            msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle, fcntl.LOCK_UN)
                finally:
                    os.close(handle)
            lock.release()
    return generate
