import io,json,zipfile
from datetime import timedelta
from unittest.mock import patch
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from django.test import Client
from django.utils import timezone
from arena.models import RunRecording,Score
from arena.recordings import result_revision

pytestmark=pytest.mark.django_db


def export_zip(**changes):
    files={'run/replay.html':b'''<!doctype html><html><head><script type="module" src="https://cyberbotics.com/wwi/R2023b/WebotsView.js"></script><link rel="stylesheet" href="replay.css"></head><body><webots-view data-scene="replay.x3d" data-animation="replay.json" data-thumbnail="replay.jpg"></webots-view></body></html>''',
        'run/replay.css':b'webots-view {height:100%}',
        'run/replay.x3d':b'''<X3D><head><meta name="version" content="R2023b"/></head><Scene><Transform id="n1"/><ImageTexture url='"textures/floor.jpg"'/></Scene></X3D>''',
        'run/replay.json':json.dumps({'basicTimeStep':32,'frames':[{'time':0,'updates':[{'id':1,'translation':'0 0 0'}]},{'time':32,'updates':[{'id':1,'translation':'1 0 0'}]}]}).encode(),
        'run/replay.jpg':b'\xff\xd8\xff\xe0JPEG','run/textures/floor.jpg':b'\xff\xd8\xff\xe0texture'}
    for key,value in changes.items():
        if value is None: files.pop(key,None)
        else: files[key]=value
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in files.items(): archive.writestr(name,data)
    return SimpleUploadedFile('export.zip',stream.getvalue(),content_type='application/zip')


def post_result(client,event,upload=None,**changes):
    c,r,teams,users,staff=event
    return client.post(f'/control/results/{r.pk}/{teams[0].pk}/',{'revision':result_revision(r,teams[0]),'raw':'0','normalized':'75','normalized_override':'on',
        **({'files':[upload]} if upload else {}),**changes})


