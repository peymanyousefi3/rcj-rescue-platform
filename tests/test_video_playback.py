from datetime import timedelta
from decimal import Decimal
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.files.storage import default_storage
from django.utils import timezone
from arena.models import Asset, Challenge, RunRecording
from arena.recordings import result_revision
from arena.views import standings
from test_results_recordings import post_result, export_zip

pytestmark=pytest.mark.django_db


def video():
    return SimpleUploadedFile('game.mp4',b'\x00\x00\x00\x18ftypmp42'+bytes(range(128)),content_type='video/mp4')


def test_video_priority_fallback_privacy_ranges_and_revocation(client,event):
    c,r,teams,users,staff=event
    client.force_login(staff)
    assert post_result(client,event,export_zip(),video=video()).status_code==302
    recording=RunRecording.objects.get()
    player=f'/recordings/{recording.pk}/player/'
    data=client.get(player).json();assert data['kind']=='video'
    url=data['url'];assert b'ftyp' in b''.join(client.get(url).streaming_content)
    response=client.get(url,HTTP_RANGE='bytes=4-11')
    assert response.status_code==206 and response['Content-Range']=='bytes 4-11/140'
    assert b''.join(response.streaming_content)==b'ftypmp42'
    response=client.get(url,HTTP_RANGE='bytes=-8');assert len(b''.join(response.streaming_content))==8
    assert client.head(url)['Content-Length']=='140'
    for value in ['bytes=999-','bytes=-0','bytes=5-2','bytes=0-1,3-4','invalid']:
        assert client.get(url,HTTP_RANGE=value).status_code==416
    client.force_login(users[0]);assert client.get(player).status_code==200
    assert client.get(url,HTTP_RANGE='bytes=0-10').status_code==206
    client.force_login(users[1]);assert client.get(url).status_code==404 and client.get(player).status_code==404
    client.logout();assert client.get(url).status_code==404
    client.force_login(staff)
    r.starts_at=timezone.now()-timedelta(hours=2);r.ends_at=timezone.now()-timedelta(hours=1);r.completed=True;r.save()
    assert post_result(client,event,published='on').status_code==302
    client.logout();assert client.get(url,HTTP_RANGE='bytes=20-25').status_code==206
    assert f'data-replay="{player}"'.encode() in client.get('/results/').content
    client.force_login(staff)
    key=recording.video_key
    assert post_result(client,event,remove_video='on').status_code==302
    assert 'kind' not in client.get(player).json() and client.get(url).status_code==404
    assert default_storage.exists(key)
    assert post_result(client,event,video=video()).status_code==302
    assert client.post(f'/control/recordings/{recording.pk}/remove/').status_code==302
    client.force_login(users[0]);assert client.get(url).status_code==404


def test_video_only_upload_preserves_on_webots_replacement_and_validates(client,event):
    client.force_login(event[-1]);assert post_result(client,event,video=video()).status_code==302
    first=RunRecording.objects.get();assert not first.entry_path and first.video_key
    assert post_result(client,event,remove_video='on').status_code==200
    assert post_result(client,event,export_zip()).status_code==302
    current=RunRecording.objects.get(current=True)
    assert current.video_key==first.video_key and current.entry_path
    stale=result_revision(event[1],event[2][0])
    assert post_result(client,event,video=video()).status_code==302
    assert post_result(client,event,revision=stale,remove_video='on').status_code==200
    current.refresh_from_db();key=current.video_key
    bad=SimpleUploadedFile('fake.mp4',b'<html>not video</html>')
    response=post_result(client,event,video=bad)
    assert response.status_code==200 and b'matching file contents' in response.content
    current.refresh_from_db();assert current.video_key==key


def test_map_maximum_in_admin_team_home_and_public_results(client,event):
    c,r,teams,users,staff=event
    r.challenge=Challenge.objects.create(competition=c,name='Field',primary=True);r.save()
    Asset.objects.create(competition=c,round=r,kind='map',map_role='info_json',field_info={'competitionCard':{'perfectMapPlusExitScore':508.2}},
        uploader=staff,original_name='info.json',blob_key='private/info.json',size=10,sha256='a'*64,scan_status='clean')
    rounds,_=standings(c);assert rounds[0].maximum_score==Decimal('508.2')
    for path in ['/','/results/']:
        page=client.get(path).content;assert b'Map max: 508.2' in page
        assert b'private/info.json' not in page
    client.force_login(users[0]);assert b'Map max: 508.2' in client.get('/portal/results/').content
    client.force_login(staff);assert b'Map max: 508.2' in client.get('/control/').content
    asset=Asset.objects.get();asset.field_info={'maximum_score':0};asset.save()
    assert b'Map max: 0' in client.get('/results/').content
    asset.scan_status='rejected';asset.save()
    assert b'Map max: 0' not in client.get('/results/').content
