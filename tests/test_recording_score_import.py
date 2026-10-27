import json
from decimal import Decimal

import pytest
from arena.models import Score,RunRecording,AuditEvent
from arena.recordings import result_revision
from test_results_recordings import export_zip
from test_video_playback import video

pytestmark=pytest.mark.django_db
META={'final_score':215.375,'field_score':180.1,'exit_bonus':20,'map_bonus':15.275,
      'elapsed_seconds':454,'max_seconds':480,'remaining_seconds':26}


def upload(client,event,metadata=META,**extra):
    _,r,teams,_,staff=event;client.force_login(staff)
    return client.post(f'/control/results/{r.pk}/{teams[0].pk}/?recording=1&inline=1',
        {'revision':result_revision(r,teams[0]),'files':[export_zip(**{'run/match-result.json':json.dumps(metadata).encode()})],**extra},
        HTTP_X_ASR_EDITOR='1')


@pytest.mark.parametrize('with_video',[False,True])
def test_upload_imports_empty_fields_and_updates_table_from_final_total(client,event,with_video):
    response=upload(client,event,**({'video':video()} if with_video else {}))
    assert response.status_code==200,response.content
    score=Score.objects.get();assert score.raw==Decimal('215.375') and score.elapsed_seconds==454
    assert score.remaining_seconds==26
    data=response.json()['recording_update']['scores'];team=str(event[2][0].pk)
    assert data['raw'][team]=='215.375' and data['elapsed_seconds'][team]==454
    assert data['normalized'][team]=='1.0000'
    assert AuditEvent.objects.filter(action='result.updated').latest('occurred_at').detail['imported']==['score','time']
    event[0].refresh_from_db();assert not event[0].workbook_enabled


@pytest.mark.parametrize('raw,elapsed,expected_raw,expected_elapsed',[
    (0,0,0,0), (42,123,42,123), (None,123,215.375,123), (42,None,42,454),
])
def test_import_never_overwrites_independent_manual_fields_including_zero(client,event,raw,elapsed,expected_raw,expected_elapsed):
    Score.objects.create(round=event[1],team=event[2][0],raw=raw,elapsed_seconds=elapsed)
    assert upload(client,event).status_code==200
    score=Score.objects.get();assert score.raw==Decimal(str(expected_raw)) and score.elapsed_seconds==expected_elapsed


def test_video_upload_can_fill_blanks_from_existing_package_without_overwriting_drafts(client,event):
    assert upload(client,event,skip_score_import='on',skip_time_import='on').status_code==200
    assert not Score.objects.exists()
    _,r,teams,_,staff=event
    response=client.post(f'/control/results/{r.pk}/{teams[0].pk}/?recording=1',
        {'revision':result_revision(r,teams[0]),'video':video()})
    assert response.status_code==302
    score=Score.objects.get();assert score.raw==Decimal('215.375') and score.elapsed_seconds==454
    assert RunRecording.objects.get(current=True).video_key


@pytest.mark.parametrize('metadata,raw,elapsed',[
    ({'final_score':0,'elapsed_seconds':0},Decimal('0'),0),
    ({'final_score':12.345678,'max_seconds':480,'remaining_seconds':60},Decimal('12.3457'),420),
    ({'final_score':'NaN','elapsed_seconds':481},None,None),
    ({'final_score':10000000000,'remaining_seconds':20},None,None),
    ({'field_score':180,'exit_bonus':20,'map_bonus':15},None,None),
    ({},None,None),
])
def test_import_requires_usable_final_metadata_and_never_infers_scores_or_video_duration(client,event,metadata,raw,elapsed):
    assert upload(client,event,metadata=metadata).status_code==200
    score=Score.objects.first()
    assert (score.raw if score else None)==raw and (score.elapsed_seconds if score else None)==elapsed


def test_manual_result_form_values_take_priority_over_uploaded_metadata(client,event):
    _,r,teams,_,staff=event;client.force_login(staff)
    response=client.post(f'/control/results/{r.pk}/{teams[0].pk}/',
        {'revision':result_revision(r,teams[0]),'raw':'0','remaining_time':'8:00',
         'files':[export_zip(**{'run/match-result.json':json.dumps(META).encode()})]})
    assert response.status_code==302
    score=Score.objects.get();assert score.raw==0 and score.elapsed_seconds==0
