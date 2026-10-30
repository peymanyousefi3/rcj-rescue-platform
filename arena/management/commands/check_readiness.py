"""Read-only deployment checks. A successful run does not certify external controls."""
import json,shutil,time
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.db import connection
from django.db.models import Q
from django.utils import timezone
from arena.models import EmailDelivery,Asset

class Command(BaseCommand):
    help='Read-only local deployment checks; prints no credentials, user records or file contents.'
    def add_arguments(self,parser):parser.add_argument('--json',action='store_true',dest='json_output')
    def handle(self,*args,**options):
        checks=[]
        def add(name,ok,detail):checks.append({'control':name,'status':'pass' if ok else 'needs_attention','detail':detail})
        add('Production debug',not settings.DEBUG,'Use DJANGO_DEBUG=0 for a real deployment.')
        add('Admin MFA',settings.REQUIRE_STAFF_OTP,'Production staff enrollment should be required.')
        add('Upload budgets',all(getattr(settings,name)>0 for name in ['UPLOAD_MAX_FILE_BYTES','UPLOAD_MAX_BATCH_BYTES','UPLOAD_MAX_FILES','UPLOAD_TEAM_MAX_BYTES','VALIDATION_MAX_BYTES']),'Positive, bounded limits are configured.')
        add('Private disk reserve',shutil.disk_usage(settings.PRIVATE_ROOT).free>=settings.UPLOAD_MIN_FREE_BYTES,'Check host capacity alerts separately.')
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            if connection.vendor=='postgresql':
                cursor.execute('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user')
                add('Database privileges',not any(cursor.fetchone()),'Run with arena_app, never the bootstrap or migration account.')
            else:add('Database privileges',False,'Production requires PostgreSQL with a restricted runtime role.')
        if settings.TRUST_PROXY_CLIENT_IP:add('Authenticated ingress',len(settings.PROXY_SHARED_SECRET)>=32,'Validate spoofed headers through the actual proxy too.')
        try:
            heartbeat=json.loads((settings.PRIVATE_ROOT/'.worker-health.json').read_text())
            healthy=time.time()-heartbeat['updated']<150 and heartbeat['ok']
        except (OSError,ValueError,KeyError):healthy=False
        add('Worker/scanner heartbeat',healthy,'Check worker logs and ClamAV health if stale or unhealthy.')
        pending=EmailDelivery.objects.filter(sent_at=None,attempts__lt=12).filter(Q(expires_at=None)|Q(expires_at__gt=timezone.now())).count()
        add('Mail backlog',pending<settings.MAIL_MAX_PENDING,'Use operator monitoring for delivery age and retries.')
        add('Pending malware scans',not Asset.objects.filter(scan_status='pending',created_at__lt=timezone.now()-timedelta(minutes=10)).exists(),'Uploads stay private while scanning is unavailable.')
        manual=['Off-host encrypted backup and restore drill','DDoS/WAF/firewall and origin controls','DNS/TLS/SMTP authentication','Real Drive/S3 ACLs and key rotation','RTO/RPO, incident contacts and privacy/retention policy','Representative capacity and browser/accessibility checks']
        result={'checks':checks,'external_evidence_required':manual}
        self.stdout.write(json.dumps(result,indent=2) if options['json_output'] else '\n'.join(f"{row['status']}: {row['control']} - {row['detail']}" for row in checks)+'\nExternal controls still require operator evidence.')
        if any(row['status']!='pass' for row in checks):raise CommandError('Some local checks need attention; no settings or data were changed.')
