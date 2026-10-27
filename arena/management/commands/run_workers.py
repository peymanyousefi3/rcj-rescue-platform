import os
import threading
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone
from arena.models import RequestQuota

class Command(BaseCommand):
    help='Small-event worker: durable mail, file scans, and spreadsheet sync every 30 seconds.'
    def handle(self,*args,**options):
        stop=threading.Event()
        while not stop.is_set():
            RequestQuota.objects.filter(expires_at__lt=timezone.now()).delete()
            tasks=['scan_assets','deliver_mail']
            if os.getenv('SOURCE_WORKBOOK_ID'): tasks.append('sync_workbook')
            for command in tasks:
                try: call_command(command,stdout=self.stdout,stderr=self.stderr)
                except Exception as exc:
                    # No credentials, private payloads or SMTP exception bodies in process logs.
                    self.stderr.write(f'{command}: {type(exc).__name__}; retrying next cycle.')
            stop.wait(30)
