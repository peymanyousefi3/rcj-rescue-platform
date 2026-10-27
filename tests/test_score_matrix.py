from decimal import Decimal
import pytest
from django.test import Client
from arena.models import Challenge,Round,Score,RunRecording,AuditEvent,Competition,Team
from arena.recordings import RoundScoresForm
from arena.recording_views import score_rounds
from arena.views import standings
from test_field_scoring import field
from test_results_recordings import export_zip,post_result

pytestmark=pytest.mark.django_db


def matrix_data(competition):
    rounds=score_rounds(competition)
    data={'round_ids':','.join(str(round_.pk) for round_ in rounds)}
    for round_ in rounds:
        form=RoundScoresForm(round_=round_,matrix=True,prefix=f'r{round_.pk}')
        for name,value in form.initial.items():
            if value is not False: data[form.add_prefix(name)]='' if value is None else value
    return data


def raw(round_,team):return f'r{round_.pk}-raw_{team.pk}'
def post(client,data):return client.post('/control/results/scores/',data,HTTP_X_ASR_SCORES='1')


def add_round(competition,first,number,challenge=None):
    return Round.objects.create(competition=competition,number=number,challenge=challenge,opens_at=first.opens_at,
        quarantine_at=first.quarantine_at,starts_at=first.starts_at,ends_at=first.ends_at)


def test_full_score_matrix_normalizes_each_column_and_preserves_recordings_and_standings(event,client):
    c,challenge,rounds=field(event,['75','100','400','80'],1,['100','100','1000','100'])
    client.force_login(event[-1]);assert post_result(client,event,export_zip(),raw='75').status_code==302
    recordings=list(RunRecording.objects.values())
    data=matrix_data(c)
    # Field-only scores must ignore attempted manual overrides.
    data[f'r{rounds[0].pk}-override_{event[2][0].pk}']='on'
    data[f'r{rounds[0].pk}-normalized_{event[2][0].pk}']='0.01'
    response=post(client,data);assert response.status_code==200,response.content
    assert len(response.json()['rounds'])==4
    assert response.json()['rounds'][str(rounds[2].pk)]['normalized'][str(event[2][0].pk)]=='0.4000'
    assert not Score.objects.filter(normalized_override=True).exists()
    row=next(row for row in standings(c,challenge)[1] if row['team']==event[2][0])
    assert row['total']==85 and row['dropped']==[3]
    assert list(RunRecording.objects.values())==recordings
    assert AuditEvent.objects.filter(action='scores.updated').count()==4
    precise=matrix_data(c);precise.update({raw(rounds[0],event[2][0]):'6667',raw(rounds[0],event[2][1]):'20000'})
    response=post(client,precise)
    assert response.status_code==200 and response.json()['rounds'][str(rounds[0].pk)]['normalized'][str(event[2][0].pk)]=='0.3334'
    page=client.get('/control/');assert page.status_code==200
    assert page.content.count(b'id="score-matrix"')==1
    assert page.content.count(b'data-score-row')==2
    assert page.content.count(b'data-score-cell')==8
    assert page.content.count(b'form="score-matrix"')==16
    assert b'Scoring settings' in page.content and b'Recording uploads &amp; history' not in page.content
    assert page.content.count(b'class="score-recording')==8 and page.content.count(b'data-score-total')==2
    assert page.content.count(b'data-score-rank')==2 and b'inline=1' in page.content
    assert b'data-score-undo' in page.content and b'data-score-missing-count' in page.content


def test_invalid_cell_prevents_saving_any_round(event,client):
    c,ch,rounds=field(event,['75','100'],0)
    client.force_login(event[-1]);before=list(Score.objects.order_by('pk').values())
    data=matrix_data(c);data[raw(rounds[0],event[2][0])]='80';data[raw(rounds[1],event[2][1])]='-1'
    response=post(client,data)
    assert response.status_code==400 and raw(rounds[1],event[2][1]) in response.json()['errors']
    assert list(Score.objects.order_by('pk').values())==before
    assert not AuditEvent.objects.filter(action='scores.updated').exists()


