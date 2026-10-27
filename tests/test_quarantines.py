import datetime as dt
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from arena.access import can_download,public_asset
from arena.forms import QuarantineForm,QuarantineUploadForm
from arena.models import Asset,AuditEvent,Competition,Membership,Quarantine,QuarantineTeam,Team
from arena.services import (check_quarantine_window,delete_submission,save_quarantine,
    set_quarantine_deadline,upload_asset,upload_quarantine_files)

pytestmark=pytest.mark.django_db


def create(event,**kwargs):
    return save_quarantine(user=event[4],competition=event[0],name='Super Team files',instructions='Upload code and all supporting files.',
        deadline=timezone.now()+dt.timedelta(hours=2),all_teams=kwargs.get('all_teams',True),
        targets=kwargs.get('targets',[]),round=event[1])


def files(*names):return [SimpleUploadedFile(name,b'opaque submitted bytes') for name in names]


def send(event,q,team=0,names=('controller.py','robot.json','support.zip'),replacement_id=None,user=None):
    return upload_quarantine_files(user=user or event[3][team],quarantine=q,team=event[2][team],
        files=files(*names),replacement_id=replacement_id)


def test_named_quarantine_all_teams_accepts_many_arbitrary_file_types(event):
    q=create(event)
    uploaded=send(event,q,names=('code.bin','robot.json','notes.pdf','photo.png','bundle.zip','other.custom'))
    assert len(uploaded)==6
    assert all(a.quarantine_id==q.pk and a.round_id==event[1].pk and not a.public_copy for a in uploaded)
    assert all(a.scan_status=='pending' and a.sha256 and can_download(event[3][0],a) for a in uploaded)
    assert q.deadline_for(event[2][1])==q.deadline
    assert AuditEvent.objects.filter(action='quarantine.created').exists()
    assert AuditEvent.objects.filter(action='file.uploaded').count()==6


def test_selected_team_cannot_be_bypassed_by_posting_other_team_id(client,event):
    q=create(event,all_teams=False,targets=[event[2][0]])
    assert q.deadline_for(event[2][1]) is None
    with pytest.raises(PermissionDenied):send(event,q,team=1)
    client.force_login(event[3][1])
    assert b'Super Team files' not in client.get('/portal/submissions/').content
    response=client.post(f'/quarantines/{q.pk}/upload/',{'files':files('bad.exe'),'team':event[2][0].pk})
    assert response.status_code==404 and not Asset.objects.exists()


def test_individual_superteam_deadlines_override_default_and_can_be_cleared(event):
    q=create(event)
    past=timezone.now()-dt.timedelta(seconds=1)
    set_quarantine_deadline(user=event[4],quarantine_id=q.pk,team=event[2][0],deadline=past)
    with pytest.raises(PermissionDenied):send(event,q)
    assert len(send(event,q,team=1))==3
    set_quarantine_deadline(user=event[4],quarantine_id=q.pk,team=event[2][0],deadline=None)
    assert len(send(event,q))==3
    assert AuditEvent.objects.filter(action='quarantine.team_deadline_updated').count()==2


def test_default_change_preserves_explicit_team_deadlines_and_workbook_round(event):
    q=create(event)
    team_deadline=q.deadline+dt.timedelta(hours=1)
    set_quarantine_deadline(user=event[4],quarantine_id=q.pk,team=event[2][0],deadline=team_deadline)
    save_quarantine(user=event[4],competition=event[0],name=q.name,instructions='',
        deadline=q.deadline-dt.timedelta(minutes=30),all_teams=True,targets=[],round=event[1],quarantine_id=q.pk)
    q.refresh_from_db()
    assert q.deadline_for(event[2][0])==team_deadline
    assert q.deadline_for(event[2][1])==q.deadline
    event[1].refresh_from_db()
    assert event[1].quarantine_at!=q.deadline


def test_exact_deadline_locks_upload_replacement_deletion_but_allows_private_download(event,client):
    q=create(event);asset=send(event,q,names=('original.py',))[0]
    with patch('arena.services.timezone.now',return_value=q.deadline):
        with pytest.raises(PermissionDenied):send(event,q)
        with pytest.raises(PermissionDenied):send(event,q,names=('replacement.py',),replacement_id=asset.pk)
        with pytest.raises(PermissionDenied):delete_submission(user=event[3][0],asset_id=asset.pk)
    asset.refresh_from_db();assert asset.current and asset.deleted_at is None
    client.force_login(event[3][0]);assert client.get(f'/files/{asset.pk}/').status_code==200
    client.force_login(event[3][1]);assert client.get(f'/files/{asset.pk}/').status_code==404
    client.logout();assert client.get(f'/files/{asset.pk}/').status_code==404


