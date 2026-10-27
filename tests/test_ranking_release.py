"""Scores remain visible; ranks require explicit, reversible staff approval."""
import pytest
from django.test import Client
from arena.models import AuditEvent,Challenge,EmailDelivery,Score
from arena.recording_views import results_context
from arena.views import standings

pytestmark=pytest.mark.django_db


def complete(event):
    c,r,teams,users,staff=event
    ch=Challenge.objects.create(competition=c,name='Field rankings',category='main',primary=True,expected_rounds=1)
    r.challenge=ch;r.save(update_fields=['challenge'])
    for t,value in zip(teams,[75,100]):Score.objects.create(round=r,team=t,raw=value,normalized=value/100)
    return ch


def release(client,ch,enabled,previous=False):
    return client.post(f'/control/results/rankings/{ch.pk}/',{'released':'1' if enabled else '0','previous_state':'1' if previous else '0'})


def test_complete_scores_do_not_rank_until_staff_approves_and_can_be_withdrawn(event,client):
    ch=complete(event);c,r,teams,users,staff=event
    before=list(Score.objects.values())
    rows=standings(c,ch)[1]
    assert all(row['total'] is not None and row['rank'] is None and not row['tie'] for row in rows)
    assert [row['team'].name for row in rows]==sorted(t.name for t in teams)
    preview=results_context(c)['score_preview']
    assert not preview['rankings_released'] and all(v['total'] is not None and v['rank'] is None for v in preview['rows'].values())
    page=client.get('/results/')
    assert b'Rankings not released' in page.content and b'75.00' in page.content
    client.force_login(users[0]);page=client.get('/portal/results/')
    assert b'Rankings not released' in page.content and b'75.00' in page.content
    assert release(client,ch,True).status_code in [302,403]
    ch.refresh_from_db();assert not ch.rankings_released
    client.force_login(staff)
    assert release(client,ch,True).status_code==302
    ch.refresh_from_db();assert ch.rankings_released
    assert [v['rank'] for v in standings(c,ch)[1]]==[1,2]
    assert results_context(c)['score_preview']['rankings_released']
    assert b'Rankings released' in client.get('/results/').content
    # A stale administrator tab cannot overwrite a newer release decision.
    release(client,ch,False,previous=False);ch.refresh_from_db();assert ch.rankings_released
    assert release(client,ch,False,previous=True).status_code==302
    ch.refresh_from_db();assert not ch.rankings_released
    assert all(v['rank'] is None for v in standings(c,ch)[1])
    assert list(Score.objects.values())==before
    assert set(AuditEvent.objects.filter(action__startswith='rankings.').values_list('action',flat=True))=={'rankings.released','rankings.withdrawn'}
    assert not EmailDelivery.objects.exists()


def test_release_requires_complete_scores_csrf_and_valid_competition(event,client):
    ch=complete(event);c,r,teams,users,staff=event
    secured=Client(enforce_csrf_checks=True);secured.force_login(staff)
    assert release(secured,ch,True).status_code==403
    client.force_login(staff)
    Score.objects.filter(team=teams[0]).delete()
    release(client,ch,True);ch.refresh_from_db();assert not ch.rankings_released
    assert client.post(f'/control/results/rankings/{ch.pk}/',{'released':'yes','previous_state':'0'}).status_code==400
    assert client.get(f'/control/results/rankings/{ch.pk}/').status_code==405
    ch.archived_at=c.starts_at;ch.save(update_fields=['archived_at'])
    assert release(client,ch,True).status_code==404
