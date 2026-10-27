from datetime import timedelta
from decimal import Decimal
import json
import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone
from arena.models import Asset, Challenge, Complaint, EmailDelivery, Membership, Programme, Quarantine, Round, Score, Team
from arena.recordings import RoundScoresForm
from arena.services import upload_asset
from arena.views import standings

pytestmark=pytest.mark.django_db


def sample(event):
    c,r,teams,users,staff=event
    challenge=Challenge.objects.create(competition=c,name='Rescue Relay',category='superteam',expected_rounds=1,calculation='sum',score_source='raw')
    group=Team.objects.create(competition=c,code='ST01',name='First pair',country='Canada',superteam_challenge=challenge)
    group.members.set(teams)
    third=Team.objects.create(competition=c,code='THIRD',name='Third team',country='Canada')
    outsider=get_user_model().objects.create_user(username='outsider',password='test-only-pass-2026')
    Membership.objects.create(user=outsider,team=third)
    return challenge,group,third,outsider


def file(name='one.bin',body=b'evidence'): return SimpleUploadedFile(name,body)
def stamp(value):return timezone.localtime(value).strftime('%Y-%m-%dT%H:%M')


def test_admin_superteam_pair_validation_and_existing_account_reuse(event,client):
    c,r,teams,users,staff=event;challenge=Challenge.objects.create(competition=c,name='Relay',category='superteam')
    client.force_login(staff)
    data={'form':'superteam','superteam_challenge':challenge.pk,'code':'PAIR','name':'Paired team','active':'on','members':[t.pk for t in teams]}
    before=get_user_model().objects.count()
    response=client.post('/control/',{**data,'members':[teams[0].pk]})
    assert response.status_code==200 and b'exactly two' in response.content
    response=client.post('/control/',data);assert response.status_code==302,response.content
    group=Team.objects.get(code='PAIR');assert set(group.members.all())==set(teams)
    assert get_user_model().objects.count()==before and not EmailDelivery.objects.exists()
    assert client.post('/control/',{**data,'code':'DUP','name':'Duplicate'}).status_code==200
    assert not Team.objects.filter(code='DUP').exists()
    assert client.get(f'/control/?editor=superteam&superteam={group.pk}').status_code==200
    assert client.post('/control/',{**data,'form':'team','record_id':group.pk}).status_code==404
    client.force_login(users[0]);assert client.post('/control/',data).status_code in [302,403]
    secured=Client(enforce_csrf_checks=True);secured.force_login(staff);assert secured.post('/control/',data).status_code==403


def test_shared_workspace_access_is_revoked_immediately_without_exposing_individual_files(event,client):
    c,r,teams,users,staff=event;ch,group,third,outsider=sample(event)
    shared=upload_asset(user=users[0],team=group,kind='code',file=file('shared.py'))
    own=upload_asset(user=users[0],team=teams[0],kind='code',file=file('private.py'))
    base=f'/portal/superteams/{group.pk}'
    for user in users:
        client.force_login(user)
        assert client.get(base+'/').status_code==200
        assert client.get(f'/files/{shared.pk}/').status_code==200
        assert group.name.encode() in client.get('/portal/').content
    client.force_login(users[1]);assert client.get(f'/files/{own.pk}/').status_code==404
    client.force_login(outsider);assert client.get(base+'/').status_code==404 and client.get(f'/files/{shared.pk}/').status_code==404
    client.force_login(staff)
    response=client.post('/control/',{'form':'superteam','record_id':group.pk,'code':group.code,'name':group.name,
        'superteam_challenge':ch.pk,'members':[teams[1].pk,third.pk],'active':'on'})
    assert response.status_code==302,response.content
    client.force_login(users[0]);assert client.get(base+'/').status_code==404 and client.get(f'/files/{shared.pk}/').status_code==404
    assert client.get(f'/files/{own.pk}/').status_code==200
    client.force_login(outsider);assert client.get(base+'/').status_code==200 and client.get(f'/files/{shared.pk}/').status_code==200
    client.logout();assert client.get(f'/files/{shared.pk}/').status_code==404