def test_transfer_crossing_deadline_leaves_no_partial_batch_or_stored_objects(event):
    q=create(event);save=default_storage.save;saved=[]
    def transfer(*args,**kwargs):
        key=save(*args,**kwargs);saved.append(key)
        if len(saved)==2:
            Quarantine.objects.filter(pk=q.pk).update(deadline=timezone.now()-dt.timedelta(seconds=1))
        return key
    with patch('arena.services.default_storage.save',side_effect=transfer):
        with pytest.raises(PermissionDenied):send(event,q)
    assert not Asset.objects.exists()
    assert all(not default_storage.exists(key) for key in saved)
    assert not AuditEvent.objects.filter(action='file.uploaded').exists()


def test_quarantine_replacement_and_delete_retain_history(event,client):
    q=create(event);old=send(event,q,names=('first.py',))[0]
    new=send(event,q,names=('changed-name.bin',),replacement_id=old.pk)[0]
    old.refresh_from_db();assert not old.current and new.current
    assert can_download(event[3][0],old) and not can_download(event[3][1],old)
    with pytest.raises(PermissionDenied):send(event,q,names=('late-replace.py',),replacement_id=old.pk)
    client.force_login(event[3][0]);html=client.get('/portal/submissions/').content
    assert b'Previous versions' in html and b'first.py' in html and b'changed-name.bin' in html
    delete_submission(user=event[3][0],asset_id=new.pk)
    new.refresh_from_db();assert not new.current and new.deleted_at
    assert not can_download(event[3][0],new) and can_download(event[4],new)


def test_replacement_cannot_cross_teams_or_quarantines(event):
    q=create(event);a=send(event,q,names=('a.py',))[0]
    with pytest.raises(PermissionDenied):send(event,q,team=1,names=('x.py',),replacement_id=a.pk)
    other=create(event)
    with pytest.raises(PermissionDenied):send(event,other,names=('x.py',),replacement_id=a.pk)
    a.refresh_from_db();assert a.current


def test_withdrawn_recipient_keeps_own_files_but_cannot_read_updated_request(client,event):
    q=create(event,all_teams=False,targets=event[2])
    asset=send(event,q,names=('retained-own-file.bin',))[0]
    save_quarantine(user=event[4],competition=event[0],quarantine_id=q.pk,
        name='Other team private request',instructions='New confidential instructions for the other team.',
        deadline=q.deadline,all_teams=False,targets=[event[2][1]])
    client.force_login(event[3][0])
    html=client.get('/portal/submissions/').content
    assert b'retained-own-file.bin' in html
    assert b'Other team private request' not in html and b'New confidential instructions' not in html
    assert client.get(f'/files/{asset.pk}/').status_code==200
    assert client.post(f'/quarantines/{q.pk}/upload/',{'files':files('x.bin')}).status_code==404


def test_quarantine_files_never_public_under_any_release_state(event,client):
    q=create(event);asset=send(event,q,names=('private.html',))[0]
    c=event[0];c.phase='finished';c.archive_released=True;c.ends_at=timezone.now()-dt.timedelta(minutes=1);c.save()
    asset.public_approved=True;asset.scan_status='clean';asset.save();asset.refresh_from_db()
    assert not public_asset(asset)
    client.force_login(event[4]);client.post('/control/action/',{'action':'approve-file','id':asset.pk})
    client.logout();assert client.get(f'/files/{asset.pk}/').status_code==404
    assert b'Super Team files' not in client.get('/schedule/fragment/').content
    assert b'private.html' not in client.get('/teams/').content
    # Named requests use their own deadlines, including post-competition requests.
    assert send(event,q,names=('post-event.txt',))


def test_any_number_of_files_is_accepted_and_invalid_batch_stays_atomic(event):
    q=create(event)
    with pytest.raises(ValidationError):upload_quarantine_files(user=event[3][0],team=event[2][0],quarantine=q,
        files=[SimpleUploadedFile('valid.bin',b'valid'),SimpleUploadedFile('empty.bin',b'')])
    assert not Asset.objects.exists()
    assert len(send(event,q,names=tuple(f'{n}.custom' for n in range(20))))==20


def test_admin_can_create_edit_target_override_and_upload_through_dashboard(client,event):
    client.force_login(event[4])
    day=timezone.localdate()+dt.timedelta(days=2)
    data={'form':'quarantine','name':'Round 1 quarantine','deadline':f'{day}T10:30','all_teams':'on','round':event[1].pk}
    assert client.post('/control/',data).status_code==302
    q=Quarantine.objects.get()
    assert timezone.localtime(q.deadline).hour==10 and timezone.localtime(q.deadline).minute==30
    assert client.post('/control/',{'form':'quarantine-deadline','quarantine_id':q.pk,
        'team_id':event[2][0].pk,'deadline':f'{day}T11:30'}).status_code==302
    assert timezone.localtime(q.deadline_for(event[2][0])).hour==11
    assert client.post('/control/',{'form':'quarantine-upload','quarantine':q.pk,'team':event[2][0].pk,
        'files':files('admin.zip','extra.txt')}).status_code==302
    assert Asset.objects.count()==2
    response=client.get('/control/?quarantine='+str(q.pk));assert response.status_code==200
    assert response.context['quarantine_form'].instance.pk==q.pk
    data.update(quarantine_id=str(q.pk),name='Updated request',deadline=f'{day}T12:00')
    assert client.post('/control/',data).status_code==302
    q.refresh_from_db();assert q.name=='Updated request'
    assert timezone.localtime(q.deadline_for(event[2][0])).hour==11
    old=Asset.objects.first()
    assert client.post('/control/',{'form':'quarantine-upload','quarantine':q.pk,'team':event[2][0].pk,
        'replacement':old.pk,'files':files('replacement.zip')}).status_code==302
    old.refresh_from_db();assert not old.current


