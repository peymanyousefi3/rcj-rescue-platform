import os
import threading
import signal, json, time, socket
from django.conf import settings
from django.db import close_old_connections
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone
from arena.models import RequestQuota

class Command(BaseCommand):
    help='Small-event worker: durable mail, file scans, and spreadsheet sync every 30 seconds.'
    def handle(self,*args,**options):
        stop=threading.Event()
        signal.signal(signal.SIGTERM,lambda *_:stop.set())
        signal.signal(signal.SIGINT,lambda *_:stop.set())
        while not stop.is_set():
            close_old_connections()
            ok=True
            RequestQuota.objects.filter(expires_at__lt=timezone.now()).delete()
            tasks=['scan_assets']
            from arena.mail import email_ready
            if email_ready(): tasks.append('deliver_mail')
            if os.getenv('SOURCE_WORKBOOK_ID'): tasks.append('sync_workbook')
            for command in tasks:
                try: call_command(command,stdout=self.stdout,stderr=self.stderr)
                except Exception as exc:
                    ok=False
                    # No credentials, private payloads or SMTP exception bodies in process logs.
                    self.stderr.write(f'{command}: {type(exc).__name__}; retrying next cycle.')
            try:
                with socket.create_connection((os.getenv('CLAMAV_HOST','127.0.0.1'),int(os.getenv('CLAMAV_PORT','3310'))),timeout=5) as scanner:
                    scanner.sendall(b'zPING\0');ok=ok and scanner.recv(64).rstrip(b'\0')==b'PONG'
            except OSError: ok=False
            settings.PRIVATE_ROOT.mkdir(parents=True,exist_ok=True)
            temporary=settings.PRIVATE_ROOT/'.worker-health.tmp'
            temporary.write_text(json.dumps({'updated':time.time(),'ok':bool(ok)}))
            temporary.replace(settings.PRIVATE_ROOT/'.worker-health.json')
            stop.wait(30)