def test_superteam_round_lineup_scores_and_calendar_are_separate(event,client):
    c,r,teams,users,staff=event;ch,group,third,outsider=sample(event)
    fourth=Team.objects.create(competition=c,code='FOURTH',name='Fourth team',country='Canada')
    other=Team.objects.create(competition=c,code='ST02',name='Second pair',country='Canada',superteam_challenge=ch)
    other.members.set([third,fourth])
    client.force_login(staff)
    lineup=[{'team':str(t.pk),'duration':10,'gap':0,'field':'Relay','confirmed':True} for t in [other,group]]
    response=client.post('/control/',{'form':'round','challenge':ch.pk,'number':1,'name':'Relay final','starts_at':stamp(r.starts_at),'lineup-lineup':json.dumps(lineup)})
    assert response.status_code==302,response.content
    relay=Round.objects.get(challenge=ch)
    assert list(Programme.objects.filter(round=relay).values_list('team_id',flat=True))==[other.pk,group.pk]
    assert relay.ends_at==relay.starts_at+timedelta(minutes=20)
    form=RoundScoresForm(round_=relay,matrix=True,prefix=f'r{relay.pk}')
    data={'score_challenge':ch.pk,'round_ids':str(relay.pk)}
    data.update({form.add_prefix(name):'' if value is None else value for name,value in form.initial.items() if value is not False})
    data.update({f'r{relay.pk}-raw_{group.pk}':'150',f'r{relay.pk}-raw_{other.pk}':'100'})
    response=client.post('/control/results/scores/',data,HTTP_X_ASR_SCORES='1');assert response.status_code==200,response.content
    ch.rankings_released=True;ch.save(update_fields=['rankings_released'])
    rows=standings(c,ch)[1];assert [row['team'] for row in rows]==[group,other] and rows[0]['total']==150 and rows[0]['rank']==1
    assert {row['team'] for row in standings(c)[1]}==set([*teams,third,fourth])
    assert not Score.objects.filter(team__in=teams).exists()
    context=client.get(f'/control/?score_challenge={ch.pk}').context
    assert len(context['score_rows'])==2 and len(context['result_entries'])==1
    client.force_login(users[0]);assert b'Second pair' in client.get(f'/portal/superteams/{group.pk}/schedule/').content
    assert b'Relay final' not in client.get('/portal/submissions/').content
    assert b'First pair' in client.get(f'/portal/superteams/{group.pk}/results/').content


def test_superteam_quarantine_scope_deadline_and_private_files(event,client):
    c,r,teams,users,staff=event;ch,group,third,outsider=sample(event)
    client.force_login(staff)
    response=client.post('/control/',{'form':'quarantine','challenge':ch.pk,'name':'Relay handoff',
        'deadline':stamp(timezone.now()+timedelta(hours=1)),'all_teams':'on'})
    assert response.status_code==302,response.content
    quarantine=Quarantine.objects.get();assert quarantine.deadline_for(group) and quarantine.deadline_for(teams[0]) is None
    base=f'/portal/superteams/{group.pk}'
    client.force_login(users[0]);assert b'Relay handoff' in client.get(base+'/submissions/').content
    assert b'Relay handoff' not in client.get('/portal/submissions/').content
    url=base+f'/quarantines/{quarantine.pk}/upload/'
    response=client.post(url,{'files':[file('one.py'),file('two.json')]});assert response.status_code==302 and response.url.startswith(base)
    assert Asset.objects.filter(team=group,quarantine=quarantine).count()==2
    client.force_login(users[1]);assert all(client.get(f'/files/{asset.pk}/').status_code==200 for asset in Asset.objects.all())
    quarantine.deadline=timezone.now()-timedelta(seconds=1);quarantine.save()
    client.post(url,{'files':[file('late.bin')]});assert not Asset.objects.filter(original_name='late.bin').exists()
    asset=Asset.objects.first();assert client.post(f'/files/{asset.pk}/remove/').status_code==403
    client.force_login(outsider);assert client.post(url,{'files':[file()]}).status_code==404
    assert not EmailDelivery.objects.exists()


