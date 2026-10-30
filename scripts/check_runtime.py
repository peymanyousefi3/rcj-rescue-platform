"""Bounded checks for an already-created, disposable rcj-ci-* Compose project."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import secrets
from http.cookies import SimpleCookie
from recovery import compose,run,ROOT


def request(port,path='/',cookie='',method='GET',body=None,headers=None):
    connection=http.client.HTTPConnection('127.0.0.1',port,timeout=30)
    try:
        connection.request(method,path,body=body,headers={**({'Cookie':cookie} if cookie else {}),**(headers or {})})
        response=connection.getresponse();data=response.read()
        return response.status,dict(response.getheaders()),data
    finally:connection.close()


def wait(port):
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        try:
            if request(port,'/health/')[0]==200:return
        except OSError:pass
        time.sleep(.2)
    raise RuntimeError('Disposable peer did not become healthy.')


def port_for(name,container_port):
    return int(run(['docker','port',name,str(container_port)],stdout=subprocess.PIPE).stdout.decode().strip().rsplit(':',1)[1])


def runtime_checks(project,env):
    if not project.startswith('rcj-ci-'):raise ValueError('Only disposable CI projects are permitted.')
    evidence={'environment':'disposable Docker project; synthetic data; no mail sender','phases':[],'resources':[]}
    def shell(code,which=project,configuration=env,container=None):
        output=(run(['docker','exec',container,'python','manage.py','shell','-c',code],stdout=subprocess.PIPE)
                if container else compose(which,configuration,'exec','-T','app','python','manage.py','shell','-c',code,stdout=subprocess.PIPE)).stdout.decode()
        return json.loads(next(line[7:] for line in output.splitlines() if line.startswith('RESULT ')))
    # The cookie is captured privately and never printed or included in the evidence.
    fixture_code="from django.contrib.auth import get_user_model; from django.core.management import call_command; from django.test import Client; from django.conf import settings; from django.core.files.uploadedfile import SimpleUploadedFile; from arena.models import Team,Membership,Competition,Score,Round; from arena.services import upload_asset; u=get_user_model().objects.create_user('runtime-owner'); u.set_unusable_password(); u.save(); c=Competition.objects.first(); t=Team.objects.regular().first(); Membership.objects.create(user=u,team=t); a=upload_asset(user=u,team=t,kind='tdp',file=SimpleUploadedFile('private-audit.txt',b'synthetic-private-audit')); client=Client(); client.force_login(u); cookie=client.cookies[settings.SESSION_COOKIE_NAME].value; Team.objects.bulk_create([Team(competition=c,code=f'PERF{i:04}',name=f'Performance Team {i:04}') for i in range(25)]); Score.objects.bulk_create([Score(team=team,round=r,raw=100,normalized=1) for team in Team.objects.regular() for r in Round.objects.filter(challenge__primary=True)]); import json; print('RESULT '+json.dumps({'cookie':cookie,'cookie_name':settings.SESSION_COOKIE_NAME,'file':str(a.pk),'team':t.pk}))"
    fixture=shell(fixture_code)
    cookie=fixture['cookie_name']+'='+fixture['cookie'];path='/files/'+fixture['file']+'/'
    peer=project+'-peer';proxy=project+'-probe';second=project+'-event2';second_app=second+'-app'
    with tempfile.TemporaryDirectory(prefix='rcj-ingress-check-') as temporary:
        config=Path(temporary)/'Caddyfile'
        second_env=Path(temporary)/'event2.env'
        values=dict(line.split('=',1) for line in Path(env).read_text().splitlines() if '=' in line)
        for key in ['POSTGRES_PASSWORD','APP_DB_PASSWORD','DJANGO_SECRET_KEY','PROXY_SHARED_SECRET']:values[key]=secrets.token_urlsafe(48)
        second_env.write_text(''.join(f'{key}={value}\n' for key,value in values.items()));second_env.chmod(0o600)
        try:
            compose(second,second_env,'up','-d','--wait','db',stdout=subprocess.DEVNULL)
            compose(second,second_env,'run','--rm','migrate',stdout=subprocess.DEVNULL)
            compose(second,second_env,'run','--rm','app','python','manage.py','bootstrap_event',stdout=subprocess.DEVNULL)
            compose(second,second_env,'run','-d','--no-deps','--name',second_app,'--publish','127.0.0.1::8000','app',stdout=subprocess.DEVNULL)
            second_port=port_for(second_app,8000);wait(second_port)
            other=shell(fixture_code,container=second_app)
            other_cookie=other['cookie_name']+'='+other['cookie'];other_path='/files/'+other['file']+'/'
            if request(second_port,other_path,other_cookie)[0]!=200:raise RuntimeError('Second event own-file access failed.')
            if request(second_port,path,cookie)[0]!=404 or request(8000,other_path,other_cookie)[0]!=404:raise RuntimeError('Cross-event private access was not denied.')
            if request(second_port,'/portal/',cookie)[0]!=302 or request(8000,'/portal/',other_cookie)[0]!=302:raise RuntimeError('Cross-event session was accepted.')
            evidence['event_isolation']='pass: two separate events, 30 teams each; independent secrets, DBs, files and sessions'
            compose(project,env,'run','-d','--no-deps','--name',peer,'--publish','127.0.0.1::8000','app',stdout=subprocess.DEVNULL)
            peer_port=port_for(peer,8000);wait(peer_port)
            for port in [8000,peer_port]:
                if request(port,path,cookie)[0]!=200 or request(port,path)[0]!=404:raise RuntimeError('Replica private-file authorization failed.')
            evidence['shared_session_and_private_storage']='pass across two independent app containers'
            # Public static compression is tested against the production WhiteNoise stack.
            status,headers,data=request(8000,'/static/arena/championship.css',headers={'Accept-Encoding':'gzip'})
            if status!=200 or headers.get('Content-Encoding')!='gzip':raise RuntimeError('Static compression unavailable.')
            evidence['static_compression']={'status':status,'encoding':headers['Content-Encoding'],'bytes':len(data)}
            config.write_text(f':8080 {{\n reverse_proxy app:8000 {peer}:8000 {{\n lb_policy round_robin\n health_uri /ready/\n health_interval 1s\n health_timeout 2s\n fail_duration 3s\n lb_try_duration 3s\n }}\n}}\n')
            run(['docker','run','-d','--name',proxy,'--label','com.docker.compose.project='+project,'--network',project+'_default','-p','127.0.0.1::8080','--mount',f'type=bind,src={config},dst=/etc/caddy/Caddyfile,readonly','caddy:2-alpine@'+json.loads((ROOT/'deploy/image-digests.json').read_text())['caddy:2-alpine']],stdout=subprocess.DEVNULL)
            proxy_port=port_for(proxy,8080);wait(proxy_port)
            for _ in range(8):
                if request(proxy_port,'/results/')[0]!=200:raise RuntimeError('Load-balanced public page failed.')
            run(['docker','stop','--time','10',peer],stdout=subprocess.DEVNULL)
            time.sleep(3)
            for _ in range(8):
                if request(proxy_port,'/results/')[0]!=200:raise RuntimeError('Unhealthy peer was not bypassed.')
            run(['docker','start',peer],stdout=subprocess.DEVNULL);wait(peer_port)
            evidence['load_balance_failover']='pass: stopped peer bypassed; remaining app served all probes'
            stop=threading.Event()
            def sample():
                while not stop.is_set():
                    raw=run(['docker','stats','--no-stream','--format','{{json .}}'],stdout=subprocess.PIPE).stdout.decode()
                    evidence['resources'].append([json.loads(line) for line in raw.splitlines() if project in line]);stop.wait(2)
            monitor=threading.Thread(target=sample,daemon=True);monitor.start()
            try:
                for name,clients,seconds in [('normal',2,5),('spike',16,5),('sustained',8,15)]:
                    deadline=time.monotonic()+seconds
                    def visitor(_):
                        measured=[]
                        while time.monotonic()<deadline:
                            started=time.perf_counter()
                            try:status=request(second_port if _%2 else proxy_port,'/results/')[0]
                            except (OSError,http.client.HTTPException):status=0
                            measured.append((time.perf_counter()-started,status))
                        return measured
                    start=time.perf_counter()
                    with ThreadPoolExecutor(max_workers=clients) as executor:samples=[item for group in executor.map(visitor,range(clients)) for item in group]
                    elapsed=time.perf_counter()-start;latency=sorted(t for t,s in samples);errors=sum(s!=200 for t,s in samples)
                    evidence['phases'].append({'phase':name,'clients':clients,'seconds':round(elapsed,2),'requests':len(samples),'errors':errors,'rps':round(len(samples)/elapsed,2),'p50_ms':round(latency[len(latency)//2]*1000,2),'p95_ms':round(latency[min(len(latency)-1,int(len(latency)*.95))]*1000,2),'p99_ms':round(latency[min(len(latency)-1,int(len(latency)*.99))]*1000,2)})
                    if errors:raise RuntimeError('Bounded isolated load test had errors.')
            finally:stop.set();monitor.join(timeout=10)
            # An interrupted multipart request must not create a submitted Asset.
            before=shell("from arena.models import Asset; import json; print('RESULT '+json.dumps(Asset.objects.count()))")
            import socket
            cookies=SimpleCookie();cookies.load(request(8000,'/portal/documents/',cookie)[1].get('Set-Cookie',''))
            csrf=cookies['csrftoken'].value;upload_cookie=cookie+'; csrftoken='+csrf
            with socket.create_connection(('127.0.0.1',8000),timeout=5) as connection:
                connection.sendall((f'POST /submit/tdp/ HTTP/1.1\r\nHost: localhost\r\nCookie: {upload_cookie}\r\nX-CSRFToken: {csrf}\r\nContent-Length: 4096\r\nContent-Type: multipart/form-data; boundary=audit\r\n\r\n--audit\r\nContent-Disposition: form-data; name="file"; filename="interrupted.txt"\r\n\r\npartial').encode())
                connection.shutdown(socket.SHUT_WR)
                aborted=connection.recv(4096).split(b'\r\n',1)[0].decode('ascii','replace')
            after=shell("from arena.models import Asset; import json; print('RESULT '+json.dumps(Asset.objects.count()))")
            if before!=after:raise RuntimeError('Interrupted upload changed stored files.')
            evidence['interrupted_upload']={'result':'connection abort saved no Asset','response':aborted}
            payload=b'--audit\r\nContent-Disposition: form-data; name="files"; filename="retry.txt"\r\nContent-Type: text/plain\r\n\r\ncomplete retry\r\n--audit--\r\n'
            status,_,_=request(8000,'/submit/tdp/',upload_cookie,method='POST',body=payload,headers={'Content-Type':'multipart/form-data; boundary=audit','X-CSRFToken':csrf})
            retried=shell("from arena.models import Asset; import json; print('RESULT '+json.dumps(Asset.objects.filter(original_name='retry.txt').count()))")
            if status!=302 or retried!=1:raise RuntimeError('A complete upload retry failed.')
            evidence['upload_retry']='pass: complete retry persisted exactly one file'
            shell(f"from arena.models import Team; Team.objects.filter(pk={fixture['team']}).update(active=False); import json; print('RESULT '+json.dumps(True))")
            for port in [8000,peer_port]:
                if request(port,path,cookie)[0]!=404:raise RuntimeError('Replica retained revoked team access.')
            evidence['revocation_across_replicas']='pass: disabled team denied immediately on both replicas'
            shell(f"from arena.models import Team; Team.objects.filter(pk={fixture['team']}).update(active=True); import json; print('RESULT '+json.dumps(True))")
        finally:
            for name in [proxy,peer]:
                try:run(['docker','rm','--force',name],stdout=subprocess.DEVNULL)
                except subprocess.CalledProcessError:pass
            compose(second,second_env,'down','--volumes','--remove-orphans',stdout=subprocess.DEVNULL)
    target=ROOT/'artifacts'/'runtime';target.mkdir(parents=True,exist_ok=True)
    (target/'runtime-checks.json').write_text(json.dumps(evidence,indent=2))
    print('Bounded runtime, shared-session/storage, failover, compression, interrupted-upload and revocation checks passed.')
