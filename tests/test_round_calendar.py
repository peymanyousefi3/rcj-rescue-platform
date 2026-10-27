import json
from datetime import timedelta
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone
from arena.models import Asset, Programme, Team
from arena.scheduling import calendar_entries, lineup_data, revision

pytestmark=pytest.mark.django_db

def stamp(value):
    return timezone.localtime(value).strftime('%Y-%m-%dT%H:%M:%S')

def runs_for(event):
    c,r,teams,users,staff=event
    return [Programme.objects.create(competition=c,round=r,team=t,title=str(r),source_key=f'run:{i}',
        starts_at=r.starts_at+timedelta(minutes=i*15),ends_at=r.starts_at+timedelta(minutes=(i+1)*15)) for i,t in enumerate(teams)]

def test_lineup_reorders_existing_runs_and_derives_public_times(client,event):
    c,r,teams,users,staff=event;runs=runs_for(event);client.force_login(staff)
    rows=list(reversed(lineup_data(r)))
    data={'form':'lineup','record_id':r.pk,'revision':revision(r),'lineup':json.dumps(rows)}
    assert client.post('/control/',data).status_code==302
    assert list(Programme.objects.filter(round=r).values_list('pk',flat=True))==[runs[1].pk,runs[0].pk]
    runs[1].refresh_from_db();runs[0].refresh_from_db()
    assert runs[1].starts_at==r.starts_at and runs[0].starts_at==r.starts_at+timedelta(minutes=15)
    entries=calendar_entries(c);assert len([e for e in entries if e['extendedProps']['kind']=='round'])==1
    assert not any(e['id']==f'event:{run.pk}' for run in runs for e in entries)
    context=client.get('/').context
    blocks=[block for day in context['programme_days'] for block in day['blocks'] if block['kind']=='round']
    assert [run.pk for run in blocks[0]['runs']]==[runs[1].pk,runs[0].pk]
    # A stale second save cannot overwrite the changed lineup.
    assert client.post('/control/',data).status_code==200
    assert 'changed in another window' in client.post('/control/',data).content.decode()

def test_lineup_rejects_foreign_duplicate_and_overflow_without_changes(client,event):
    c,r,teams,users,staff=event;runs=runs_for(event);client.force_login(staff)
    before=list(Programme.objects.values());base=lineup_data(r)
    for rows in [[base[0],base[0]],[{**base[0],'duration':10081}],[{**base[0],'team':'not-a-team'}],[{**base[0],'id':999999}]]:
        response=client.post('/control/',{'form':'lineup','record_id':r.pk,'revision':revision(r),'lineup':json.dumps(rows)})
        assert response.status_code==200
        assert list(Programme.objects.values())==before
    client.force_login(users[0]);assert client.post('/control/',{'form':'lineup','record_id':r.pk}).status_code==302
    assert list(Programme.objects.values())==before

def test_calendar_move_is_atomic_preserves_deadlines_and_rejects_stale(client,event):
    c,r,teams,users,staff=event;runs=runs_for(event);client.force_login(staff)
    start,end,deadline,opening=r.starts_at,r.ends_at,r.quarantine_at,r.opens_at
    data={'kind':'round','id':r.pk,'revision':revision(r),'starts_at':stamp(start+timedelta(days=1)), 'ends_at':stamp(end+timedelta(days=1))}
    response=client.post('/control/calendar/move/',data);assert response.status_code==200
    r.refresh_from_db();assert r.starts_at==start.replace(microsecond=0)+timedelta(days=1) and r.quarantine_at==deadline and r.opens_at==opening
    for run,old in zip(runs,[start,start+timedelta(minutes=15)]):
        run.refresh_from_db();assert run.starts_at==old.replace(microsecond=0)+timedelta(days=1)
    assert client.post('/control/calendar/move/',data).status_code==409
    before=list(Programme.objects.values());data.update(revision=revision(r),ends_at=stamp(r.starts_at+timedelta(minutes=10)))
    assert client.post('/control/calendar/move/',data).status_code==400
    assert list(Programme.objects.values())==before
    r.refresh_from_db();assert r.ends_at==r.starts_at+timedelta(minutes=30)
    c.refresh_from_db();assert not c.workbook_enabled

def test_calendar_permissions_csrf_and_no_child_run_edits(client,event):
    c,r,teams,users,staff=event;run=runs_for(event)[0]
    data={'kind':'event','id':run.pk,'revision':revision(run),'starts_at':stamp(run.starts_at),'ends_at':stamp(run.ends_at)}
    assert client.post('/control/calendar/move/',data).status_code in [302,403]
    client.force_login(users[0]);assert client.post('/control/calendar/move/',data).status_code==302
    client.force_login(staff);assert client.post('/control/calendar/move/',data).status_code==400
    secured=Client(enforce_csrf_checks=True);secured.force_login(staff)
    assert secured.post('/control/calendar/move/',data).status_code==403
    assert client.get('/control/calendar/move/').status_code==405

