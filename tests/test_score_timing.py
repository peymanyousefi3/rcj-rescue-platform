from decimal import Decimal
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from arena.models import AuditEvent, Challenge, Score
from arena.recordings import result_revision
from arena.timing import RemainingTimeField
from arena.views import standings
from test_field_scoring import field
from test_score_matrix import add_round, matrix_data, post, raw

pytestmark = pytest.mark.django_db


def clock(round_, team):
    return f'r{round_.pk}-remaining_{team.pk}'


@pytest.mark.parametrize('value,seconds', [('2:30',150),('150',150),('8:00',480),('480',480),
    ('0:00',0),('0',0),('7:59',479),('08:00',480),('',None)])
def test_remaining_formats_and_boundaries(value, seconds):
    assert RemainingTimeField().clean(value) == seconds


@pytest.mark.parametrize('value', ['8:01','481','-1','2:60','1.5','NaN','Infinity','1:02:03','1e2'])
def test_invalid_clocks(value):
    with pytest.raises(ValidationError):
        RemainingTimeField().clean(value)


def test_matrix_converts_saves_and_audits_time_only_edits(event, client):
    c, r, teams, _, staff = event
    client.force_login(staff)
    data = matrix_data(c)
    data.update({raw(r,teams[0]):'75',raw(r,teams[1]):'100',clock(r,teams[0]):'2:30',clock(r,teams[1]):'480'})
    response = post(client,data)
    assert response.status_code == 200, response.content
    score = Score.objects.get(round=r,team=teams[0])
    assert score.elapsed_seconds == 330 and score.elapsed_time == '5:30'
    assert score.normalized == Decimal('.75')
    assert Score.objects.get(round=r,team=teams[1]).elapsed_seconds == 0
    assert response.json()['rounds'][str(r.pk)]['elapsed_seconds'][str(teams[0].pk)] == 330
    count = AuditEvent.objects.filter(action='scores.updated').count()
    data = matrix_data(c); data[clock(r,teams[0])] = '0:00'
    assert post(client,data).status_code == 200
    score.refresh_from_db(); assert score.elapsed_seconds == 480
    assert AuditEvent.objects.filter(action='scores.updated').count() == count+1
    html = client.get('/control/').content.decode()
    assert 'Elapsed <output' in html and '>8:00</output>' in html


def test_blank_clears_and_legacy_score_only_posts_preserve_times(event, client):
    c, r, teams, _, staff = event
    score = Score.objects.create(round=r,team=teams[0],raw=75,elapsed_seconds=330)
    client.force_login(staff)
    data = matrix_data(c); data.pop(clock(r,teams[0])); data[raw(r,teams[0])] = '80'
    assert post(client,data).status_code == 200
    score.refresh_from_db(); assert score.raw == 80 and score.elapsed_seconds == 330
    data = matrix_data(c); data[clock(r,teams[0])] = ''
    assert post(client,data).status_code == 200
    score.refresh_from_db(); assert score.raw == 80 and score.elapsed_seconds is None


def test_bad_time_rolls_back_all_scores_and_stale_time_edits_are_rejected(event, client):
    c, r, teams, _, staff = event
    later = add_round(c,r,2)
    score = Score.objects.create(round=r,team=teams[0],raw=75,elapsed_seconds=330)
    client.force_login(staff)
    before = list(Score.objects.values())
    data = matrix_data(c)
    data.update({raw(r,teams[0]):'85',clock(r,teams[0]):'1:00',clock(later,teams[1]):'8:01'})
    response = post(client,data)
    assert response.status_code == 400 and clock(later,teams[1]) in response.json()['errors']
    assert list(Score.objects.values()) == before
    assert not AuditEvent.objects.filter(action='scores.updated').exists()
    stale, revision = matrix_data(c), result_revision(r,teams[0])
    Score.objects.filter(pk=score.pk).update(elapsed_seconds=400)
    assert post(client,stale).status_code == 409
    response = client.post(f'/control/results/{r.pk}/{teams[0].pk}/',
        {'revision':revision,'raw':'75','remaining_time':'1:00'})
    assert response.status_code == 200 and b'changed in another window' in response.content
    score.refresh_from_db(); assert score.elapsed_seconds == 400


def test_result_editor_converts_time_and_recording_only_editor_preserves_it(event, client):
    _, r, teams, _, staff = event
    client.force_login(staff)
    url = f'/control/results/{r.pk}/{teams[0].pk}/'
    data = {'revision':result_revision(r,teams[0]),'raw':'75','remaining_time':'2:30'}
    assert client.post(url,data).status_code == 302
    score = Score.objects.get(round=r,team=teams[0]); assert score.elapsed_seconds == 330
    data.update(revision=result_revision(r,teams[0]),remaining_time='0:00')
    assert client.post(url+'?recording=1',data).status_code == 302
    score.refresh_from_db(); assert score.elapsed_seconds == 330
    data.pop('remaining_time'); data.update(revision=result_revision(r,teams[0]),raw='80')
    assert client.post(url,data).status_code == 302
    score.refresh_from_db(); assert score.raw == 80 and score.elapsed_seconds == 330