def test_normalization_failure_rolls_back_earlier_rounds_and_audit(event,client):
    c,first,teams,*_=event
    main=Challenge.objects.create(competition=c,name='Field',expected_rounds=2,discard_count=0,primary=True,calculation='sum')
    first.challenge=main;first.save()
    later=add_round(c,first,2,main)
    data=matrix_data(c);data.update({raw(first,teams[0]):'75',raw(first,teams[1]):'100',
        raw(later,teams[0]):'-9999999999.9999',raw(later,teams[1]):'-.0001'})
    client.force_login(event[-1]);response=post(client,data)
    assert response.status_code==400,response.content
    assert not Score.objects.exists() and not AuditEvent.objects.filter(action='scores.updated').exists()
    c.refresh_from_db();assert c.workbook_enabled


def test_changed_scores_missing_cells_and_new_rounds_reject_the_whole_matrix(event,client):
    c,first,teams,*_=event;later=add_round(c,first,2)
    client.force_login(event[-1]);stale=matrix_data(c)
    Score.objects.create(round=later,team=teams[0],raw=90)
    assert post(client,stale).status_code==409
    current=matrix_data(c);current.pop(raw(first,teams[0]))
    assert post(client,current).status_code==400
    current=matrix_data(c);add_round(c,first,3)
    assert post(client,current).status_code==409
    assert Score.objects.count()==1 and Score.objects.get().raw==90


def test_manual_normalized_controls_remain_available_for_other_scoring_modes(event,client):
    c,r,teams,*_=event;client.force_login(event[-1])
    data=matrix_data(c);data.update({raw(r,teams[0]):'75',raw(r,teams[1]):'100',
        f'r{r.pk}-override_{teams[0].pk}':'on',f'r{r.pk}-normalized_{teams[0].pk}':'0.55'})
    assert post(client,data).status_code==200
    score=Score.objects.get(round=r,team=teams[0]);assert score.normalized==Decimal('.55') and score.normalized_override
    data=matrix_data(c);data[raw(r,teams[1])]='200'
    assert post(client,data).status_code==200
    score.refresh_from_db();assert score.normalized==Decimal('.55')
    data=matrix_data(c);data.pop(f'r{r.pk}-override_{teams[0].pk}')
    assert post(client,data).status_code==200
    score.refresh_from_db();assert not score.normalized_override and score.normalized==Decimal('.375')
    before=list(Score.objects.order_by('pk').values())
    data=matrix_data(c);data.update({raw(r,teams[0]):'',f'r{r.pk}-override_{teams[0].pk}':'on',f'r{r.pk}-normalized_{teams[0].pk}':'0.4'})
    assert post(client,data).status_code==400
    assert list(Score.objects.order_by('pk').values())==before


def test_matrix_requires_staff_and_csrf_and_cannot_edit_inactive_or_foreign_records(event,client):
    c,r,teams,users,staff=event;data=matrix_data(c)
    data[raw(r,teams[0])]='75'
    assert post(client,data).status_code in [302,403]
    client.force_login(users[0]);assert post(client,data).status_code in [302,403]
    secured=Client(enforce_csrf_checks=True);secured.force_login(staff)
    assert post(secured,data).status_code==403
    client.force_login(staff);teams[1].active=False;teams[1].save()
    assert post(client,data).status_code==409
    assert not Score.objects.exists()
    foreign=Competition.objects.create(slug='foreign-event',starts_at=c.starts_at,ends_at=c.ends_at)
    foreign_round=add_round(foreign,r,1)
    foreign_team=Team.objects.create(competition=foreign,code='FOREIGN',name='Foreign team')
    score=Score.objects.create(round=foreign_round,team=foreign_team,raw=50)
    current=matrix_data(c);current[raw(foreign_round,foreign_team)]='999'
    assert post(client,current).status_code==200
    score.refresh_from_db();assert score.raw==50


