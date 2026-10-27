import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from arena.models import RunRecording,Round
from arena.recordings import ResultForm,result_revision,save_result
from test_results_recordings import export_zip,post_result
from test_video_playback import video

pytestmark=pytest.mark.django_db


@pytest.mark.parametrize('kind',['webots','video'])
def test_completed_round_can_upload_and_publish_before_scheduled_end_and_revoke_immediately(client,event,kind):
    _,r,teams,users,staff=event
    r.completed=True;r.save();assert r.ends_at>timezone.now()
    client.force_login(staff)
    response=post_result(client,event,export_zip() if kind=='webots' else None,
        **({'video':video()} if kind=='video' else {}),published='on')
    assert response.status_code==302,response.content
    recording=RunRecording.objects.get();assert recording.public_open
    endpoint=f'/recordings/{recording.pk}/player/'
    client.logout();response=client.get(endpoint);assert response.status_code==200
    url=response.json()['url'];assert client.get(url).status_code==200
    assert f'data-replay="{endpoint}"'.encode() in client.get('/results/').content
    r.completed=False;r.save()
    assert client.get(endpoint).status_code==404 and client.get(url).status_code==404
    client.force_login(users[0]);assert client.get(endpoint).status_code==200
    client.force_login(users[1]);assert client.get(endpoint).status_code==404


def test_private_upload_is_allowed_before_completion_and_completion_does_not_publish_it(client,event):
    client.force_login(event[-1]);assert post_result(client,event,export_zip()).status_code==302
    recording=RunRecording.objects.get()
    assert post_result(client,event,published='on').status_code==200
    recording.refresh_from_db();assert not recording.published
    event[1].completed=True;event[1].save()
    client.logout();assert client.get(f'/recordings/{recording.pk}/player/').status_code==404


def test_publication_rechecks_completion_under_the_save_lock(client,event):
    _,r,teams,_,staff=event;r.completed=True;r.save()
    form=ResultForm({'revision':result_revision(r,teams[0]),'published':'on'},
        {'files':[export_zip()]},round_=r,team=teams[0],recording_only=True)
    assert form.is_valid(),form.errors
    Round.objects.filter(pk=r.pk).update(completed=False)
    with pytest.raises(ValidationError,match='completed and active'):save_result(form,staff)
    assert not RunRecording.objects.exists()