def test_public_time_total_precedes_final_score_and_round_clocks_stay_private(event, client):
    c, ch, rounds = field(event,['75','100'],1)
    team, other = event[2]
    for r,seconds in zip(rounds,[330,480]):
        Score.objects.filter(round=r,team=team).update(elapsed_seconds=seconds)
        Score.objects.filter(round=r,team=other).update(elapsed_seconds=0)
    side = Challenge.objects.create(competition=c,name='Side',calculation='sum',score_source='raw')
    extra = add_round(c,rounds[0],1,side)
    Score.objects.create(round=extra,team=team,raw=100,elapsed_seconds=99)
    archived = add_round(c,rounds[0],3,ch)
    from django.utils import timezone
    archived.archived_at=timezone.now(); archived.save()
    Score.objects.create(round=archived,team=team,raw=100,elapsed_seconds=77)
    rows = {row['team'].pk:row for row in standings(c,ch)[1]}
    assert rows[team.pk]['total_time_seconds'] == 810  # Includes the discarded score's run.
    assert rows[other.pk]['total_time_seconds'] == 0
    assert rows[team.pk]['dropped'] and rows[team.pk]['total'] == 100
    for url in ['/results/']:
        html = client.get(url).content.decode()
        assert html.index('Total time (s)</th>') < html.index('Final score (%)</th>')
        assert html.index('class="score-total-time">810</td>') < html.index('<td class="score-final">')
        assert 'class="score-total-time">810</td>' in html
        assert 'class="score-total-time">0</td>' in html
        assert 'data-remaining-time' not in html and 'data-elapsed-time' not in html
        assert 'team-total-time' in html


def test_unknown_and_partial_times_and_database_limits(event):
    c, r, teams, *_ = event
    score = Score.objects.create(round=r,team=teams[0],raw=75)
    assert all(row['total_time_seconds'] is None for row in standings(c)[1])
    score.elapsed_seconds=123; score.save()
    later = add_round(c,r,2); Score.objects.create(round=later,team=teams[0],raw=100)
    assert next(row for row in standings(c)[1] if row['team']==teams[0])['total_time_seconds'] == 123
    for value in [-1,481]:
        with pytest.raises(IntegrityError), transaction.atomic():
            Score.objects.filter(pk=score.pk).update(elapsed_seconds=value)


def test_results_without_challenges_also_show_total_time(event, client):
    _, r, teams, *_ = event
    Score.objects.create(round=r,team=teams[0],raw=75,elapsed_seconds=330)
    html=client.get('/results/').content.decode()
    assert '<th class="score-total-time">Total time (s)</th>' in html
    assert html.index('Total time (s)</th>') < html.index('<th>Total</th>')
    assert 'class="score-total-time">330</td>' in html


def test_system_admin_converts_remaining_time(event):
    from arena.admin import ScoreAdminForm
    _, r, teams, *_ = event
    form = ScoreAdminForm({'team':str(teams[0].pk),'round':str(r.pk),'raw':'75','normalized':'','remaining_time':'2:30'})
    assert form.is_valid(), form.errors
    assert form.save().elapsed_seconds == 330


def test_superteam_clocks_save_in_the_selected_challenge_without_changing_individual_scores(event, client):
    from arena.recordings import RoundScoresForm
    from test_superteams_complaints import sample
    c, r, teams, users, staff = event
    challenge, group, _, _ = sample(event)
    individual = Score.objects.create(round=r, team=teams[0], raw=50, elapsed_seconds=123)
    paired_round = add_round(c, r, 1, challenge)
    form = RoundScoresForm(round_=paired_round, matrix=True, prefix=f'r{paired_round.pk}')
    data = {'round_ids':str(paired_round.pk), 'score_challenge':str(challenge.pk)}
    data.update({form.add_prefix(name):'' if value is None else value for name,value in form.initial.items() if value is not False})
    data.update({raw(paired_round,group):'75', clock(paired_round,group):'2:30'})
    client.force_login(staff)
    assert post(client,data).status_code == 200
    assert Score.objects.get(round=paired_round,team=group).elapsed_seconds == 330
    individual.refresh_from_db()
    assert individual.raw == 50 and individual.elapsed_seconds == 123
    assert standings(c,challenge)[1][0]['total_time_seconds'] == 330
    page = client.get(f'/control/?score_challenge={challenge.pk}')
    assert [row['team'] for row in page.context['score_rows']] == [group]
    assert page.context['score_rows'][0]['cells'][0]['remaining_field'].value() == '2:30'
    client.force_login(users[0])
    html = client.get(f'/portal/superteams/{group.pk}/results/').content.decode()
    assert 'class="score-total-time">330</td>' in html and 'data-remaining-time' not in html