def test_matrix_refreshes_csrf_after_sign_in_without_weakening_post_protection(event):
    c,r,teams,users,staff=event
    secured=Client(enforce_csrf_checks=True);secured.force_login(staff)
    first=secured.get('/control/results/scores/')
    assert first.status_code==200 and first.cookies['csrftoken']['httponly']
    old_token=first.json()['csrf']
    # A sign-in in another tab rotates the cookie; an old form must not bypass CSRF.
    secured.cookies['csrftoken']='A'*32
    data=matrix_data(c);data[raw(r,teams[0])]='75';data['csrfmiddlewaretoken']=old_token
    assert post(secured,data).status_code==403 and not Score.objects.exists()
    data['csrfmiddlewaretoken']=secured.get('/control/results/scores/').json()['csrf']
    assert post(secured,data).status_code==200
    assert Score.objects.get(round=r,team=teams[0]).raw==75


def preview(client,data):return client.post('/control/results/scores/preview/',data)


def test_live_preview_uses_independent_exact_discards_and_never_saves(event,client):
    c,ch,rounds=field(event,['75','100','400','80'],1,['100','100','1000','100'])
    client.force_login(event[-1]);before=list(Score.objects.order_by('pk').values());data=matrix_data(c)
    response=preview(client,data);assert response.status_code==200,response.content
    result=response.json();a,b=(result['rows'][str(team.pk)] for team in event[2])
    assert a=={'total':'85.00','rank':2,'tie':False,'discarded':[str(rounds[2].pk)],'excluded':[]}
    assert b['total']=='100.00' and b['rank']==1 and b['discarded']==[str(rounds[0].pk)]
    assert not result['provisional'] and result['percentage']
    data[raw(rounds[2],event[2][0])]='900'
    changed=preview(client,data).json()['rows'][str(event[2][0].pk)]
    assert changed['discarded']==[str(rounds[0].pk)] and changed['total']=='90.00'
    assert list(Score.objects.order_by('pk').values())==before
    assert not AuditEvent.objects.filter(action__in=['scores.updated','result.updated']).exists()
    c.refresh_from_db();assert c.workbook_enabled


def test_preview_is_provisional_until_every_team_has_scores_and_handles_all_zero(event,client):
    c,ch,rounds=field(event,['75','100','400','80'],1,['100','100','1000','100'])
    client.force_login(event[-1]);data=matrix_data(c)
    for round_ in rounds[2:]:
        for team in event[2]:data[raw(round_,team)]=''
    result=preview(client,data).json();assert result['provisional']
    assert result['rows'][str(event[2][0].pk)]['total']=='100.00'
    data[raw(rounds[1],event[2][1])]=''
    assert preview(client,data).json()['rows'][str(event[2][0].pk)]['total'] is None
    for team in event[2]:data[raw(rounds[1],team)]='0'
    result=preview(client,data).json();assert 'organizer decision' in result['message']
    assert result['rows'][str(event[2][0].pk)]['total'] is None
    rounds[1].zero_score_policy='exclude';rounds[1].save();data=matrix_data(c)
    for team in event[2]:data[raw(rounds[1],team)]='0'
    result=preview(client,data).json();assert result['rows'][str(event[2][0].pk)]['excluded']==[str(rounds[1].pk)]
    assert result['rows'][str(event[2][0].pk)]['total']=='77.50'


def test_preview_shares_ties_preserves_full_precision_and_ignores_side_challenges(event,client):
    c,ch,rounds=field(event,['9999999999','1'],0,['9999999999.9999','1'])
    client.force_login(event[-1]);data=matrix_data(c)
    result=preview(client,data).json()['rows'];a,b=(result[str(team.pk)] for team in event[2])
    assert a['total']==b['total']=='100.00' and a['rank']==2 and b['rank']==1 and not a['tie']
    data[raw(rounds[0],event[2][0])]='9999999999.9999'
    result=preview(client,data).json()['rows'];assert all(row['rank']==1 and row['tie'] for row in result.values())
    side=Challenge.objects.create(competition=c,name='SuperTeam',calculation='sum',score_source='raw')
    extra=add_round(c,rounds[0],1,side);data=matrix_data(c)
    data[raw(extra,event[2][0])]='9999999';data[raw(extra,event[2][1])]='1'
    result=preview(client,data).json()['rows'];assert result[str(event[2][0].pk)]['rank']==2
    assert all(str(extra.pk) not in row['discarded'] for row in result.values())


