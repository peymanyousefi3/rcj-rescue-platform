from datetime import timedelta
from io import StringIO
from unittest.mock import patch
import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone
from arena.models import Announcement, Asset, Competition, EmailDelivery, Membership, Programme, Quarantine, Round, Team
from arena.services import announce, save_quarantine

pytestmark=pytest.mark.django_db

def post(client,event,data):
    client.force_login(event[4]);return client.post('/control/',data)

def stamp(value): return timezone.localtime(value).strftime('%Y-%m-%dT%H:%M')

def round_data(event,**changes):
    r=event[1]
    return {'form':'round','record_id':r.pk,'number':r.number,'name':'Qualifying round',
        **{k:stamp(getattr(r,k)) for k in ['opens_at','quarantine_at','starts_at','ends_at']},**changes}

def team_data(team,**changes):
    return {'form':'team','record_id':team.pk,'name':team.name,'code':team.code,'country':team.country,
        'school':team.school,'leader_email':team.leader_email,'active':'on',**changes}

def test_round_crud_programme_and_workbook_persistence(client,event):
    c,r,teams,users,staff=event
    Programme.objects.create(competition=c,source_key='test:run',title='Existing run',round=r,team=teams[0],starts_at=r.starts_at,ends_at=r.ends_at)
    assert post(client,event,round_data(event)).status_code==302
    r.refresh_from_db();c.refresh_from_db()
    assert r.name=='Qualifying round' and not c.workbook_enabled
    with patch('arena.management.commands.sync_workbook.requests.get') as fetch:
        call_command('sync_workbook',stdout=StringIO())
        fetch.assert_not_called()
    assert client.get('/control/').content.decode().index('id="rounds"')<client.get('/control/').content.decode().index('id="accounts"')
    assert client.post('/control/action/',{'action':'remove-round','id':r.pk}).status_code==302
    r.refresh_from_db();assert r.archived_at and not r.editable
    assert not client.get('/schedule/').context['rounds']
    client.force_login(users[0]);response=client.post(f'/submit/round_file/{r.pk}/',{'files':SimpleUploadedFile('late.bin',b'x'),'attested':'on'})
    assert response.status_code==302 and not Asset.objects.exists()
    client.force_login(staff);client.post('/control/action/',{'action':'restore-round','id':r.pk})
    assert [item.pk for item in client.get('/schedule/').context['rounds']]==[r.pk]
    data=round_data(event,number=2);data.pop('record_id')
    assert client.post('/control/',data).status_code==302 and Round.objects.count()==2
    assert client.post('/control/',data).status_code==200 and Round.objects.count()==2

def test_team_account_email_updates_removal_and_creation(client,event):
    c,r,teams,users,staff=event;team=teams[0];user=users[0]
    EmailDelivery.objects.create(team=team,dedupe_key='pending-old-recipient',subject='Old',body='Private',recipient=team.leader_email)
    response=post(client,event,team_data(team,leader_email='new-leader@example.test',username='updated-leader'))
    assert response.status_code==302
    user.refresh_from_db();team.refresh_from_db()
    assert user.email==team.leader_email=='new-leader@example.test' and user.username=='updated-leader'
    assert EmailDelivery.objects.get().expires_at<=timezone.now()
    client.post('/control/action/',{'action':'suspend-team','id':team.pk})
    user.refresh_from_db();assert not user.is_active and Membership.objects.filter(user=user).exists()
    client.post('/control/action/',{'action':'reactivate-team','id':team.pk})
    user.refresh_from_db();assert user.is_active
    data={'form':'team','code':'NEW','name':'New team','country':'Canada','leader_email':'new@example.test',
        'active':'on','create_account':'on','username':'new-leader-account'}
    assert client.post('/control/',data).status_code==302
    account=get_user_model().objects.get(username='new-leader-account')
    assert account.email=='new@example.test' and account.membership.team.name=='New team'
    assert EmailDelivery.objects.filter(team=account.membership.team).count()==1
    client.force_login(users[1]);assert client.post('/control/',data).status_code==302
    assert Team.objects.filter(code='NEW').count()==1

