import datetime as dt
import json
from django.conf import settings
from django.core.management.base import BaseCommand
from arena.models import Competition
from arena.workbook import apply_snapshot

class Command(BaseCommand):
    help='Initialize a fictional demonstration competition. No accounts, passwords or emails are seeded.'
    def handle(self,*args,**options):
        if Competition.objects.filter(slug='asr26').exists():
            self.stdout.write('Event already exists. Bootstrap does not overwrite live data.');return
        snapshot=json.loads((settings.BASE_DIR/'data/asr26-public-snapshot.json').read_text())
        for row in snapshot['rounds']+snapshot['events']:
            for k,v in row.items():
                if k.endswith('_at'): row[k]=dt.datetime.fromisoformat(v.replace('Z','+00:00'))
        c=Competition.objects.create(name='Demonstration Rescue Competition',location='Fictional demonstration venue',starts_at=dt.datetime.fromisoformat('2026-10-22T08:30:00-04:00'),
            ends_at=dt.datetime.fromisoformat('2026-10-25T17:00:00-04:00'),workbook_enabled=True)
        try:
            apply_snapshot(snapshot,'',c,allow_initial_deadlines=True)
        except Exception:
            c.delete();raise
        c.refresh_from_db()
        c.workbook_enabled=False
        c.workbook_last_synced=None
        c.workbook_digest=''
        c.save(update_fields=['workbook_enabled','workbook_last_synced','workbook_digest'])
        self.stdout.write('Demonstration competition initialized. All roster entries are fictional. No accounts, passwords or emails were created.')