def test_preview_enforces_staff_csrf_revision_and_field_validation(event,client):
    c,ch,rounds=field(event,['75','100'],0);data=matrix_data(c)
    assert preview(client,data).status_code==302
    client.force_login(event[3][0]);assert preview(client,data).status_code==302
    secure=Client(enforce_csrf_checks=True);secure.force_login(event[-1]);assert preview(secure,data).status_code==403
    client.force_login(event[-1]);data[raw(rounds[0],event[2][0])]='-1'
    assert preview(client,data).status_code==400
    data=matrix_data(c);Score.objects.filter(round=rounds[0],team=event[2][0]).update(raw=99)
    assert preview(client,data).status_code==409
    assert not AuditEvent.objects.filter(action='scores.updated').exists()


def test_inline_recording_upload_remove_and_restore_return_cell_updates_without_changing_scores(event,client):
    from arena.recordings import result_revision
    c,ch,rounds=field(event,['75'],0);r=rounds[0];team=event[2][0];client.force_login(event[-1])
    before=list(Score.objects.order_by('pk').values())
    url=f'/control/results/{r.pk}/{team.pk}/?recording=1&inline=1'
    response=client.post(url,{'revision':result_revision(r,team),'raw':'999','files':export_zip()},HTTP_X_ASR_EDITOR='1')
    recording=RunRecording.objects.get()
    assert response.status_code==200
    update=response.json()['recording_update'];scores=update.pop('scores')
    assert update=={'round':str(r.pk),'team':str(team.pk),'present':True,'player':f'/recordings/{recording.pk}/player/'}
    assert scores['raw'][str(team.pk)]=='75'
    assert list(Score.objects.order_by('pk').values())==before
    page=client.get(url);assert b'data-recording-action' in page.content and b'Remove current recording' in page.content
    response=client.post(f'/control/recordings/{recording.pk}/remove/',HTTP_X_ASR_RECORDING='1')
    assert response.status_code==200 and not response.json()['recording_update']['present'] and response.json()['recording_update']['player'] is None
    recording.refresh_from_db();assert not recording.current and not recording.published
    response=client.post(f'/control/recordings/{recording.pk}/restore/',HTTP_X_ASR_RECORDING='1')
    assert response.status_code==200 and response.json()['recording_update']['present']
    recording.refresh_from_db();assert recording.current and not recording.published
    assert list(Score.objects.order_by('pk').values())==before


def test_preview_respects_other_challenge_methods_and_manual_normalization(event,client):
    c,ch,rounds=field(event,['75','100'],0,['100','100'])
    ch.calculation='sum';ch.score_source='normalized';ch.save()
    client.force_login(event[-1]);data=matrix_data(c)
    data.update({raw(rounds[0],event[2][0]):'6667',raw(rounds[0],event[2][1]):'20000',
        f'r{rounds[1].pk}-override_{event[2][0].pk}':'on',f'r{rounds[1].pk}-normalized_{event[2][0].pk}':'0.5'})
    data.pop(f'r{rounds[0].pk}-override_{event[2][0].pk}')
    result=preview(client,data).json()
    assert not result['percentage'] and result['rows'][str(event[2][0].pk)]['total']=='0.83'
    assert post(client,data).status_code==200
    saved=next(row for row in standings(c,ch)[1] if row['team']==event[2][0])
    assert result['rows'][str(event[2][0].pk)]['total']==format(saved['total'],'.2f')