def test_independent_quarantine_remove_restore_keeps_private_files(client,event):
    c,r,teams,users,staff=event
    data={'form':'quarantine','name':'Super Team handoff','deadline':stamp(timezone.now()+timedelta(hours=4)),'all_teams':'on'}
    assert post(client,event,data).status_code==302
    q=Quarantine.objects.get();assert q.round_id is None
    upload={'form':'managed-upload','destination':'quarantine','team':teams[0].pk,'quarantine':q.pk,
        'files':[SimpleUploadedFile('one.tar',b'one'),SimpleUploadedFile('two.bin',b'two')]}
    assert client.post('/control/',upload).status_code==302
    assert Asset.objects.count()==2
    client.post('/control/action/',{'action':'remove-quarantine','id':q.pk})
    q.refresh_from_db();assert q.deadline_for(teams[0]) is None
    client.force_login(users[0]);assert client.post(f'/quarantines/{q.pk}/upload/',{}).status_code==404
    for a in Asset.objects.all(): assert client.get(f'/files/{a.pk}/').status_code==200
    client.force_login(staff);client.post('/control/action/',{'action':'restore-quarantine','id':q.pk})
    q.refresh_from_db();assert q.deadline_for(teams[0])

def test_file_upload_replace_remove_restore_and_metadata_privacy(client,event):
    c,r,teams,users,staff=event
    upload={'form':'managed-upload','destination':'team','team':teams[0].pk,'kind':'tdp',
        'files':[SimpleUploadedFile('one.xyz',b'one'),SimpleUploadedFile('two.any',b'two')]}
    assert post(client,event,upload).status_code==302 and Asset.objects.count()==2
    first=Asset.objects.get(original_name='one.xyz')
    assert client.get(f'/control/?replace={first.pk}').status_code==200
    upload.update(replacement=first.pk,files=[SimpleUploadedFile('replacement.data',b'replacement')])
    assert client.post('/control/',upload).status_code==302
    first.refresh_from_db();assert not first.current and Asset.objects.count()==3
    latest=Asset.objects.get(original_name='replacement.data')
    assert client.post('/control/',{'form':'file','record_id':latest.pk,'title':'Updated title','original_name':'updated.bin','public_copy':'on'}).status_code==302
    latest.refresh_from_db();assert latest.title=='Updated title' and not latest.public_copy
    client.post('/control/action/',{'action':'remove-admin-file','id':latest.pk});latest.refresh_from_db();assert latest.deleted_at
    client.force_login(users[0]);assert client.get(f'/files/{latest.pk}/').status_code==404
    client.force_login(staff);assert client.get(f'/files/{latest.pk}/').status_code==200
    client.post('/control/action/',{'action':'restore-admin-file','id':latest.pk});latest.refresh_from_db();assert not latest.deleted_at and latest.current
    client.force_login(users[1]);assert client.get(f'/files/{latest.pk}/').status_code==404
    client.force_login(users[0]);assert client.get(f'/files/{latest.pk}/').status_code==200

def test_announcement_edit_audience_removal_and_explicit_email(client,event):
    c,r,teams,users,staff=event
    n=announce(user=staff,competition=c,title='Initial',body='Body',general=True,public=True,target_ids=[])
    data={'form':'notice','record_id':n.pk,'title':'Edited notice','body':'New private body','targets':[teams[0].pk]}
    assert post(client,event,data).status_code==302
    assert n.notification_set.count()==1 and EmailDelivery.objects.count()==2
    assert not EmailDelivery.objects.filter(expires_at=None).exists()
    assert b'Edited notice' not in client.get('/').content
    client.force_login(users[0]);assert b'Edited notice' in client.get('/portal/announcements/').content
    client.force_login(users[1]);assert b'Edited notice' not in client.get('/portal/announcements/').content
    client.force_login(staff);client.post('/control/action/',{'action':'remove-announcement','id':n.pk})
    client.force_login(users[0]);assert b'Edited notice' not in client.get('/portal/announcements/').content
    client.force_login(staff);client.post('/control/action/',{'action':'restore-announcement','id':n.pk})
    data['send_email']='on';assert client.post('/control/',data).status_code==302
    assert EmailDelivery.objects.filter(expires_at=None).count()==1

