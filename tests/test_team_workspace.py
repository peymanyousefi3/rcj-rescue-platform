import datetime as dt
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from arena.access import can_download
from arena.models import Asset, AuditEvent
from arena.services import save_quarantine, upload_asset, upload_files

pytestmark=pytest.mark.django_db


def files(*names):
    return [SimpleUploadedFile(name,b'opaque file bytes\x00\xff') for name in names]


def test_team_menu_order_and_combined_submissions_keep_admin_activity(client,event):
    c,r,teams,users,staff=event
    q=save_quarantine(user=staff,competition=c,name='Individual requested files',instructions='Private request',
        deadline=timezone.now()+dt.timedelta(hours=2),all_teams=True,targets=[],round=r)
    client.force_login(users[0])
    page=client.get('/portal/submissions/')
    nav=page.content.decode().split('aria-label="Team dashboard"',1)[1].split('</nav>',1)[0]
    labels=['Organizer files','Announcements','Dashboard','Submissions','Team documents']
    assert [nav.index('>'+label) for label in labels]==sorted(nav.index('>'+label) for label in labels)
    assert 'Activity' not in nav and 'Quarantines' not in nav
    assert b'Individual requested files' in page.content and b'Round 1' in page.content
    assert b'Controller code' not in page.content and b'JSON' not in page.content
    assert b'name="files" multiple' in page.content and b'accept=' not in page.content
    assert client.get('/portal/quarantines/').url=='/portal/submissions/'
    assert client.get('/portal/activity/').url=='/portal/'
    client.force_login(staff)
    admin=client.get('/control/')
    assert b'Activity &amp; file hashes' in admin.content
    assert b'dashboard.viewed' in admin.content and users[0].username.encode() in admin.content


def test_round_multifile_accepts_any_type_and_preserves_each_file(client,event):
    c,r,teams,users,staff=event
    client.force_login(users[0])
    response=client.post(f'/submit/round_file/{r.pk}/',{'files':files('one.exe','two.json','third.7z'),
        'attested':'on','team':teams[1].pk,'public_copy':'on'})
    assert response.status_code==302
    assets=list(Asset.objects.all())
    assert len(assets)==3 and all(a.kind=='round_file' and a.current for a in assets)
    assert all(a.team_id==teams[0].pk and not a.public_copy for a in assets)
    assert all(can_download(users[0],a) and can_download(staff,a) and not can_download(users[1],a) for a in assets)
    assert AuditEvent.objects.filter(action='file.uploaded').count()==3
    client.post(f'/submit/round_file/{r.pk}/',{'files':files('fourth.pdf'),'attested':'on'})
    assert Asset.objects.filter(current=True).count()==4
    old=assets[0]
    client.post(f'/submit/round_file/{r.pk}/',{'files':files('replacement.custom'),'attested':'on','replacement':old.pk})
    old.refresh_from_db();assert not old.current
    assert Asset.objects.filter(current=True).count()==4 and Asset.objects.count()==5
    client.force_login(users[1])
    client.post(f'/submit/round_file/{r.pk}/',{'files':files('forged.bin'),'attested':'on','replacement':old.pk})
    assert Asset.objects.count()==5


def test_team_documents_add_multiple_and_replace_only_selected_file(client,event):
    client.force_login(event[3][0])
    assert client.post('/submit/tdp/',{'files':files('one.pdf','two.docx')}).status_code==302
    assert Asset.objects.filter(kind='tdp',current=True).count()==2
    old=Asset.objects.first()
    client.post('/submit/tdp/',{'files':files('new.pdf'),'replacement':old.pk})
    old.refresh_from_db();assert not old.current
    assert Asset.objects.filter(kind='tdp',current=True).count()==2
    assert b'name="files" multiple' in client.get('/portal/documents/').content


def test_round_batch_deadline_rolls_back_every_file(event):
    c,r,teams,users,staff=event
    original=upload_asset
    def finish_round(**kwargs):
        asset=original(**kwargs)
        r.quarantine_at=timezone.now()-dt.timedelta(seconds=1);r.save()
        return asset
    with patch('arena.services.upload_asset',side_effect=finish_round):
        with pytest.raises(PermissionDenied):
            upload_files(user=users[0],team=teams[0],round_=r,kind='round_file',
                files=files('first.bin','second.bin'),attested=True)
    assert not Asset.objects.exists()


def test_many_uploaded_files_use_disk_without_a_count_cap(client,event):
    client.force_login(event[3][0])
    response=client.post('/submit/tdp/',{'files':files(*[f'{n}.custom' for n in range(20)])})
    assert response.status_code==302
    assert Asset.objects.filter(current=True).count()==20


def test_closed_round_stays_closed_and_legacy_files_stay_visible(client,event):
    legacy=upload_asset(user=event[3][0],team=event[2][0],round_=event[1],kind='round_code',
        file=files('existing.bin')[0],attested=True)
    r=event[1];r.opens_at=timezone.now()+dt.timedelta(minutes=20);r.save()
    client.force_login(event[3][0])
    assert b'existing.bin' in client.get('/portal/submissions/').content
    client.post(f'/submit/round_file/{r.pk}/',{'files':files('blocked.bin'),'attested':'on'})
    assert Asset.objects.count()==1 and can_download(event[3][0],legacy)


@pytest.mark.parametrize('path,status',[('/submit/tdp/',403),('/quarantines/unknown/upload/',403),('/control/',302)])
def test_anonymous_upload_is_rejected_before_its_body_is_read(path,status):
    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory
    from arena.middleware import SecurityBoundaryMiddleware
    request=RequestFactory().post(path,b'body',content_type='application/octet-stream')
    request.user=AnonymousUser()
    with patch.object(request._stream,'read',side_effect=AssertionError('Upload body must stay unread')) as read:
        response=SecurityBoundaryMiddleware(lambda request: None)(request)
    assert response.status_code==status and 'no-store' in response['Cache-Control']
    read.assert_not_called()
