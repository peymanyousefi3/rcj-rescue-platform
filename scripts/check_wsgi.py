"""Exercise the Docker startup command against the disposable CI database."""
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time


def main():
    root = Path(__file__).resolve().parent.parent
    command = next(line[4:] for line in (root / 'Dockerfile').read_text().splitlines()
                   if line.startswith('CMD '))
    args = json.loads(command)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    args[args.index('--bind') + 1] = f'127.0.0.1:{port}'
    env = dict(os.environ, DJANGO_DEBUG='0', PUBLIC_ORIGIN='https://rescue.example.test',
               DJANGO_ALLOWED_HOSTS='rescue.example.test', TRUST_PROXY_HTTPS='1')
    with tempfile.TemporaryFile(mode='w+') as log:
        server = subprocess.Popen([sys.executable, '-m', *args], cwd=root, env=env,
                                  stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                    connection.request('GET', '/health/', headers={
                        'Host': 'rescue.example.test', 'X-Forwarded-Proto': 'https'})
                    response = connection.getresponse()
                    response.read()
                    connection.close()
                    if response.status == 200:
                        break
                except OSError:
                    pass
                if server.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('Production WSGI server did not become healthy.')
                time.sleep(0.1)
            for method, path, status in [('GET', '/', 200), ('GET', '/account/login/', 200),
                                         ('GET', '/portal/', 302), ('GET', '/control/', 302),
                                         ('POST', '/accounts/logout/', 403)]:
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=15)
                connection.request(method, path, headers={
                    'Host': 'rescue.example.test', 'X-Forwarded-Proto': 'https'})
                response = connection.getresponse()
                body = response.read()
                assert response.status == status, (path, response.status, body[:200])
                assert response.getheader('X-Content-Type-Options') == 'nosniff', path
                if status == 302:
                    assert '/account/login/' in response.getheader('Location', ''), path
                connection.close()
            print('Production WSGI startup, public/login pages, private redirects and CSRF passed.')
        except Exception:
            log.seek(0)
            print(log.read(), file=sys.stderr)
            raise
        finally:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
            if server.returncode not in (0, -15):
                raise RuntimeError(f'WSGI server exited unsuccessfully: {server.returncode}')


if __name__ == '__main__':
    main()
