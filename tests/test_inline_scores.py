from decimal import Decimal
from unittest.mock import patch
import pytest
from django.test import Client
from arena.models import Challenge,Score,AuditEvent,Competition,Round,RunRecording
from arena.recordings import RoundScoresForm,round_scores_revision,result_revision
from test_results_recordings import export_zip,post_result

pytestmark=pytest.mark.django_db


def payload(round_,values):
    form=RoundScoresForm(round_=round_)
    return {'revision':form.initial['revision'],**{f'raw_{team.pk}':values[i] for i,team in enumerate(form.teams)}}


def save(client,round_,data):
    return client.post(f'/control/results/{round_.pk}/scores/',data,HTTP_X_ASR_SCORES='1')


def field_round(event):
    c,r,*_=event
    r.challenge=Challenge.objects.create(competition=c,name='Field',category='main',expected_rounds=1,discard_count=0)
    r.save()
    return r


def test_save_round_table_normalizes_all_teams_and_preserves_recording(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    assert post_result(client,event,export_zip()).status_code==302
    recording=RunRecording.objects.get()
    # An existing publication flag must not be altered by a score-only save.
    RunRecording.objects.filter(pk=recording.pk).update(published=True)
    recording.refresh_from_db();original=dict(RunRecording.objects.values().get())
    r=field_round(event)
    data=payload(r,['75','100']);response=save(client,r,data)
    assert response.status_code==200,response.content
    assert response.json()['normalized']=={str(teams[0].pk):'0.7500',str(teams[1].pk):'1.0000'}
    assert response.json()['revision']!=data['revision']
    assert list(Score.objects.filter(round=r).order_by('team__name').values_list('raw',flat=True))==[75,100]
    assert not Score.objects.filter(round=r,normalized_override=True).exists()
    assert dict(RunRecording.objects.values().get())==original
    c.refresh_from_db();assert not c.workbook_enabled
    assert AuditEvent.objects.filter(action='scores.updated',object_id=str(r.pk)).count()==1
    # A new maximum must also recalculate an unchanged opponent.
    response=save(client,r,payload(r,['75','200']))
    assert response.status_code==200
    assert Score.objects.get(round=r,team=teams[0]).normalized==Decimal('.3750')
    # Blanks clear a result; zero remains a real score.
    assert save(client,r,payload(r,['','0'])).status_code==200
    assert Score.objects.get(round=r,team=teams[0]).raw is None
    assert Score.objects.get(round=r,team=teams[1]).raw==0
    assert all(value is None for value in Score.objects.filter(round=r).values_list('normalized',flat=True))


@pytest.mark.parametrize('bad',['-1','1.00001','10000000000','NaN'])
def test_invalid_table_entry_rolls_back_whole_round(client,event,bad):
    client.force_login(event[-1]);r=field_round(event)
    assert save(client,r,payload(r,['75','100'])).status_code==200
    before=list(Score.objects.order_by('pk').values())
    response=save(client,r,payload(r,['80',bad]))
    assert response.status_code==400 and response.json()['errors']
    assert list(Score.objects.order_by('pk').values())==before


def test_table_rejects_stale_scores_missing_rows_and_team_changes(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    stale=payload(r,['1','2'])
    assert save(client,r,payload(r,['75','100'])).status_code==200
    before=list(Score.objects.order_by('pk').values())
    assert save(client,r,stale).status_code==409
    incomplete=payload(r,['3','4']);incomplete.pop(f'raw_{teams[0].pk}')
    assert save(client,r,incomplete).status_code==400
    current=payload(r,['3','4']);teams[1].active=False;teams[1].save()
    assert save(client,r,current).status_code==409
    assert list(Score.objects.order_by('pk').values())==before


def test_table_requires_staff_csrf_and_current_competition(client,event):
    c,r,teams,users,staff=event;data=payload(r,['75','100'])
    assert save(client,r,data).status_code in [302,403]
    client.force_login(users[0]);assert save(client,r,data).status_code in [302,403]
    assert not Score.objects.exists()
    secured=Client(enforce_csrf_checks=True);secured.force_login(staff)
    assert save(secured,r,data).status_code==403
    client.force_login(staff)
    other=Competition.objects.create(slug='other-event',starts_at=c.starts_at,ends_at=c.ends_at)
    foreign=Round.objects.create(competition=other,number=1,opens_at=r.opens_at,quarantine_at=r.quarantine_at,starts_at=r.starts_at,ends_at=r.ends_at)
    assert save(client,foreign,payload(foreign,[])).status_code==404
    r.archived_at=r.starts_at;r.save()
    assert save(client,r,data).status_code==404
    assert not Score.objects.exists()


def test_table_revision_matches_displayed_snapshot_even_during_another_save(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    assert save(client,r,payload(r,['75','100'])).status_code==200
    def concurrent_save(round_,teams_,scores=None):
        Score.objects.filter(round=r,team=teams[0]).update(raw=85)
        return round_scores_revision(round_,teams_,scores)
    with patch('arena.recordings.round_scores_revision',side_effect=concurrent_save):
        data=payload(r,['80','100'])
    assert save(client,r,data).status_code==409
    assert Score.objects.get(round=r,team=teams[0]).raw==85


def test_recording_only_editor_cannot_change_scores(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    assert save(client,r,payload(r,['75','100'])).status_code==200
    before=list(Score.objects.order_by('pk').values())
    url=f'/control/results/{r.pk}/{teams[0].pk}/?recording=1'
    page=client.get(url)
    assert page.status_code==200 and b'<legend>Scores</legend>' not in page.content
    response=client.post(url,{'revision':result_revision(r,teams[0]),'raw':'9999','normalized':'99','normalized_override':'on','files':export_zip()})
    assert response.status_code==302,response.content
    assert list(Score.objects.order_by('pk').values())==before
    assert RunRecording.objects.count()==1
