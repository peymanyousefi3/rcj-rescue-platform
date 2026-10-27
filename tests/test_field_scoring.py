from decimal import Decimal
from fractions import Fraction
import importlib
import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.management import call_command
from unittest.mock import patch
from arena.models import Challenge,Round,Score
from arena.control_forms import ChallengeForm
from arena.recordings import ResultForm
from arena.views import standings

pytestmark=pytest.mark.django_db


def field(event,values,discard=0,opponents=None):
    c,first,teams,*_=event
    challenge=Challenge.objects.create(competition=c,name='Field',category='main',primary=True,
        expected_rounds=len(values),discard_count=discard,rankings_released=True)
    first.challenge=challenge;first.save()
    rounds=[first]
    for number in range(2,len(values)+1):
        rounds.append(Round.objects.create(competition=c,challenge=challenge,number=number,
            opens_at=first.opens_at,quarantine_at=first.quarantine_at,starts_at=first.starts_at,ends_at=first.ends_at))
    for i,(round_,value) in enumerate(zip(rounds,values)):
        Score.objects.create(round=round_,team=teams[0],raw=Decimal(value),normalized=Decimal('.1234'),normalized_override=True)
        Score.objects.create(round=round_,team=teams[1],raw=Decimal(opponents[i] if opponents else '100'))
    return c,challenge,rounds


def test_example_discards_normalized_not_raw_and_keeps_challenges_separate(event,client):
    c,ch,rounds=field(event,['75','100','400','80'],1,['100','100','1000','100'])
    side=Challenge.objects.create(competition=c,name='SuperTeam',category='superteam',calculation='sum',score_source='raw')
    extra=Round.objects.create(competition=c,challenge=side,number=1,opens_at=rounds[0].opens_at,
        quarantine_at=rounds[0].quarantine_at,starts_at=rounds[0].starts_at,ends_at=rounds[0].ends_at)
    Score.objects.create(round=extra,team=event[2][0],raw=9999)
    rows=standings(c,ch)[1]
    row=next(row for row in rows if row['team']==event[2][0])
    other=next(row for row in rows if row['team']==event[2][1])
    # Each team's own normalized scores choose its discard, independently.
    assert other['dropped']==[1] and other['total']==100
    assert row['exact']==Fraction(85) and row['total']==85 and row['dropped']==[3]
    assert next(row for row in standings(c)[1] if row['team']==event[2][0])['total']==85
    assert row['cells'][2].discarded and row['cells'][2].raw==400
    page=client.get('/results/').content.decode()
    assert '85.00' in page and 'Discarded' in page and 'Final score (%)' in page
    for round_ in rounds:
        assert f'colspan="2" id="round-{ch.pk}-{round_.pk}"' in page
        assert f'id="raw-{ch.pk}-{round_.pk}"' in page and f'id="normalized-{ch.pk}-{round_.pk}"' in page
    assert '400.00' in page and '0.4000' in page and 'results-matrix' in page
    assert 'For each team separately' in page and 'remaining normalized scores' in page
    assert '60%' not in page


def test_full_precision_ranking_and_exact_ties(event):
    c,ch,rounds=field(event,['999999999.9998'],opponents=['999999999.9999'])
    rows=standings(c,ch)[1]
    assert [row['rank'] for row in rows]==[1,2] and not any(row['tie'] for row in rows)
    assert rows[0]['total'].quantize(Decimal('.01'))==rows[1]['total'].quantize(Decimal('.01'))
    Score.objects.filter(round=rounds[0],team=event[2][0]).update(raw=Decimal('999999999.9999'))
    rows=standings(c,ch)[1]
    assert [row['rank'] for row in rows]==[1,1] and all(row['tie'] for row in rows)


def test_only_explicit_retained_score_tie_break_resolves_equal_finals(event):
    c,ch,rounds=field(event,['100','50'],opponents=['50','100'])
    # Add a third score so equal means have different retained score distributions.
    Score.objects.filter(round=rounds[1],team=event[2][0]).update(raw=75)
    Score.objects.filter(round=rounds[0],team=event[2][1]).update(raw=100)
    Score.objects.filter(round=rounds[1],team=event[2][1]).update(raw=75)
    # Both currently 100%, so even an explicit policy must preserve a true tie.
    ch.tie_break='retained';ch.save()
    assert all(row['tie'] for row in standings(c,ch)[1])
    # A third team supplies round maxima: [1,.5] vs [.75,.75] => both 75%.
    from arena.models import Team
    third=Team.objects.create(competition=c,code='MAX',name='Maxima',country='Canada')
    for round_ in rounds: Score.objects.create(round=round_,team=third,raw=100)
    for team,values in zip(event[2],[['100','50'],['75','75']]):
        for round_,value in zip(rounds,values): Score.objects.filter(round=round_,team=team).update(raw=value)
    ch.tie_break='none';ch.save()
    rows=standings(c,ch)[1];assert [row['rank'] for row in rows]==[1,2,2]
    ch.tie_break='retained';ch.save()
    rows=standings(c,ch)[1];assert [row['rank'] for row in rows]==[1,2,3]
    assert rows[1]['team']==event[2][0]


def test_zero_round_requires_decision_and_discard_cannot_remove_every_round(event):
    c,ch,rounds=field(event,['0','75'],1,['0','100'])
    rows=standings(c,ch)[1]
    assert all(row['total'] is None and 'decision required' in row['issue'] for row in rows)
    rounds[0].zero_score_policy='zero';rounds[0].save()
    rows=standings(c,ch)[1]
    assert sorted(row['total'] for row in rows)==[75,100] and all(row['dropped']==[1] for row in rows)
    rounds[0].zero_score_policy='exclude';rounds[0].save()
    rows=standings(c,ch)[1]
    assert all(row['total'] is None and 'one round must remain' in row['issue'] for row in rows)
    ch.discard_count=0;ch.save()
    rows=standings(c,ch)[1]
    assert sorted(row['total'] for row in rows)==[75,100] and all(row['cells'][0].excluded for row in rows)
    Score.objects.filter(round=rounds[1],team=event[2][1]).update(raw=None)
    assert all(row['total'] is None for row in standings(c,ch)[1])


def test_configuration_and_upgrade_preserve_results_and_stop_sheet_sync(event):
    c,ch,rounds=field(event,['75','80'])
    ch.calculation='best';ch.top_count=1;ch.save()
    before=list(Score.objects.values('id','raw','normalized','normalized_override'))
    importlib.import_module('arena.migrations.0017_field_average_after_discards').use_field_average(apps,None)
    c.refresh_from_db();ch.refresh_from_db()
    assert not c.workbook_enabled and ch.calculation=='trimmed_mean' and ch.discard_count==1 and ch.tie_break=='none'
    assert before==list(Score.objects.values('id','raw','normalized','normalized_override'))
    with patch('arena.management.commands.sync_workbook.requests.get') as get:
        call_command('sync_workbook')
        get.assert_not_called()
    form=ChallengeForm({'name':'Invalid','category':'main','expected_rounds':2,'calculation':'trimmed_mean',
        'discard_count':2,'tie_break':'none','top_count':1,'score_source':'raw'},competition=c)
    assert not form.is_valid() and 'discard_count' in form.errors
    form=ResultForm({'raw':'-1'},round_=rounds[0],team=event[2][0])
    assert not form.is_valid() and 'raw' in form.errors
    ch.discard_count=2
    with pytest.raises(ValidationError): ch.full_clean()