def test_results_upload_preserves_export_and_is_private_until_explicit_release(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    assert post_result(client,event,export_zip()).status_code==302
    recording=RunRecording.objects.get();score=Score.objects.get()
    assert score.raw==0 and score.normalized==75 and not recording.published and recording.frame_count==2
    assert 'run/textures/floor.jpg' in recording.manifest
    assert default_storage.exists(f'recordings/{recording.pk}/run/textures/floor.jpg')
    player_url=f'/recordings/{recording.pk}/player/'
    assert client.get(player_url).status_code==200
    private_cap=client.get(player_url).json()['url']
    html=client.get(private_cap)
    assert html.status_code==200 and 'X-Frame-Options' not in html
    assert "sandbox allow-scripts allow-pointer-lock;" in html['Content-Security-Policy']
    assert 'allow-same-origin' not in html['Content-Security-Policy'] and html['Access-Control-Allow-Origin']=='null'
    assert b'replay-bridge.js' in html.content
    client.force_login(users[0]);assert client.get(player_url).status_code==200
    assert client.get(f'/recordings/{recording.pk}/preview/').status_code==200
    client.force_login(users[1]);assert client.get(player_url).status_code==404
    assert client.get(f'/recordings/{recording.pk}/preview/').status_code==404
    client.logout();assert client.get(player_url).status_code==404 and b'recording-card' not in client.get('/results/').content
    client.force_login(staff);assert post_result(client,event,published='on').status_code==200
    recording.refresh_from_db();assert not recording.published
    r.starts_at=timezone.now()-timedelta(hours=2);r.ends_at=timezone.now()-timedelta(hours=1);r.completed=True;r.save()
    assert post_result(client,event,published='on').status_code==302
    client.logout();assert client.get(player_url).status_code==200
    public_cap=client.get(player_url).json()['url'];assert client.get(public_cap).status_code==200
    for path in ['/results/','/playbacks/']:
        page=client.get(path).content
        assert (b'recording-card' in page)==(path=='/playbacks/')
        assert b'<iframe' not in page and b'WebotsView.js' not in page
        if path=='/results/': assert b'Run recordings</h2>' not in page and b'result-score-play' in page
        assert f'data-replay="{player_url}"'.encode() in page and b'data-replay-dialog' in page
        assert b'data-replay-close' in page and b'Open recording in a new tab' not in page
    client.force_login(staff);assert post_result(client,event).status_code==302
    client.logout();assert client.get(public_cap).status_code==404


@pytest.mark.parametrize('changes',[
    {'../escape.txt':b'bad'},
    {'run/replay.json':b'{broken'},
    {'run/replay.json':b'{"frames":[]}'},
    {'run/replay.json':b'{"frames":[{"time":0,"updates":[{"id":99}]},{"time":1,"updates":[{"id":99}]}]}'},
    {'run/textures/floor.jpg':None},
    {'run/replay.jpg':b'<script>bad</script>'},
    {'run/replay.x3d':b'<X3D><head><meta name="version" content="R2025a"/></head><Scene id="n1"/></X3D>'},
])
def test_invalid_export_cannot_replace_previous_results_or_files(client,event,changes):
    client.force_login(event[-1]);assert post_result(client,event,export_zip()).status_code==302
    original=RunRecording.objects.get();original_score=list(Score.objects.values())
    response=post_result(client,event,export_zip(**changes),raw=99)
    assert response.status_code==200 and b'errorlist' in response.content
    assert RunRecording.objects.get().pk==original.pk and list(Score.objects.values())==original_score


def test_replacement_withdrawal_stale_edits_permissions_and_csrf(client,event):
    c,r,teams,users,staff=event
    assert post_result(client,event,export_zip()).status_code in [302,403]
    client.force_login(users[0]);assert post_result(client,event,export_zip()).status_code==302
    assert not RunRecording.objects.exists()
    client.force_login(staff);stale=result_revision(r,teams[0]);assert post_result(client,event,export_zip()).status_code==302
    first=RunRecording.objects.get();cap=client.get(f'/recordings/{first.pk}/player/').json()['url']
    assert post_result(client,event,raw=999,revision=stale).status_code==200
    assert Score.objects.get().raw==0
    assert post_result(client,event,export_zip()).status_code==302
    first.refresh_from_db();assert not first.current and RunRecording.objects.count()==2
    assert client.get(cap).status_code==404 and default_storage.exists(f'recordings/{first.pk}/{first.entry_path}')
    secured=Client(enforce_csrf_checks=True);secured.force_login(staff)
    assert post_result(secured,event).status_code==403
    current=RunRecording.objects.get(current=True)
    assert client.post(f'/control/recordings/{current.pk}/remove/').status_code==302
    current.refresh_from_db();assert not current.current
    assert default_storage.exists(f'recordings/{current.pk}/{current.entry_path}')
    assert client.get(f'/recordings/{first.pk}/player/').status_code==200
    assert client.post(f'/control/recordings/{first.pk}/restore/').status_code==302
    first.refresh_from_db();assert first.current and not first.published


def test_replay_capabilities_expire_and_do_not_allow_traversal(client,event):
    client.force_login(event[-1]);assert post_result(client,event,export_zip()).status_code==302
    item=RunRecording.objects.get();url=client.get(f'/recordings/{item.pk}/player/').json()['url']
    assert client.get(url.replace('/run/replay.html','/run/not-in-export.js')).status_code==404
    with patch('django.core.signing.time.time',return_value=__import__('time').time()+601): assert client.get(url).status_code==404


def test_folder_upload_detects_html_thumbnail_among_nested_texture_images(client,event):
    client.force_login(event[-1])
    with zipfile.ZipFile(export_zip()) as archive:
        files={name:archive.read(name) for name in archive.namelist()}
    html=files.pop('run/replay.html').replace(b'data-thumbnail="replay.jpg"',b'data-thumbnail=../previews/actual%20preview.jpg')
    files['run/pages/replay.html']=html.replace(b'href="replay.css"',b'href="../replay.css"').replace(b'data-scene="replay.x3d"',b'data-scene="../replay.x3d"').replace(b'data-animation="replay.json"',b'data-animation="../replay.json"')
    files['run/previews/actual preview.jpg']=files.pop('run/replay.jpg')
    files['run/textures/another.jpg']=b'\xff\xd8\xff\xe0texture'
    files['run/readme.html']=b'<html><body>Export notes</body></html>'
    data={'revision':result_revision(event[1],event[2][0]),'paths':json.dumps(list(files)),
        'files':[SimpleUploadedFile(name.rsplit('/',1)[-1],body) for name,body in files.items()]}
    response=client.post(f'/control/results/{event[1].pk}/{event[2][0].pk}/',data)
    assert response.status_code==302,response.content
    recording=RunRecording.objects.get()
    assert recording.entry_path=='run/pages/replay.html'
    assert recording.preview_path=='run/previews/actual preview.jpg'
    assert default_storage.open(f'recordings/{recording.pk}/{recording.preview_path}').read()==files[recording.preview_path]


def test_private_replay_checks_every_asset_and_binds_links_to_active_session(client,event,settings):
    from django.core import signing
    c,r,teams,users,staff=event
    client.force_login(staff);assert post_result(client,event,export_zip()).status_code==302
    recording=RunRecording.objects.get();endpoint=f'/recordings/{recording.pk}/player/'
    staff_url=client.get(endpoint).json()['url'].split('#')[0]
    staff_assets=[staff_url.replace(recording.entry_path,path) for path in recording.manifest]
    for url in staff_assets:
        assert client.get(url).status_code==200
        assert Client().get(url).status_code==404
    # The old bearer links must stop working immediately, even for a logged-in admin.
    legacy=signing.dumps({'id':str(recording.pk),'public':False,'history':False},salt='webots-replay')
    assert client.get(f'/replay-view/{legacy}/{recording.entry_path}').status_code==404
    client.force_login(users[1])
    for url in staff_assets: assert client.get(url).status_code==404
    client.force_login(users[0])
    assert client.get(staff_url).status_code==404
    owner_response=client.get(endpoint);owner_url=owner_response.json()['url'].split('#')[0]
    cookie=owner_response.cookies['asr_replay_session']
    assert cookie['httponly'] and cookie['secure'] and cookie['samesite']=='None' and cookie['path']=='/replay-view/'
    assert not cookie['max-age'] and not cookie['expires'] # The replay must not outlive a browser-only sign-in.
    for path in recording.manifest: assert client.get(owner_url.replace(recording.entry_path,path)).status_code==200
    # Opaque-frame fetches use a path-scoped cookie, with the same live Django session.
    auxiliary=Client();auxiliary.cookies['asr_replay_session']=cookie.value
    assert auxiliary.get(owner_url,HTTP_ORIGIN='null').status_code==200
    assert auxiliary.get('/portal/').status_code==302
    assert auxiliary.get(endpoint).status_code==404
    client.logout()
    assert auxiliary.get(owner_url,HTTP_ORIGIN='null').status_code==404


def test_private_recordings_are_discoverable_only_to_owner_and_admin(client,event):
    c,r,teams,users,staff=event
    client.force_login(staff);assert post_result(client,event,export_zip()).status_code==302
    recording=RunRecording.objects.get();play=f'data-replay="/recordings/{recording.pk}/player/"'.encode()
    assert play in client.get('/control/').content
    client.force_login(users[0])
    for url in ['/portal/','/portal/results/','/results/','/playbacks/']:
        page=client.get(url);assert page.status_code==200 and play in page.content
        assert b'<iframe' not in page.content
        if url!='/results/': assert b'Private' in page.content
        else: assert b'recording-card' not in page.content and b'result-score-play' in page.content
    client.force_login(users[1])
    for url in ['/portal/','/portal/results/','/results/','/playbacks/']: assert play not in client.get(url).content
    client.logout()
    assert play not in client.get('/results/').content


def test_replay_cookie_does_not_bypass_admin_authenticator_checks(client,event):
    from django_otp.plugins.otp_totp.models import TOTPDevice
    client.force_login(event[-1]);assert post_result(client,event,export_zip()).status_code==302
    recording=RunRecording.objects.get()
    response=client.get(f'/recordings/{recording.pk}/player/');url=response.json()['url']
    auxiliary=Client();auxiliary.cookies['asr_replay_session']=response.cookies['asr_replay_session'].value
    device=TOTPDevice.objects.create(user=event[-1],name='default',confirmed=True)
    blocked=auxiliary.get(url)
    assert blocked.status_code==302 and blocked.url.startswith('/account/login/')
    session=client.session;session['otp_device_id']=device.persistent_id;session.save()
    assert auxiliary.get(url).status_code==200


def test_schedule_run_play_buttons_follow_owner_access_and_refresh_publication(client,event):
    from arena.models import Programme
    import re
    c,r,teams,users,staff=event
    Programme.objects.create(competition=c,source_key='run',round=r,team=teams[0],title='Run',
        starts_at=r.starts_at,ends_at=r.ends_at)
    client.force_login(staff)
    assert post_result(client,event,export_zip()).status_code==302
    recording=RunRecording.objects.get()
    button=f'class="programme-play" data-replay="/recordings/{recording.pk}/player/"'.encode()
    paths=['/','/schedule/','/schedule/fragment/']
    for user,visible in [(staff,True),(users[0],True),(users[1],False),(None,False)]:
        if user: client.force_login(user)
        else: client.logout()
        for path in paths:
            response=client.get(path)
            assert response.status_code==200 and (button in response.content)==visible
            if path!='/schedule/fragment/':
                assert b'replay.js' in response.content and b'data-replay-dialog' in response.content
                assert b'recordings-section' not in response.content
                assert b'<iframe' not in response.content
            else: assert 'private' in response['Cache-Control']
    def fragment_version():
        return re.search(rb'data-version="([^"]+)"',client.get('/schedule/fragment/').content).group(1)
    r.starts_at=timezone.now()-timedelta(hours=2);r.ends_at=timezone.now()-timedelta(hours=1)
    r.completed=True;r.save()
    before_publication=fragment_version()
    recording.published=True;recording.save()
    assert button in client.get('/schedule/fragment/').content
    published_version=fragment_version()
    assert published_version!=before_publication
    recording.published=False;recording.save()
    assert fragment_version()==before_publication and button not in client.get('/').content


def test_public_replay_allows_assets_on_the_validated_serving_alias(client,event,settings):
    c,r,teams,users,staff=event
    client.force_login(staff)
    assert post_result(client,event,export_zip()).status_code==302
    r.starts_at=timezone.now()-timedelta(hours=2);r.ends_at=timezone.now()-timedelta(hours=1)
    r.completed=True;r.save()
    recording=RunRecording.objects.get();recording.published=True;recording.save()
    client.logout()
    settings.PUBLIC_ORIGIN='https://rcjrescue.com'
    settings.ALLOWED_HOSTS=['rcjrescue.com','www.rcjrescue.com']
    host={'HTTP_HOST':'www.rcjrescue.com','secure':True}
    player=client.get(f'/recordings/{recording.pk}/player/',**host)
    assert player.status_code==200
    response=client.get(player.json()['url'],**host)
    assert response.status_code==200
    policy=response['Content-Security-Policy']
    for directive in ('script-src','style-src','connect-src','img-src'):
        assert f'{directive} https://rcjrescue.com https://www.rcjrescue.com ' in policy
    assert 'allow-same-origin' not in policy and response['Access-Control-Allow-Origin']=='null'
    assert client.get(player.json()['url'].split('#')[0].replace('replay.html','replay.x3d'),**host).status_code==200
    assert client.get(player.json()['url'],HTTP_HOST='untrusted.example',secure=True).status_code==400


def test_result_cells_pair_the_score_with_only_its_accessible_replay(client,event):
    import re
    from arena.models import Challenge
    c,r,teams,users,staff=event
    client.force_login(staff)
    assert post_result(client,event,export_zip(),raw='75').status_code==302
    recording=RunRecording.objects.get()
    endpoint=f'/recordings/{recording.pk}/player/'
    def cells():
        html=client.get('/results/').content.decode()
        return [cell for cell in re.findall(r'<td\b[^>]*>(.*?)</td>',html,re.S) if 'result-score-play' in cell]
    assert len(cells())==1 # Uncategorized competition fallback table.
    challenge=Challenge.objects.create(competition=c,name='Field competition',primary=True)
    r.challenge=challenge;r.save()
    for user,visible in [(staff,True),(users[0],True),(users[1],False),(None,False)]:
        if user: client.force_login(user)
        else: client.logout()
        paired=cells()
        assert len(paired)==(2 if visible else 0) # Desktop and mobile tables.
        for cell in paired:
            assert '75.00' in cell and endpoint in cell and f'Play {teams[0].name} in {r}' in cell
    r.starts_at=timezone.now()-timedelta(hours=2);r.ends_at=timezone.now()-timedelta(hours=1)
    r.completed=True;r.save()
    recording.published=True;recording.save()
    assert len(cells())==2
    recording.current=False;recording.save()
    assert cells()==[]
