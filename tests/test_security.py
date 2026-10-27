import datetime as dt
import hashlib
from unittest.mock import patch
import pytest
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone
from arena.access import can_download
from arena.models import Asset,AuditEvent,EmailDelivery,Notification
from arena.services import announce,delete_submission,upload_asset

pytestmark=pytest.mark.django_db

def upload(event,kind='round_code',payload=b'print("test")'):
    c,r,teams,users,staff=event
    return upload_asset(user=users[0],file=SimpleUploadedFile('controller.py',payload),
        kind=kind,team=teams[0],round_=r if kind.startswith('round_') else None,attested=True)

def test_cross_team_download_is_hidden(client,event):
    asset=upload(event)
    client.force_login(event[3][1])
    assert client.get(f'/files/{asset.pk}/').status_code==404
    client.force_login(event[3][0])
    response=client.get(f'/files/{asset.pk}/')
    assert response.status_code==200
    assert {'private','no-store'} <= {v.strip() for v in response['Cache-Control'].split(',')}
    assert 'attachment' in response['Content-Disposition']
    assert response['Content-Type']=='application/octet-stream'
    assert response['X-File-SHA256']==hashlib.sha256(b'print("test")').hexdigest()

def test_anonymous_cannot_download_private_file(client,event):
    asset=upload(event)
    assert client.get(f'/files/{asset.pk}/').status_code==404

def test_team_cannot_upload_to_other_team(event):
    with pytest.raises(PermissionDenied):
        upload_asset(user=event[3][1],file=SimpleUploadedFile('a.bin',b'abc'),kind='round_code',team=event[2][0],round_=event[1],attested=True)

def test_hash_is_server_calculated_and_replace_retains_history(event):
    a=upload(event);b=upload(event,payload=b'new version')
    a.refresh_from_db()
    assert not a.current and b.current
    assert b.sha256==hashlib.sha256(b'new version').hexdigest()
    assert can_download(event[3][0],a)
    assert can_download(event[4],a)
    assert AuditEvent.objects.filter(action='file.superseded',sha256=a.sha256).exists()

def test_quarantine_rejects_upload_and_delete(event):
    asset=upload(event)
    r=event[1];r.quarantine_at=timezone.now()-dt.timedelta(seconds=1);r.save()
    with pytest.raises(PermissionDenied): upload(event)
    with pytest.raises(PermissionDenied): delete_submission(user=event[3][0],asset_id=asset.pk)

def test_deadline_rechecked_after_storage_transfer(event):
    from django.core.files.storage import default_storage
    real_save=default_storage.save
    def slow_save(*args,**kwargs):
        key=real_save(*args,**kwargs)
        r=event[1];r.quarantine_at=timezone.now()-dt.timedelta(seconds=1);r.save()
        return key
    with patch('arena.services.default_storage.save',side_effect=slow_save):
        with pytest.raises(PermissionDenied): upload(event)
    assert not Asset.objects.exists()

def test_code_accepts_binary_and_is_never_executed(event):
    assert upload(event,payload=b'\x00\xff\x01').size==3

def test_legacy_file_slots_also_accept_opaque_content(event):
    assert upload(event,'round_json',b'[]').size==2
    assert upload(event,'round_json',b'{broken').size==7

def test_attestation_required(event):
    with pytest.raises(ValidationError):
        upload_asset(user=event[3][0],file=SimpleUploadedFile('a.py',b'x'),kind='round_code',team=event[2][0],round_=event[1])

def test_upload_size_metadata_does_not_impose_an_artificial_cap(event):
    file=SimpleUploadedFile('large.bin',b'actual streamed bytes')
    file.size=5*1024**3
    asset=upload_asset(user=event[3][0],team=event[2][0],kind='round_file',
        round_=event[1],file=file,attested=True)
    assert asset.size==len(b'actual streamed bytes')

def test_archive_has_server_release_gates(client,event):
    asset=upload(event,'tdp',b'private paper')
    asset.scan_status='clean';asset.public_approved=True;asset.save()
    assert client.get(f'/files/{asset.pk}/').status_code==404
    c=event[0];c.phase='finished';c.archive_released=True;c.save()
    assert client.get(f'/files/{asset.pk}/').status_code==404
    c.ends_at=timezone.now()-dt.timedelta(minutes=1);c.save()
    assert client.get(f'/files/{asset.pk}/').status_code==404
    client.force_login(event[3][1])
    assert client.get(f'/files/{asset.pk}/').status_code==404
    client.force_login(event[3][0])
    assert client.get(f'/files/{asset.pk}/').status_code==200