def test_round_form_moves_runs_and_empty_round_is_visible(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    assert f'data-programme-round=' in client.get('/').content.decode()
    runs=runs_for(event);start=r.starts_at
    response=client.post('/control/',{'form':'round','record_id':r.pk,'number':r.number,'starts_at':stamp(start+timedelta(hours=2)),
        'end_mode':'duration','duration_minutes':60})
    assert response.status_code==302
    runs[0].refresh_from_db();assert runs[0].starts_at==start.replace(microsecond=0)+timedelta(hours=2)
    assert client.get(f'/control/?event={runs[0].pk}').url==f'/control/?editor=round&round={r.pk}'

def test_removing_lineup_team_keeps_recoverable_original_record(client,event):
    c,r,teams,users,staff=event;runs=runs_for(event);client.force_login(staff)
    assert client.post('/control/',{'form':'lineup','record_id':r.pk,'revision':revision(r),'lineup':json.dumps(lineup_data(r)[:1])}).status_code==302
    runs[1].refresh_from_db();assert runs[1].archived_at is not None
    assert Programme.objects.filter(pk=runs[1].pk).exists()

def test_file_audience_uses_one_record_with_pending_public_access(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    response=client.post('/control/',{'form':'managed-upload','destination':'organizer','audience':'public_selected','targets':[teams[0].pk],
        'files':[SimpleUploadedFile('instructions.xyz',b'Organizer instructions')]})
    assert response.status_code==302
    shared=Asset.objects.get()
    assert shared.public_copy and not shared.public_approved
    assert list(shared.targets.all())==[teams[0]] and not shared.general
    shared.scan_status='clean';shared.save()
    client.force_login(users[0]);assert client.get(f'/files/{shared.pk}/').status_code==200
    client.force_login(users[1]);assert client.get(f'/files/{shared.pk}/').status_code==404
    client.logout();assert client.get(f'/files/{shared.pk}/').status_code==404


def test_calendar_styles_keep_strict_csp_and_nonce(client,event):
    client.force_login(event[-1]);response=client.get('/control/')
    assert "script-src 'self';" in response['Content-Security-Policy']
    assert "'unsafe-inline'" not in response['Content-Security-Policy']
    nonce=response.wsgi_request.csp_nonce
    assert f"style-src 'self' 'nonce-{nonce}'" in response['Content-Security-Policy']
    assert f'name="csp-nonce" content="{nonce}"' in response.content.decode()

def test_lineup_revision_after_calendar_move_can_be_used_again(client,event):
    c,r,teams,users,staff=event;runs_for(event);client.force_login(staff)
    data={'kind':'round','id':r.pk,'revision':revision(r),'starts_at':stamp(r.starts_at+timedelta(hours=1)), 'ends_at':stamp(r.ends_at+timedelta(hours=1))}
    response=client.post('/control/calendar/move/',data);assert response.status_code==200
    r.refresh_from_db();assert response.json()['revision']==revision(r)
    data.update(revision=response.json()['revision'],starts_at=stamp(r.starts_at+timedelta(hours=1)),ends_at=stamp(r.ends_at+timedelta(hours=1)))
    assert client.post('/control/calendar/move/',data).status_code==200

def test_round_editor_saves_timing_and_lineup_together_or_neither(client,event):
    c,r,teams,users,staff=event;runs=runs_for(event);client.force_login(staff)
    rows=list(reversed(lineup_data(r)));old_start=r.starts_at
    data={'form':'round','record_id':r.pk,'number':r.number,'revision':revision(r),'starts_at':stamp(old_start+timedelta(hours=2)),
        'end_mode':'duration','duration_minutes':45,'lineup-revision':revision(r),'lineup-lineup':json.dumps(rows)}
    assert client.post('/control/',data).status_code==302
    r.refresh_from_db();runs[1].refresh_from_db()
    assert r.duration_minutes==30 and runs[1].starts_at==r.starts_at
    before=list(Programme.objects.values());current_start=r.starts_at
    data.update(revision=revision(r),starts_at=stamp(r.starts_at+timedelta(hours=1)),duration_minutes=10)
    data['lineup-revision']=revision(r)
    data['lineup-lineup']=json.dumps([{**rows[0],'duration':0}])
    assert client.post('/control/',data).status_code==200
    r.refresh_from_db();assert r.starts_at==current_start and list(Programme.objects.values())==before