def test_complaints_support_private_attachments_admin_response_and_no_mail(event,client):
    c,r,teams,users,staff=event
    client.force_login(users[0])
    response=client.post('/portal/complaints/',{'subject':'Review this run','message':'Please review the evidence.',
        'files':[file('trace.json'),file('photo.png')]})
    assert response.status_code==302,response.content
    complaint=Complaint.objects.get();assert complaint.team==teams[0] and complaint.attachments.count()==2
    asset=complaint.attachments.first()
    assert client.get(f'/files/{asset.pk}/').status_code==200
    client.force_login(users[1]);assert b'Review this run' not in client.get('/portal/complaints/').content
    assert client.get(f'/files/{asset.pk}/').status_code==404
    assert client.get(f'/control/complaints/{complaint.pk}/').status_code in [302,403]
    client.logout();assert client.get(f'/files/{asset.pk}/').status_code==404
    client.force_login(staff);assert complaint.subject.encode() in client.get('/control/').content
    assert client.get(f'/files/{asset.pk}/').status_code==200
    response=client.post(f'/control/complaints/{complaint.pk}/',{'status':'resolved','response':'The timing was corrected.'})
    assert response.status_code==302
    client.force_login(users[0]);assert b'The timing was corrected.' in client.get('/portal/complaints/').content
    assert not EmailDelivery.objects.exists()
    response=client.post('/portal/complaints/',{'subject':'No attachments','message':'A concern.'});assert response.status_code==302
    assert Complaint.objects.count()==2
    before=Asset.objects.count()
    response=client.post('/portal/complaints/',{'subject':'Invalid','message':'Test','files':[file(),file('empty.bin',b'')]})
    assert response.status_code==200 and Complaint.objects.count()==2 and Asset.objects.count()==before


def test_organizer_multiple_files_share_one_subject_and_access(event,client):
    c,r,teams,users,staff=event;client.force_login(staff)
    response=client.post('/control/',{'form':'resource','kind':'resource','title':'Competition brief','targets':[teams[0].pk],
        'file':[file('brief.pdf'),file('notes.txt')]})
    assert response.status_code==302,response.content
    assets=list(Asset.objects.all());assert len(assets)==2
    assert {asset.title for asset in assets}=={'Competition brief'}
    for asset in assets: asset.scan_status='clean';asset.save()
    client.force_login(users[0]);assert all(client.get(f'/files/{asset.pk}/').status_code==200 for asset in assets)
    client.force_login(users[1]);assert all(client.get(f'/files/{asset.pk}/').status_code==404 for asset in assets)
    client.force_login(staff)
    response=client.post('/control/',{'form':'managed-upload','destination':'organizer','title':'Second brief','targets':[teams[0].pk],
        'files':[file('one.md'),file('two.zip')]})
    assert response.status_code==302 and Asset.objects.filter(title='Second brief').count()==2
    assert b'multiple' in client.get('/control/?editor=managed-upload').content
    assert not EmailDelivery.objects.exists()


def test_one_shared_delivery_groups_files_and_revokes_every_file_on_recipient_edit(event,client):
    from arena.models import FileShare
    c,r,teams,users,staff=event;client.force_login(staff)
    response=client.post('/control/',{'form':'managed-upload','destination':'organizer','title':'One shared subject','targets':[team.pk for team in teams],
        'files':[file('instructions.pdf'),file('examples.zip')]})
    assert response.status_code==302
    share=FileShare.objects.get();assets=list(share.files.all())
    assert len(assets)==2 and all(asset.team_id is None for asset in assets) and share.targets.count()==2
    page=client.get('/control/').content.decode()
    assert page.count(f'data-file-share="{share.pk}"')==1
    assert all(team.name in page for team in teams)
    for asset in assets: asset.scan_status='clean';asset.save()
    sessions=[Client(),Client()]
    for session,user in zip(sessions,users):
        session.force_login(user)
        for asset in assets: assert session.get(f'/files/{asset.pk}/').status_code==200
        assert session.get('/portal/resources/').content.count(b'<h2>One shared subject</h2>')==1
    response=client.post('/control/',{'form':'share','record_id':share.pk,'recipient_module':'1','title':'One shared subject','targets':[teams[0].pk]})
    assert response.status_code==302,response.content
    assert FileShare.objects.count()==1 and Asset.objects.count()==2
    for asset in assets:
        assert sessions[1].get(f'/files/{asset.pk}/').status_code==404
        assert sessions[0].get(f'/files/{asset.pk}/').status_code==200
    assert b'One shared subject' not in sessions[1].get('/portal/resources/').content
    client.post('/control/action/',{'action':'remove-share','id':share.pk})
    for asset in assets: assert sessions[0].get(f'/files/{asset.pk}/').status_code==404
    assert client.get(f'/files/{assets[0].pk}/').status_code==200
    client.post('/control/action/',{'action':'restore-share','id':share.pk})
    assert sessions[0].get(f'/files/{assets[0].pk}/').status_code==200
    assert not EmailDelivery.objects.exists()


