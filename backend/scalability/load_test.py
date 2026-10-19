"""Read-only authenticated concurrency probe for a running deployment."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import time
from threading import Barrier, BrokenBarrierError, Semaphore
from urllib.parse import urljoin

import requests


def percentile(values, fraction):
    return sorted(values)[max(0, int(len(values) * fraction + 0.999999) - 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:5062')
    parser.add_argument('--users', type=int, default=100)
    parser.add_argument('--requests-per-user', type=int, default=10)
    parser.add_argument('--login-concurrency', type=int, default=4)
    parser.add_argument('--path', action='append', default=[])
    parser.add_argument('--timeout', type=float, default=20)
    args = parser.parse_args()
    if args.users < 1 or args.requests_per_user < 1 or args.login_concurrency < 1 or args.timeout <= 0:
        parser.error('users, requests-per-user, login-concurrency and timeout must be positive')
    paths = args.path or ['/api/me', '/api/leads', '/api/orders']
    if any(not path.startswith('/') or path.startswith('//') for path in paths):
        parser.error('--path must be a local absolute path')
    username = os.environ.get('AMT_LOAD_USERNAME')
    password = os.environ.get('AMT_LOAD_PASSWORD')
    if not username or not password:
        parser.error('Set AMT_LOAD_USERNAME and AMT_LOAD_PASSWORD in the environment')
    base = args.base_url.rstrip('/') + '/'
    barrier = Barrier(args.users)
    login_slots = Semaphore(args.login_concurrency)

    def user_run(index):
        session = requests.Session()
        try:
            with login_slots:
                login = session.post(urljoin(base, 'login'),
                    data={'username': username, 'password': password},
                    headers={'Connection': 'close'},
                    allow_redirects=False, timeout=args.timeout)
            if login.status_code != 302:
                barrier.abort()
                return [], [{'phase': 'login', 'status': login.status_code}]
            try:
                barrier.wait(timeout=max(120, args.timeout * 6))
            except BrokenBarrierError:
                return [], [{'phase': 'login', 'error': 'A virtual user did not log in'}]
            timings, errors = [], []
            for number in range(args.requests_per_user):
                path = paths[(index + number) % len(paths)]
                start = time.perf_counter()
                try:
                    response = session.get(urljoin(base, path.lstrip('/')),
                                           timeout=args.timeout)
                    timings.append((time.perf_counter() - start) * 1000)
                    if response.status_code != 200:
                        errors.append({'path': path, 'status': response.status_code})
                except requests.RequestException as error:
                    errors.append({'path': path, 'error': type(error).__name__})
            return timings, errors
        except requests.RequestException as error:
            barrier.abort()
            return [], [{'phase': 'login', 'error': type(error).__name__}]
        finally:
            session.close()

    start = time.perf_counter()
    timings, errors = [], []
    with ThreadPoolExecutor(max_workers=args.users) as pool:
        futures = [pool.submit(user_run, index) for index in range(args.users)]
        for future in as_completed(futures):
            try:
                result, failures = future.result()
                timings.extend(result)
                errors.extend(failures)
            except Exception as error:
                errors.append({'phase': 'worker', 'error': type(error).__name__})
    summary = {'users': args.users, 'requests': len(timings),
               'errors': len(errors), 'elapsed_seconds': round(time.perf_counter()-start, 2),
               'p50_ms': round(percentile(timings, .50), 1) if timings else None,
               'p95_ms': round(percentile(timings, .95), 1) if timings else None,
               'p99_ms': round(percentile(timings, .99), 1) if timings else None,
               'sample_errors': errors[:10]}
    print(json.dumps(summary, indent=2))
    raise SystemExit(1 if errors else 0)


if __name__ == '__main__':
    main()