def test_all_record_editors_reject_foreign_competition_and_csrf(client,event):
    from django.test import Client
    c,r,teams,users,staff=event
    other=Competition.objects.create(slug='other',starts_at=c.starts_at,ends_at=c.ends_at)
    foreign=Team.objects.create(competition=other,code='FOREIGN',name='Other team',country='Canada')
    client.force_login(staff)
    assert client.get(f'/control/?team={foreign.pk}').status_code==404
    assert client.post('/control/',team_data(foreign)).status_code==404
    csrf=Client(enforce_csrf_checks=True);csrf.force_login(staff)
    assert csrf.post('/control/',round_data(event)).status_code==403


def test_dynamic_scoring_and_competition_settings(client,event):
    from arena.policy import best_rounds
    from decimal import Decimal
    assert best_rounds([Decimal(i) for i in range(8)],6)==(Decimal(27),[1,2])
    assert best_rounds([0,1,None],2)==(None,[])
    assert best_rounds([1,2],6)==(3,[])
    c=event[0]
    data={'form':'competition','name':'Updated competition','location':'New venue','first_day':timezone.localtime(c.starts_at).date().isoformat(),
        'last_day':timezone.localtime(c.ends_at).date().isoformat(),'phase':c.phase,'counted_rounds':3}
    assert post(client,event,data).status_code==302
    c.refresh_from_db();assert c.name=='Updated competition' and c.counted_rounds==6
    assert b'Updated competition' in client.get('/').content
    assert b'Best 6 / 1' in client.get('/results/').content
    data['workbook_enabled']='on'
    assert client.post('/control/',data).status_code==302
    c.refresh_from_db();assert c.workbook_enabled and c.workbook_digest==''


def test_public_upload_multiple_files_and_private_organizer_targets(client,event):
    c,r,teams,users,staff=event
    upload={'form':'managed-upload','destination':'public','team':teams[0].pk,'kind':'tdp',
        'files':[SimpleUploadedFile('public1.txt',b'one'),SimpleUploadedFile('public2.txt',b'two')]}
    assert post(client,event,upload).status_code==302
    assert Asset.objects.filter(public_copy=True,current=True).count()==2
    upload={'form':'managed-upload','destination':'organizer','targets':[teams[0].pk],
        'files':[SimpleUploadedFile('targeted.txt',b'Private organizer document')]}
    assert client.post('/control/',upload).status_code==302
    item=Asset.objects.get(original_name='targeted.txt');item.scan_status='clean';item.save()
    client.force_login(users[1]);assert client.get(f'/files/{item.pk}/').status_code==404
    client.force_login(users[0]);assert client.get(f'/files/{item.pk}/').status_code==200


def test_removed_teams_do_not_receive_queued_mail(event,settings):
    from django.core import mail
    team=event[2][0];team.active=False;team.save()
    EmailDelivery.objects.create(team=team,dedupe_key='paused-team',subject='Private',body='Private',recipient=team.leader_email)
    settings.DEBUG=True
    call_command('deliver_mail',stdout=StringIO())
    assert not getattr(mail,'outbox',[])
    assert EmailDelivery.objects.get().sent_at is None


def test_round_name_changes_public_poll_version(client,event):
    c,r,teams,users,staff=event
    Programme.objects.create(competition=c,round=r,team=teams[0],source_key='version:run',title='Run',starts_at=r.starts_at,ends_at=r.ends_at)
    before=client.get('/schedule/fragment/').content.decode().split('data-version="',1)[1].split('"',1)[0]
    r.name='New round name';r.save()
    response=client.get('/schedule/fragment/').content.decode()
    assert before!=response.split('data-version="',1)[1].split('"',1)[0] and 'New round name' in response


def test_inflight_workbook_import_cannot_overwrite_manual_edits(client,event):
    from arena.workbook import apply_snapshot
    from django.core.exceptions import ValidationError
    c=event[0];c.workbook_enabled=False;c.save()
    with pytest.raises(ValidationError,match='administrator edits are preserved'):
        apply_snapshot({},'incoming-digest',c)
    assert Team.objects.count()==2 and Round.objects.count()==1