def test_public_shared_delivery_requires_every_clean_file_and_one_explicit_approval(event,client):
    from arena.models import FileShare
    c,r,teams,users,staff=event;client.force_login(staff)
    client.post('/control/',{'form':'managed-upload','destination':'organizer','title':'Public delivery','audience':'public',
        'files':[file('first.pdf'),file('second.txt')]})
    share=FileShare.objects.get();assets=list(share.files.all())
    client.post('/control/action/',{'action':'approve-share','id':share.pk})
    share.refresh_from_db();assert not share.public_approved
    for asset in assets: asset.scan_status='clean';asset.save()
    client.post('/control/action/',{'action':'approve-share','id':share.pk})
    share.refresh_from_db();assert share.public_approved
    client.logout()
    for asset in assets: assert client.get(f'/files/{asset.pk}/').status_code==200
    assert client.get('/resources/').content.count(b'<h2>Public delivery</h2>')==1
    client.force_login(staff)
    client.post('/control/',{'form':'share','record_id':share.pk,'recipient_module':'1','title':share.title,'targets':[teams[0].pk]})
    client.logout()
    for asset in assets: assert client.get(f'/files/{asset.pk}/').status_code==404


def test_one_announcement_for_overlapping_direct_and_superteam_recipients(event,client):
    from arena.services import announce
    from arena.models import Announcement,Notification
    c,r,teams,users,staff=event;ch,group,third,outsider=sample(event)
    notice=announce(user=staff,competition=c,title='One announcement',body='Shared message',
        general=False,public=False,target_ids=[teams[0].pk,group.pk],queue_email=False)
    assert Announcement.objects.count()==1
    client.force_login(users[0]);page=client.get('/portal/announcements/')
    assert page.content.count(b'<h2>One announcement</h2>')==1 and page.context['unread_count']==1
    receipt=Notification.objects.filter(announcement=notice,team=teams[0]).get()
    client.post(f'/notices/{receipt.pk}/read/')
    assert client.get('/portal/announcements/').context['unread_count']==0
    client.force_login(outsider);assert b'One announcement' not in client.get('/portal/announcements/').content
    assert not EmailDelivery.objects.exists()


def test_private_superteam_replay_uses_current_membership_on_every_request(event,client):
    from arena.models import RunRecording
    from test_results_recordings import export_zip,post_result
    c,r,teams,users,staff=event;ch,group,third,outsider=sample(event)
    r.challenge=ch;r.save()
    paired_event=(c,r,[group],users,staff)
    client.force_login(staff)
    assert post_result(client,paired_event,export_zip(),raw='50').status_code==302
    recording=RunRecording.objects.get()
    player=f'/recordings/{recording.pk}/player/'
    client.force_login(users[0]);response=client.get(player);assert response.status_code==200
    old_replay=response.json()['url'].split('#')[0]
    client.force_login(users[1]);assert client.get(player).status_code==200
    client.force_login(outsider);assert client.get(player).status_code==404
    client.logout();assert client.get(player).status_code==404
    group.members.set([teams[1],third])
    client.force_login(users[0]);assert client.get(player).status_code==404 and client.get(old_replay).status_code==404
    client.force_login(users[1]);assert client.get(player).status_code==200
    client.force_login(staff);assert client.get(player).status_code==200
