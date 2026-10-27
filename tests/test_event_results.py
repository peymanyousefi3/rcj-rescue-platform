import pytest
from arena.models import Challenge,Round,Score,Team
from arena.recording_views import results_context
from arena.recordings import RoundScoresForm

pytestmark=pytest.mark.django_db


def test_each_event_has_own_rounds_scores_and_public_results(event,client):
    c,first,teams,users,staff=event
    main=Challenge.objects.create(competition=c,name='Main field',primary=True,expected_rounds=1)
    first.challenge=main;first.save()
    side=Challenge.objects.create(competition=c,name='Technical challenge',calculation='sum',score_source='raw')
    r=Round.objects.create(competition=c,challenge=side,number=1,name='Technical final',opens_at=first.opens_at,
        quarantine_at=first.quarantine_at,starts_at=first.starts_at,ends_at=first.ends_at)
    for t in teams:Score.objects.create(round=first,team=t,raw=999,normalized=1)
    client.force_login(staff)
    response=client.get(f'/control/?score_challenge={side.pk}')
    assert response.status_code==200
    assert {ch.pk for ch in response.context['score_challenges']}=={main.pk,side.pk}
    assert [entry['round'] for entry in response.context['result_entries']]==[r]
    form=RoundScoresForm(round_=r,matrix=True,prefix=f'r{r.pk}')
    data={'score_challenge':side.pk,'round_ids':str(r.pk)}
    data.update({form.add_prefix(k):'' if v is None else v for k,v in form.initial.items() if v is not False})
    data.update({f'r{r.pk}-raw_{teams[0].pk}':'25',f'r{r.pk}-raw_{teams[1].pk}':'50'})
    preview=client.post('/control/results/scores/preview/',data).json()
    assert preview['rows'][str(teams[0].pk)]['total']=='25.00'
    assert preview['rows'][str(teams[0].pk)]['rank'] is None
    saved=client.post('/control/results/scores/',data,HTTP_X_ASR_SCORES='1')
    assert saved.status_code==200,saved.content
    assert Score.objects.get(round=first,team=teams[0]).raw==999
    assert [entry['round'] for entry in results_context(c)['result_entries']]==[first]
    public=client.get('/results/');group=next(g for g in public.context['result_groups'] if g['challenge']==side)
    assert [item['round'] for item in group['rows'][0]['round_scores']]==[r]
    assert {row['total'] for row in group['rows']}=={25,50}
    assert b'Technical challenge' in public.content and b'Rankings not released' in public.content
    client.force_login(users[0]);assert b'Technical challenge' in client.get('/portal/results/').content
    side.archived_at=c.starts_at;side.save(update_fields=['archived_at'])
    client.force_login(staff);assert client.get(f'/control/?score_challenge={side.pk}').status_code==404


def test_new_round_shortcut_uses_selected_superteam_event_pairings(event,client):
    c,first,teams,users,staff=event
    ch=Challenge.objects.create(competition=c,name='SuperTeam relay',category='superteam')
    pair=Team.objects.create(competition=c,superteam_challenge=ch,code='PAIR',name='Existing pair',country='Canada')
    pair.members.set(teams)
    client.force_login(staff)
    page=client.get(f'/control/?editor=round&round_challenge={ch.pk}')
    form=page.context['form']
    assert str(form['challenge'].value())==str(ch.pk)
    assert form.instance.challenge==ch
    assert form.lineup_form.initial['teams']==[str(pair.pk)]
    assert form['number'].value()==1
    assert b'Add event' in client.get('/control/').content


def test_adding_event_from_results_opens_its_new_score_table(event,client):
    client.force_login(event[-1])
    data={'form':'challenge','_return':'results-recordings','name':'New event','category':'side','expected_rounds':1,'calculation':'sum','top_count':1,'score_source':'raw'}
    response=client.post('/control/',data,HTTP_X_ASR_EDITOR='1')
    ch=Challenge.objects.get(name='New event')
    assert response.json()['redirect']==f'/control/?score_challenge={ch.pk}#results-recordings'
    assert not ch.rankings_released


def test_admin_shows_main_and_superteam_tables_together_with_isolated_forms(event,client):
    c,first,teams,users,staff=event
    main=Challenge.objects.create(competition=c,name='Main competition',primary=True)
    first.challenge=main;first.save()
    relay=Challenge.objects.create(competition=c,name='SuperTeam',category='superteam',calculation='sum',score_source='raw')
    group=Team.objects.create(competition=c,name='Existing pair',code='PAIR-TABLE',country='Canada',superteam_challenge=relay)
    group.members.set(teams)
    r=Round.objects.create(competition=c,challenge=relay,number=1,opens_at=first.opens_at,quarantine_at=first.quarantine_at,starts_at=first.starts_at,ends_at=first.ends_at)
    Score.objects.create(round=first,team=teams[0],raw=75,normalized=1)
    client.force_login(staff);page=client.get('/control/')
    assert page.status_code==200
    tables=page.context['score_tables'];assert {t['score_challenge'].pk for t in tables}=={main.pk,relay.pk}
    assert page.content.count(b'data-score-grid')==2
    assert b'Open table' not in page.content and b'id="score-challenge"' not in page.content
    assert len({t['matrix_id'] for t in tables})==len({t['preview_id'] for t in tables})==2
    for table in tables:
        for row in table['score_rows']:
            for cell in row['cells']:
                assert cell['raw_field'].field.widget.attrs['form']==table['matrix_id']
                assert cell['remaining_field'].field.widget.attrs['form']==table['matrix_id']
    form=next(t for t in tables if t['score_challenge']==relay)['result_entries'][0]['score_form']
    data={'score_challenge':relay.pk,'round_ids':str(r.pk)}
    data.update({form.add_prefix(k):'' if v is None else v for k,v in form.initial.items() if v is not False})
    data[f'r{r.pk}-raw_{group.pk}']='50'
    assert client.post('/control/results/scores/',data,HTTP_X_ASR_SCORES='1').status_code==200
    assert Score.objects.get(round=r,team=group).raw==50
    assert Score.objects.get(round=first,team=teams[0]).raw==75
    assert all(t['score_preview']['rankings_released'] is False for t in tables)