def test_pending_scan_cannot_be_published(client,event):
    a=upload(event,'poster')
    client.force_login(event[4]);client.post('/control/action/',{'action':'approve-file','id':a.pk})
    a.refresh_from_db();assert not a.public_approved

def test_early_map_release_requires_explicit_completion(client,event):
    client.force_login(event[4]);client.post('/control/action/',{'action':'release-maps','id':event[1].pk})
    event[1].refresh_from_db();assert not event[1].maps_released
    original_end=event[1].ends_at
    client.post('/control/action/',{'action':'complete-round','id':event[1].pk})
    event[1].refresh_from_db();assert event[1].completed and not event[1].editable
    client.post('/control/action/',{'action':'release-maps','id':event[1].pk})
    event[1].refresh_from_db();assert event[1].maps_open and event[1].ends_at==original_end

def test_targeted_announcement_notification_and_outbox(event):
    c,r,teams,users,staff=event
    a=announce(user=staff,competition=c,title='Private briefing',body='Only team 101.',general=False,public=False,target_ids=[teams[0].pk])
    assert Notification.objects.filter(announcement=a,team=teams[0]).exists()
    assert not Notification.objects.filter(announcement=a,team=teams[1]).exists()
    assert list(EmailDelivery.objects.values_list('recipient',flat=True))==[teams[0].leader_email]

def test_public_targeted_announcement_is_explicitly_allowed(event):
    notice=announce(user=event[4],competition=event[0],title='Public',body='Public',general=False,public=True,target_ids=[event[2][0].pk])
    assert notice.public and notice.targets.count()==1
    assert Notification.objects.filter(announcement=notice).count()==1

def test_dashboard_announcement_works_without_leader_emails(event):
    event[2][0].leader_email='';event[2][0].save()
    announce(user=event[4],competition=event[0],title='All',body='All',general=True,public=False,target_ids=[])
    assert Notification.objects.count()==2
    assert EmailDelivery.objects.count()==1

def test_targeted_resource_is_not_cross_team(event):
    a=upload_asset(user=event[4],file=SimpleUploadedFile('note.txt',b'private'),kind='resource',target_ids=[event[2][0].pk])
    a.scan_status='clean';a.save()
    assert can_download(event[3][0],a)
    assert not can_download(event[3][1],a)

def test_mutations_require_csrf(event):
    client=Client(enforce_csrf_checks=True);client.force_login(event[3][0])
    assert client.post('/submit/round_code/1/',{}).status_code==403

def test_staff_mfa_cannot_be_bypassed(client,event,settings):
    settings.REQUIRE_STAFF_OTP=True
    client.force_login(event[4])
    assert client.get('/control/').status_code==302
    assert client.get('/control/')['Location'].endswith('/account/two_factor/setup/')

@pytest.mark.parametrize('page',['/','/schedule/','/results/','/teams/','/maps/','/resources/','/account/login/'])
def test_public_pages_render(client,event,page):
    response=client.get(page)
    assert response.status_code==200
    assert response['X-Frame-Options']=='DENY'
    assert "object-src 'none'" in response['Content-Security-Policy']

@pytest.mark.parametrize('section',['','submissions/','documents/','resources/','announcements/'])
def test_team_pages_render(client,event,section):
    client.force_login(event[3][0])
    assert client.get('/portal/'+section).status_code==200

def test_admin_page_renders(client,event):
    client.force_login(event[4]);assert client.get('/control/').status_code==200

def test_private_dashboard_has_no_shared_cache(client,event):
    client.force_login(event[3][0])
    response=client.get('/portal/')
    assert 'no-store' in response['Cache-Control']

def test_scanner_response_cannot_enable_inline_execution(client,event):
    a=upload(event,payload=b'<script>alert(1)</script>')
    client.force_login(event[3][0])
    response=client.get(f'/files/{a.pk}/')
    assert response['Content-Security-Policy']=="sandbox; default-src 'none'"

def test_db_backed_throttle_limits_repeated_downloads(client,event):
    from arena.models import RequestQuota
    a=upload(event);client.force_login(event[3][0])
    first=client.get(f'/files/{a.pk}/')
    assert first.status_code==200
    RequestQuota.objects.update(count=180)
    response=client.get(f'/files/{a.pk}/')
    assert response.status_code==429 and int(response['Retry-After'])>0

def test_bootstrap_snapshot_schedule_renders_without_date_format_errors(db,client):
    from django.core.management import call_command
    call_command('bootstrap_event')
    assert client.get('/schedule/').status_code==200
