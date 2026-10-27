from datetime import timedelta
from decimal import Decimal
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from arena.models import Asset,Challenge,Programme,Quarantine,Round,Score,Team
from arena.policy import challenge_total
from arena.services import save_quarantine
from arena.views import standings

pytestmark=pytest.mark.django_db

def stamp(value):return timezone.localtime(value).strftime('%Y-%m-%dT%H:%M')

def challenge(client,event,**changes):
    client.force_login(event[4])
    data={'form':'challenge','name':'SuperTeam relay','category':'superteam','expected_rounds':2,
        'calculation':'sum','top_count':1,'score_source':'raw',**changes}
    response=client.post('/control/',data)
    assert response.status_code==302,response.context['challenge_form'].errors if response.context else ''
    return Challenge.objects.get(name=data['name'])

def test_challenges_have_independent_round_numbers_and_real_calculations(client,event):
    c,r,teams,users,staff=event
    main=challenge(client,event,name='Main event',category='main',expected_rounds=1)
    r.challenge=main;r.save()
    extra=challenge(client,event)
    pair=Team.objects.create(competition=c,code='PAIR',name='Paired teams',country='Canada',superteam_challenge=extra)
    pair.members.set(teams)
    data={'form':'round','challenge':extra.pk,'number':1,'name':'Relay one',
        'starts_at':stamp(r.starts_at),'end_mode':'duration','duration_minutes':25}
    assert client.post('/control/',data).status_code==302
    relay=Round.objects.get(challenge=extra,number=1)
    assert relay.duration_minutes==15 and not relay.submissions_enabled
    assert client.post('/control/',data).status_code==200
    data.update(number=2,name='Relay two')
    assert client.post('/control/',data).status_code==302
    for round_,value in zip(Round.objects.filter(challenge=extra),[Decimal('20'),Decimal('40')]):
        Score.objects.create(round=round_,team=pair,raw=value,normalized=1)
    assert standings(c,extra)[1][0]['total']==60
    extra.calculation='average';extra.save()
    assert standings(c,extra)[1][0]['total']==30
    extra.calculation='best';extra.top_count=1;extra.save()
    assert standings(c,extra)[1][0]['total']==40
    page=client.get('/results/').content.decode()
    assert 'SuperTeam relay' in page and '40.00' in page
    assert len(standings(c,main)[0])==1


