"""Container probes; do not return dependency details or credentials to visitors."""
import http.client
import json
import os
from pathlib import Path
import sys
import time

if sys.argv[1] == 'worker':
    try:
        state = json.loads(Path('/app/var/private/.worker-health.json').read_text())
        assert time.time() - state['updated'] < 150 and state['ok']
    except (OSError,ValueError,KeyError,AssertionError):
        raise SystemExit(1)
else:
    connection = http.client.HTTPConnection('127.0.0.1',8000,timeout=5)
    host = os.getenv('DJANGO_ALLOWED_HOSTS','localhost').split(',')[0]
    connection.request('GET','/health/',headers={'Host':host,'X-Forwarded-Proto':'https'})
    response=connection.getresponse();response.read();connection.close()
    raise SystemExit(0 if response.status==200 else 1)
