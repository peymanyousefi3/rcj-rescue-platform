"""End-to-end CI drill on randomly named disposable projects; never a live deployment."""
import http.client,json,os,secrets,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from recovery import compose,run

def main():
    token=secrets.token_hex(5);project='rcj-ci-'+token;restored='rcj-restore-ci-'+token
    with tempfile.TemporaryDirectory(prefix='rcj-deployment-') as directory:
        stage=Path(directory);env=stage/'test.env'
        values={'POSTGRES_PASSWORD':secrets.token_urlsafe(32),'APP_DB_PASSWORD':secrets.token_urlsafe(32),
            'DJANGO_SECRET_KEY':secrets.token_urlsafe(64),'PROXY_SHARED_SECRET':secrets.token_urlsafe(48),
            'DJANGO_DEBUG':'1','DJANGO_ALLOWED_HOSTS':'localhost,127.0.0.1','PUBLIC_ORIGIN':'http://127.0.0.1:8000',
            'REQUIRE_STAFF_OTP':'0','STORAGE_BACKEND':'local'}
        env.write_text(''.join(f'{key}={value}\n' for key,value in values.items()));os.chmod(env,0o600)
        destination=stage/'restored'
        try:
            compose(project,env,'build','app','worker','migrate',stdout=subprocess.DEVNULL)
            compose(project,env,'up','-d','--wait','db',stdout=subprocess.DEVNULL)
            compose(project,env,'run','--rm','migrate',stdout=subprocess.DEVNULL)
            compose(project,env,'run','--rm','app','python','manage.py','bootstrap_event',stdout=subprocess.DEVNULL)
            compose(project,env,'up','-d','--wait','app',stdout=subprocess.DEVNULL)
            code="from django.db import connection; c=connection.cursor(); c.execute('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user'); assert not any(c.fetchone()); print('Restricted runtime role verified.')"
            compose(project,env,'exec','-T','app','python','manage.py','shell','-c',code)
            check="import os; assert 'POSTGRES_PASSWORD' not in os.environ; assert 'arena_admin' not in os.environ['DATABASE_URL']; from pathlib import Path; Path('/app/var/private/recovery-marker.txt').write_text('synthetic-recovery-marker')"
            compose(project,env,'exec','-T','app','python','manage.py','shell','-c',check,stdout=subprocess.DEVNULL)
            for path,status in [('/health/',200),('/ready/',200),('/portal/',302),('/.env',404),('/.git/config',404)]:
                connection=http.client.HTTPConnection('127.0.0.1',8000,timeout=15);connection.request('GET',path)
                response=connection.getresponse();response.read();assert response.status==status,(path,response.status);connection.close()
            if os.getenv('RUN_RUNTIME')=='1':
                from check_runtime import runtime_checks
                runtime_checks(project,env)
            if os.getenv('RUN_SCANNER')=='1':
                compose(project,env,'up','-d','--wait','--wait-timeout','360','clamav',stdout=subprocess.DEVNULL)
                scan="from django.contrib.auth import get_user_model; from django.core.files.uploadedfile import SimpleUploadedFile; from django.core.management import call_command; from arena.models import Team; from arena.services import upload_asset; u=get_user_model().objects.create_user('scanner-test',is_staff=True); a=upload_asset(user=u,team=Team.objects.first(),kind='tdp',file=SimpleUploadedFile('antivirus-test.txt',b'X5O!P%@AP[4\\\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*')); call_command('scan_assets'); a.refresh_from_db(); assert a.scan_status=='rejected'; print('Real ClamAV rejected the harmless standard EICAR test file.')"
                compose(project,env,'exec','-T','app','python','manage.py','shell','-c',scan)
            if os.getenv('RUN_ZAP')=='1':
                reports=ROOT/'artifacts'/'zap';reports.mkdir(parents=True,exist_ok=True);reports.chmod(0o777)
                run(['docker','run','--rm','--network','host','--mount',f'type=bind,src={reports},dst=/zap/wrk','ghcr.io/zaproxy/zaproxy:stable@sha256:030d3df57735dacbb83464854758e674dd9ad01d79d12a129a8e58b1fd384238','zap-baseline.py','-t','http://127.0.0.1:8000','-m','1','-I','-J','report.json','-r','report.html'])
            # Migrations and append-only audit privileges are exercised as separate roles.
            audit="from arena.models import AuditEvent; from django.db import transaction,DatabaseError; a=AuditEvent.objects.create(action='test.runtime'); denied=False\ntry:\n with transaction.atomic(): AuditEvent.objects.filter(pk=a.pk).delete()\nexcept DatabaseError: denied=True\nassert denied"
            compose(project,env,'exec','-T','app','python','manage.py','shell','-c',audit,stdout=subprocess.DEVNULL)
            # Validate the real ingress configuration, including the authenticated custom header.
            run(['docker','run','--rm','-e','PUBLIC_HOST=rescue.example.test','-e','PROXY_SHARED_SECRET='+values['PROXY_SHARED_SECRET'],'--mount',f'type=bind,src={ROOT}/deploy/Caddyfile,dst=/etc/caddy/Caddyfile,readonly','caddy:2-alpine@'+json.loads((ROOT/'deploy/image-digests.json').read_text())['caddy:2-alpine'],'caddy','validate','--config','/etc/caddy/Caddyfile'],stdout=subprocess.DEVNULL)
            identity=stage/'identity.agekey'
            run(['age-keygen','-o',str(identity)],stdout=subprocess.DEVNULL)
            recipient=run(['age-keygen','-y',str(identity)],stdout=subprocess.PIPE).stdout.decode().strip()
            archive=stage/'backup.age'
            run([sys.executable,str(ROOT/'scripts/recovery.py'),'backup','--project',project,'--env',str(env),'--output',str(archive),'--recipient',recipient,'--confirm-maintenance'])
            run([sys.executable,str(ROOT/'scripts/recovery.py'),'restore','--project',restored,'--backup',str(archive),'--identity',str(identity),'--destination',str(destination)])
            proof="from pathlib import Path; from arena.models import Competition; assert Competition.objects.count()==1; assert Path('/app/var/private/recovery-marker.txt').read_text()=='synthetic-recovery-marker'; print('Encrypted database + private-file restore verified.')"
            compose(restored,destination/'.env','run','--rm','--no-deps','app','python','manage.py','shell','-c',proof)
            try:
                run([sys.executable,str(ROOT/'scripts/recovery.py'),'restore','--project',restored,'--backup',str(archive),'--identity',str(identity),'--destination',str(stage/'must-not-exist')],stdout=subprocess.DEVNULL)
            except subprocess.CalledProcessError:pass
            else:raise AssertionError('Restore must reject an existing project.')
            print('Isolated deployment, runtime privileges, private-path denial, encryption and non-destructive restore passed.')
        except subprocess.CalledProcessError as exc:
            message=(exc.stderr or b'').decode('utf-8','replace')[-6000:]
            for value in values.values():
                if len(value)>=16:message=message.replace(value,'[REDACTED]')
            print(message,file=sys.stderr)
            raise RuntimeError('Isolated deployment drill failed; subprocess arguments withheld.') from None
        finally:
            for name,config in [(project,env),(restored,destination/'.env' if (destination/'.env').exists() else env)]:
                if not name.startswith(('rcj-ci-','rcj-restore-ci-')):raise RuntimeError('Refusing unsafe cleanup.')
                compose(name,config,'down','--volumes','--remove-orphans',stdout=subprocess.DEVNULL)

if __name__=='__main__':main()