def test_top_round_editor_uses_team_duration_and_preserves_submission_window(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    opening,deadline=r.opens_at,r.quarantine_at
    response=client.get(f'/control/?round={r.pk}')
    html=response.content.decode()
    assert html.index(f'id="round-editor-{r.pk}"')<html.index(f'id="round-row-{r.pk}"')<html.index('id="accounts"')
    fields=response.context['round_form'].fields
    assert not {'opens_at','quarantine_at','end_mode','duration_minutes','ends_at','playback_url'}&set(fields)
    import json
    rows=[{'team':str(t.pk),'duration':20,'gap':5} for t in teams]
    data={'form':'round','record_id':r.pk,'number':1,'name':'Edited in place',
        'starts_at':stamp(r.starts_at-timedelta(hours=3)),'lineup-lineup':json.dumps(rows)}
    assert client.post('/control/',data).status_code==302
    r.refresh_from_db()
    assert r.duration_minutes==50 and r.opens_at==opening and r.quarantine_at==deadline
    data['lineup-lineup']=json.dumps([{**rows[0],'duration':0}])
    assert client.post('/control/',data).status_code==200


def test_schedule_editor_uses_end_or_duration_and_stays_adjacent(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    data={'form':'event','title':'Technical challenge demo','starts_at':stamp(r.starts_at),
        'end_mode':'duration','duration_minutes':17,'confirmed':'on'}
    assert client.post('/control/',data).status_code==302
    item=Programme.objects.get(title=data['title']);assert item.duration_minutes==17
    page=client.get(f'/control/?editor=event&event={item.pk}').content.decode()
    assert 'name="record_id"' in page and '<html' not in page
    data.update(record_id=item.pk,end_mode='end',ends_at=stamp(item.starts_at+timedelta(minutes=30)))
    assert client.post('/control/',data).status_code==302
    item.refresh_from_db();assert item.duration_minutes==30


def test_upload_window_config_is_separate_and_server_enforced(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    data={'form':'window','record_id':r.pk,'opens_at':stamp(r.opens_at),'quarantine_at':stamp(r.quarantine_at)}
    assert client.post('/control/',data).status_code==302
    r.refresh_from_db();assert not r.editable
    client.force_login(users[0])
    assert client.post(f'/submit/round_file/{r.pk}/',{'files':SimpleUploadedFile('x.tar',b'x'),'attested':'on'}).status_code==302
    assert Asset.objects.count()==0
    client.force_login(staff);data['submissions_enabled']='on'
    assert client.post('/control/',data).status_code==302
    r.refresh_from_db();assert r.editable
    client.force_login(users[0])
    client.post(f'/submit/round_file/{r.pk}/',{'files':[SimpleUploadedFile('a.tar',b'a'),SimpleUploadedFile('b.xyz',b'b')],'attested':'on'})
    assert Asset.objects.count()==2
    client.force_login(staff)
    html=client.get('/control/').content.decode()
    participant=html.split('id="quarantines"',1)[1].split('id="files"',1)[0]
    assert 'a.tar' in participant and 'b.xyz' in participant and 'Filter files by team' in participant
    assert 'a.tar' not in html.split('id="files"',1)[1].split('id="announce"',1)[0]


def test_named_quarantine_browse_and_opening_enforced(client,event):
    c,r,teams,users,staff=event
    q=save_quarantine(user=staff,competition=c,name='Independent challenge files',instructions='',
        deadline=timezone.now()+timedelta(hours=3),opens_at=timezone.now()+timedelta(hours=1),all_teams=True,targets=[])
    client.force_login(users[0]);client.post(f'/quarantines/{q.pk}/upload/',{'files':SimpleUploadedFile('early.any',b'early')})
    assert not Asset.objects.exists()
    q.opens_at=timezone.now()-timedelta(hours=1);q.save()
    client.post(f'/quarantines/{q.pk}/upload/',{'files':[SimpleUploadedFile('one.any',b'one'),SimpleUploadedFile('two.bin',b'two')]})
    assert Asset.objects.count()==2
    client.force_login(staff);page=client.get('/control/').content.decode()
    assert page.index(q.name)<page.index('one.any')<page.index('id="files"')
    assert 'data-picker-search' in page and 'data-picker-all' in page and 'data-picker-clear' in page
    assert '<select name="targets"' not in page


def test_challenge_removal_retains_scores_and_files_and_blocks_round_uploads(client,event):
    c,r,teams,users,staff=event
    group=challenge(client,event,expected_rounds=1);r.challenge=group;r.save()
    score=Score.objects.create(team=teams[0],round=r,raw=0,normalized=0)
    client.post('/control/action/',{'action':'remove-challenge','id':group.pk})
    r.refresh_from_db();assert not r.editable and Score.objects.filter(pk=score.pk).exists()
    assert group.name not in client.get('/results/').content.decode()
    client.post('/control/action/',{'action':'restore-challenge','id':group.pk})
    r.refresh_from_db();assert r.editable and group.name in client.get('/results/').content.decode()
    foreign=type(c).objects.create(slug='foreign',starts_at=c.starts_at,ends_at=c.ends_at)
    other=Challenge.objects.create(competition=foreign,name='Foreign')
    assert client.get(f'/control/?challenge={other.pk}').status_code==404
    assert challenge_total([Decimal(0),Decimal(0)],'average',1,2)==(Decimal(0),[])
    assert challenge_total([Decimal(4)],'sum',1,2)==(None,[])


def test_explicit_announcement_audience_and_checkbox_selection(client,event):
    from arena.models import Announcement,EmailDelivery
    c,r,teams,users,staff=event;client.force_login(staff)
    data={'form':'notice','title':'Public only','body':'A public update','audience':'public','send_email':'on',
        'general':'on','targets':[teams[0].pk]}
    assert client.post('/control/',data).status_code==302
    notice=Announcement.objects.get();assert notice.public and not notice.general and notice.targets.count()==0
    assert not EmailDelivery.objects.exists() and not notice.notification_set.exists()
    data.update(title='Selected audience',audience='public_selected',targets=[teams[1].pk])
    assert client.post('/control/',data).status_code==302
    notice=Announcement.objects.get(title='Selected audience')
    assert list(notice.targets.all())==[teams[1]] and EmailDelivery.objects.count()==1
    data.update(title='Empty selected',targets=[])
    assert client.post('/control/',data).status_code==200
    assert not Announcement.objects.filter(title='Empty selected').exists()


def test_recipient_checkboxes_render_real_choices_in_upload_and_file_editors(client,event):
    from arena.services import upload_asset
    c,r,teams,users,staff=event;client.force_login(staff)
    response=client.get('/control/')
    for team in teams: assert str(team.pk) in str(response.context['managed_upload_form']['targets'])
    asset=upload_asset(user=staff,file=SimpleUploadedFile('organizer.txt',b'Private organizer file'),kind='resource',general=False,target_ids=[teams[0].pk])
    response=client.get(f'/control/?file={asset.pk}')
    for team in teams: assert str(team.pk) in str(response.context['file_form']['targets'])
    assert 'checked' in str(response.context['file_form']['targets'])
