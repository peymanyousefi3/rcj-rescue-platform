import json
import pytest
from django.test import Client
from django.urls import reverse
from arena.models import Complaint,RunRecording
from arena.recordings import match_result
from arena.workspaces import ComplaintForm
from test_results_recordings import export_zip,post_result

pytestmark=pytest.mark.django_db

def recording(client,event,events=None):
    client.force_login(event[-1])
    metadata={'final_score':125,'events':events if events is not None else [
        {'timestamp':'00:12','text':'Original event +60','playback_time_ms':16},
        {'timestamp':'00:20','text':'Second event','playback_time_ms':16}]}
    assert post_result(client,event,export_zip(**{'run/match-result.json':json.dumps(metadata).encode()})).status_code==302
    return RunRecording.objects.get()

def test_event_metadata_and_complaint_link_are_authorized(client,event):
    item=recording(client,event)
    url=reverse('recording-player',args=[item.pk])
    response=client.get(url).json();assert response['complaint_url'] is None
    assert response['result']['events'][1]['text']=='Second event'
    client.force_login(event[3][0]);response=client.get(url).json()
    assert response['complaint_url']=='/portal/complaints/'
    client.force_login(event[3][1]);assert client.get(url).status_code==404
    client.logout();assert client.get(url).status_code==404

def test_complaint_preserves_recording_position_and_is_private(client,event):
    item=recording(client,event);client.force_login(event[3][0])
    page=client.get('/portal/complaints/',{'recording':item.pk,'at':'00:00'})
    assert page.status_code==200 and str(item.pk).encode() in page.content
    assert b'Position ms' not in page.content
    response=client.post('/portal/complaints/',{'subject':'Review an event','message':'Please check this moment','recording':item.pk,'playback_time':'00:00'})
    assert response.status_code==302
    complaint=Complaint.objects.get();assert complaint.recording==item and complaint.playback_time_ms==0
    assert complaint.playback_timestamp=='00:00'
    own=client.get('/portal/complaints/');assert b'Open related replay at 00:00' in own.content
    review=reverse('complaint-review',args=[complaint.pk])
    client.force_login(event[3][1]);assert b'Review an event' not in client.get('/portal/complaints/').content
    assert client.get(review).status_code in (302,403)
    client.force_login(event[-1]);page=client.get(review);assert page.status_code==200 and b'data-start-ms="0"' in page.content
    assert b'data-replay-dialog' in page.content
    client.logout();assert client.get(review).status_code in (302,403)

@pytest.mark.parametrize('position',['00:01','-01:00','01:99','NaN','1.5','9999999:00'])
def test_invalid_or_out_of_range_positions_cannot_save(client,event,position):
    item=recording(client,event);client.force_login(event[3][0])
    response=client.post('/portal/complaints/',{'subject':'Concern','message':'Check','recording':item.pk,'playback_time':position})
    assert response.status_code==200 and not Complaint.objects.exists()

def test_forged_other_team_recording_is_rejected(client,event):
    item=recording(client,event);client.force_login(event[3][1])
    response=client.post('/portal/complaints/',{'subject':'Concern','message':'Check','recording':item.pk,'playback_time':'00:00'})
    assert response.status_code==200 and not Complaint.objects.exists()

def test_general_complaint_still_works(client,event):
    client.force_login(event[3][0])
    assert client.post('/portal/complaints/',{'subject':'General','message':'No recording needed'}).status_code==302
    item=Complaint.objects.get();assert item.recording is None and item.playback_time_ms is None

def test_events_are_stable_and_missing_history_is_not_invented(client,event):
    item=recording(client,event,[{'timestamp':'00:20','text':'later','playback_time_ms':20},{'timestamp':'00:10','text':'first','playback_time_ms':10},{'timestamp':'00:11','text':'same position','playback_time_ms':10}])
    assert [e['text'] for e in match_result(item)['events']]==['first','same position','later']
    from django.core.files.storage import default_storage
    path=f'recordings/{item.pk}/run/match-result.json'
    with default_storage.open(path,'wb') as f:f.write(b'{"last_event":"00:20 not history"}')
    result=match_result(item);assert not result['event_history_available'] and result['events']==[]


def test_precise_link_position_survives_seconds_display(client,event):
    item=recording(client,event);client.force_login(event[3][0])
    response=client.post('/portal/complaints/',{'subject':'Precise event','message':'Preserve actual playback time','recording':item.pk,'playback_time':'00:00','position_ms':'16'})
    assert response.status_code==302 and Complaint.objects.get().playback_time_ms==16


def test_edited_visible_time_does_not_reuse_old_hidden_position(client,event):
    item=recording(client,event);client.force_login(event[3][0])
    response=client.post('/portal/complaints/',{'subject':'Edited event','message':'Changed position','recording':item.pk,'playback_time':'00:00','position_ms':'1500'})
    assert response.status_code==302 and Complaint.objects.get().playback_time_ms==0


def test_complaint_keeps_private_replay_version_reviewable(client,event):
    item=recording(client,event);client.force_login(event[3][0])
    assert client.post('/portal/complaints/',{'subject':'Keep evidence','message':'Review original recording','recording':item.pk,'playback_time':'00:00'}).status_code==302
    item.current=False;item.save(update_fields=['current'])
    url=reverse('recording-player',args=[item.pk]);assert client.get(url).status_code==200
    client.force_login(event[3][1]);assert client.get(url).status_code==404
    client.logout();assert client.get(url).status_code==404
    from arena.models import EmailDelivery
    assert not EmailDelivery.objects.exists()
