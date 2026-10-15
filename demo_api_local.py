"""Standalone synthetic loopback demo. No real API, client data or credentials."""
import argparse
import hashlib
import json
import platform
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIELDS = ('ticket_id', 'status', 'opened_at')


class DemoFailure(Exception):
    """An explicit acceptance check failed, including under Python -O."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def export_paginated(fetch, start_cursor=None, max_pages=5):
    cursor = start_cursor
    seen, ids, records = set(), set(), []
    pages = 0
    while True:
        if cursor in seen:
            raise ValueError('Repeated pagination cursor')
        seen.add(cursor)
        if pages >= max_pages:
            raise ValueError('Page cap reached before completion')
        page = fetch(cursor)
        pages += 1
        if not isinstance(page, dict) or set(page) != {'data', 'next_cursor'} or not isinstance(page['data'], list):
            raise ValueError('Unsupported API schema')
        for record in page['data']:
            if not isinstance(record, dict) or set(record) != set(FIELDS) or not all(isinstance(record[k], str) for k in FIELDS):
                raise ValueError('Unsupported row schema')
            if not record['ticket_id'] or record['ticket_id'] in ids:
                raise ValueError('Missing or repeated API record id')
            ids.add(record['ticket_id'])
            records.append(record)
        following = page['next_cursor']
        if following is None:
            return {'records': records, 'pages': pages, 'complete': True}
        if not isinstance(following, str) or not following:
            raise ValueError('Unsupported pagination cursor')
        cursor = following


class LocalAPI:
    def __init__(self, base):
        parsed = urllib.parse.urlsplit(base)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1':
            raise ValueError('Only the synthetic loopback server is permitted')
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.calls = []

    def fetch(self, cursor):
        url = self.base + '/tickets' + ('?' + urllib.parse.urlencode({'cursor': cursor}) if cursor is not None else '')
        for attempt in range(2):
            try:
                with self.opener.open(urllib.request.Request(url, method='GET'), timeout=2) as response:
                    raw = response.read(65537)
                    self.calls.append({'status': response.status, 'attempt': attempt + 1})
                    if len(raw) > 65536:
                        raise ValueError('Response cap exceeded')
                    return json.loads(raw.decode('utf-8'))
            except urllib.error.HTTPError as exc:
                self.calls.append({'status': exc.code, 'attempt': attempt + 1})
                if exc.code not in (429, 502, 503, 504) or attempt == 1:
                    raise
                try:
                    seconds = float(exc.headers.get('Retry-After', '0.05'))
                except ValueError:
                    raise ValueError('Unsupported Retry-After') from None
                if not 0 <= seconds <= 2:
                    raise ValueError('Retry-After exceeds the short-demo budget')
                time.sleep(seconds)
        raise DemoFailure('Unreachable retry state')


def check(tests, name, measured, expected):
    passed = measured == expected
    tests.append({'test': name, 'passed': passed, 'measured': measured, 'expected': expected})
    if not passed:
        raise DemoFailure(name)


def write_json(path, value):
    path.write_bytes((json.dumps(value, indent=2, ensure_ascii=True) + '\n').encode('utf-8'))


def run(output):
    state = {'mode': 'success', 'count': 0}
    methods, tests = [], []
    report = None
    failure = None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            methods.append('GET')
            state['count'] += 1
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            cursor = query.get('cursor', [None])[0]
            if state['mode'] == 'success' and state['count'] == 1:
                self.send_response(429)
                self.send_header('Retry-After', '0')
                self.end_headers()
                self.wfile.write(b'{"error":"synthetic_rate_limit"}')
                return
            if state['mode'] == 'unauthorized':
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"error":"synthetic_not_authorized"}')
                return
            if state['mode'] == 'unavailable':
                self.send_response(503)
                self.send_header('Retry-After', '0')
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            if state['mode'] == 'invalid_json':
                self.wfile.write(b'{broken')
                return
            following = 'page-2' if cursor is None else None
            item = {'ticket_id': 'T-001' if cursor is None else 'T-002',
                    'status': 'open' if cursor is None else 'closed', 'opened_at': '2026-10-15'}
            self.wfile.write(json.dumps({'data': [item], 'next_cursor': following}).encode('utf-8'))

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:' + str(server.server_port)
    try:
        client = LocalAPI(base)
        report = export_paginated(client.fetch)
        measured = {'complete': report['complete'], 'pages': report['pages'],
                    'records': len(report['records']), 'ids': [r['ticket_id'] for r in report['records']],
                    'HTTP_statuses': [c['status'] for c in client.calls], 'HTTP_requests': state['count']}
        check(tests, 'two_pages_and_bounded_429_retry', measured,
              {'complete': True, 'pages': 2, 'records': 2, 'ids': ['T-001', 'T-002'],
               'HTTP_statuses': [429, 200, 200], 'HTTP_requests': 3})
        write_json(output / 'report.json', report)
        state.update(mode='plain', count=0)
        legacy = LocalAPI(base).fetch(None)['data']
        state.update(mode='plain', count=0)
        corrected = export_paginated(LocalAPI(base).fetch)['records']
        check(tests, 'synthetic_before_after_missing_second_page',
              {'legacy_records': len(legacy), 'corrected_records': len(corrected)},
              {'legacy_records': 1, 'corrected_records': 2})
        for mode, statuses, expected_error in (
                ('unauthorized', [401], 'HTTPError'),
                ('unavailable', [503, 503], 'HTTPError'),
                ('invalid_json', [200], 'JSONDecodeError')):
            state.update(mode=mode, count=0)
            client = LocalAPI(base)
            error_name = None
            try:
                export_paginated(client.fetch)
            except (urllib.error.HTTPError, ValueError) as exc:
                error_name = type(exc).__name__
            check(tests, mode,
                  {'error_type': error_name, 'HTTP_requests': state['count'],
                   'HTTP_statuses': [c['status'] for c in client.calls],
                   'partial_report_published': (output / (mode + '.json')).exists()},
                  {'error_type': expected_error, 'HTTP_requests': len(statuses),
                   'HTTP_statuses': statuses, 'partial_report_published': False})
    except Exception as exc:
        failure = {'type': type(exc).__name__, 'check': str(exc) if isinstance(exc, DemoFailure) else None}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    passed = failure is None and len(tests) == 5 and all(t['passed'] for t in tests) and not thread.is_alive()
    receipt = {'status': 'PASS_LOCAL_HTTP_SYNTHETIC_ONLY' if passed else 'FAIL_LOCAL_HTTP_SYNTHETIC',
               'fixture': 'Invented tickets only; no client data or credentials.',
               'runtime': {'implementation': platform.python_implementation(), 'version': platform.python_version(),
                           'python_executable_sha256': hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
                           'isolated': bool(sys.flags.isolated), 'optimize': sys.flags.optimize},
               'HTTP_methods_measured': methods, 'tests': tests, 'failure': failure,
               'observed_report': None if report is None else {'pages': report['pages'], 'records': len(report['records']),
                                                             'complete': report['complete']},
               'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'report_sha256': hashlib.sha256((output / 'report.json').read_bytes()).hexdigest()
                                if (output / 'report.json').exists() else None,
               'limits': ['Only the synthetic data/next_cursor schema and three-field rows.',
                          'No external API, OAuth, deployment, scheduler, load test or production result.',
                          'Retry-After HTTP-date is unsupported; no production atomic replace/fsync.']}
    write_json(output / 'RESULTADO.json', receipt)
    print(json.dumps({'output': str(output), 'receipt': str(output / 'RESULTADO.json'),
                      'status': receipt['status'], 'checks': len(tests), 'failure': failure}, ensure_ascii=True))
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New explicit output directory; existing paths are refused')
    args = parser.parse_args()
    output = args.output.resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError:
        print('Output directory could not be created; existing paths are not overwritten.', file=sys.stderr)
        return 2
    return run(output)


if __name__ == '__main__':
    raise SystemExit(main())