@pytest.mark.parametrize('popup',[False,True])
def test_deadline_save_and_clear_return_to_same_quarantine(client,event,popup):
    q=create(event);client.force_login(event[4])
    destination=f'/control/#quarantine-{q.pk}'
    override=timezone.localtime(q.deadline+dt.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M')
    for deadline in [override,'']:
        response=client.post('/control/',{'form':'quarantine-deadline','quarantine_id':q.pk,
            'team_id':event[2][0].pk,'deadline':deadline},**({'HTTP_X_ASR_EDITOR':'1'} if popup else {}))
        if popup:
            assert response.status_code==200 and response.json()=={'redirect':destination}
        else:
            assert response.status_code==302 and response.url==destination
        q.refresh_from_db()
        assert q.deadline_for(event[2][0])==(timezone.make_aware(dt.datetime.fromisoformat(deadline)) if deadline else q.deadline)


def test_team_multifile_post_uses_own_membership_and_no_content_type_restrictions(client,event):
    q=create(event);client.force_login(event[3][0])
    response=client.post(f'/quarantines/{q.pk}/upload/',{'files':files('controller.exe','invalid-but-opaque.json','archive.7z'),
        'team':event[2][1].pk,'public_copy':'on'})
    assert response.status_code==302 and Asset.objects.count()==3
    assert all(a.team_id==event[2][0].pk and not a.public_copy for a in Asset.objects.all())
    assert all(can_download(event[3][0],a) and not can_download(event[3][1],a) for a in Asset.objects.all())


def test_teams_cannot_manage_quarantines_and_mfa_csrf_are_enforced(client,event,settings):
    q=create(event);client.force_login(event[3][0])
    assert client.post('/control/',{'form':'quarantine','name':'forged'}).status_code==302
    with pytest.raises(PermissionDenied):set_quarantine_deadline(user=event[3][0],quarantine_id=q.pk,team=event[2][0],deadline=None)
    csrf=Client(enforce_csrf_checks=True);csrf.force_login(event[3][0])
    assert csrf.post(f'/quarantines/{q.pk}/upload/',{'files':files('x.py')}).status_code==403
    csrf.force_login(event[4]);assert csrf.post('/control/',{'form':'quarantine'}).status_code==403
    settings.REQUIRE_STAFF_OTP=True
    # Even a staff account assigned to a team cannot mutate files without MFA.
    Membership.objects.create(user=event[4],team=event[2][0]);client.force_login(event[4])
    assert client.post(f'/quarantines/{q.pk}/upload/',{'files':files('x.py')}).status_code==302
    assert not Asset.objects.exists()


def test_cross_competition_and_nonrecipient_deadline_changes_are_rejected(event):
    q=create(event,all_teams=False,targets=[event[2][0]])
    with pytest.raises(ValidationError):set_quarantine_deadline(user=event[4],quarantine_id=q.pk,team=event[2][1],deadline=None)
    c=Competition.objects.create(slug='other',starts_at=event[0].starts_at,ends_at=event[0].ends_at)
    t=Team.objects.create(competition=c,code='other',name='Other',country='Canada')
    assert q.deadline_for(t) is None
    with pytest.raises(ValidationError):save_quarantine(user=event[4],competition=event[0],name='Bad',instructions='',deadline=q.deadline,all_teams=False,targets=[t])


def test_forms_validate_all_files_empty_targets_and_ambiguous_local_time(event):
    form=QuarantineUploadForm({}, {'files':files('one.py','two.py')})
    # MultiValueDict is supplied by the real request parser; exercise the field directly here.
    field=form.fields['files']
    assert len(field.clean(files('one.py','two.py')))==2
    assert len(field.clean(files(*[f'{n}.bin' for n in range(20)])))==20
    form=QuarantineForm({'name':'Empty','deadline':'2026-10-24T10:00'},competition=event[0])
    assert not form.is_valid() and 'targets' in form.errors
    form=QuarantineForm({'name':'Ambiguous','deadline':'2026-11-01T01:30','all_teams':'on'},competition=event[0])
    assert not form.is_valid() and 'deadline' in form.errors
