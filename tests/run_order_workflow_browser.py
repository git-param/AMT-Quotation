"""Run the real order workflow in headless Edge on Windows.

Usage: .venv/Scripts/python.exe tests/run_order_workflow_browser.py
Requires Node 22+ and Microsoft Edge. Uses a fresh isolated fixture database
and synthetic company details. Screenshots are written under .verification/.
"""
from pathlib import Path
import json
import os
import subprocess
import threading
import time
import sys
from uuid import uuid4

sys.path.insert(0, str(Path.cwd()))
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server, WSGIRequestHandler
from backend import database
import backend.app as application

scratch = Path('.verification').resolve()
scratch.mkdir(exist_ok=True)
run_id=uuid4().hex[:10]
profile=scratch / ('edge-profile-'+run_id)
# Synthetic issuer settings keep this test independent of production data.
company_profile=json.dumps({
    'seller':['Fixture Seller','Fixture Street','GST: TEST'],
    'bank':['Fixture bank','Company account fixture'],
    'bank_charges':'Sender pays',
    'payment_terms':{'USD':'100% Advance','INR':'100% Advance'},
    'tax_rates':{'USD':'0','INR':'0.18'},
    'terms':{'USD':['1. Valid 7 days'],'INR':['1. Valid 7 days']},
})

database.DB_PATH = str(scratch / ('browser-fixture-'+run_id+'.db'))
database.DATABASE_DIR = scratch
application.SECRET_KEY_PATH = scratch / 'fixture-secret.key'
app = application.create_app()
connection = database.get_db()
with connection:
    connection.execute('INSERT INTO company_pi_settings(id,profile_json) VALUES(1,?)',(company_profile,))
    connection.execute('INSERT OR IGNORE INTO users(username,password_hash,role) VALUES(?,?,?)',
                       ('browser-fixture', generate_password_hash('local-fixture-only'), 'sales_executive'))
connection.close()

class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass

server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=QuietHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
edge = subprocess.Popen([
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=0', '--user-data-dir=' + str(profile), 'about:blank',
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
try:
    active = profile / 'DevToolsActivePort'
    for _ in range(100):
        try:
            port = active.read_text().splitlines()[0]
            break
        except (OSError,IndexError):
            time.sleep(.1)
    else:raise RuntimeError('Browser debugging port unavailable')
    for _ in range(50):
        try:
            import urllib.request
            targets_json=urllib.request.urlopen('http://127.0.0.1:'+port+'/json/list',timeout=1).read().decode()
            break
        except OSError:
            time.sleep(.1)
    result = subprocess.run(['node', 'tests/order_workflow_browser.cjs',
                             f'http://127.0.0.1:{server.server_port}', port], timeout=160, env={**os.environ, 'CDP_TARGETS':targets_json})
    sys.exit(result.returncode)
finally:
    server.shutdown()
    edge.terminate()
    edge.wait(timeout=10)
