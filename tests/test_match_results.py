import json
import zipfile
from decimal import Decimal

import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile

from arena.models import RunRecording, Score
from arena.recordings import result_revision
from test_results_recordings import export_zip, post_result

pytestmark = pytest.mark.django_db

RESULT = {'final_score': 215.375, 'field_score': 180.1, 'exit_bonus': 20,
          'map_bonus': 15.275, 'elapsed_seconds': 454, 'max_seconds': 480,
          'remaining_seconds': 26, 'last_event': '07:34 Successful Exit'}


@pytest.mark.parametrize('folder', [False, True])
def test_complete_package_result_paths_isolation_and_permissions(client, event, folder):
    _, round_, teams, users, staff = event
    client.force_login(staff)
    Score.objects.create(round=round_, team=teams[0], raw=Decimal('42'), elapsed_seconds=123)
    scores = list(Score.objects.values())
    package = export_zip(**{'run/match-result.json': json.dumps(RESULT).encode()})
    with zipfile.ZipFile(package) as archive:
        files = {'parent/' + name: archive.read(name) for name in archive.namelist()}
    data = {'revision': result_revision(round_, teams[0])}
    if folder:
        data.update(paths=json.dumps(list(files)), files=[
            SimpleUploadedFile(path.rsplit('/', 1)[-1], content) for path, content in files.items()])
    else:
        import io
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for path, content in files.items(): archive.writestr(path, content)
        data['files'] = SimpleUploadedFile('parent.zip', stream.getvalue())
    response = client.post(f'/control/results/{round_.pk}/{teams[0].pk}/?recording=1', data)
    assert response.status_code == 302, response.content
    assert list(Score.objects.values()) == scores  # Exported totals never overwrite entered competition scores.
    recording = RunRecording.objects.get()
    assert recording.entry_path == 'parent/run/replay.html'
    for path, content in files.items():
        with default_storage.open(f'recordings/{recording.pk}/{path}', 'rb') as stored:
            assert stored.read() == content
    endpoint = f'/recordings/{recording.pk}/player/'
    expected = {'available': True,
                'scores': {'final_score': '215.38', 'field_score': '180.10', 'exit_bonus': '20.00', 'map_bonus': '15.28'},
                'times': {'elapsed_seconds': '07:34', 'max_seconds': '08:00', 'remaining_seconds': '00:26'},
                'event_history_available': False, 'events': []}
    assert client.get(endpoint).json()['result'] == expected
    client.force_login(users[0])
    response = client.get(endpoint)
    assert response.json()['result'] == expected
    result_url = response.json()['url'].split('#')[0].replace(recording.entry_path, 'parent/run/match-result.json')
    assert json.loads(b''.join(client.get(result_url).streaming_content)) == RESULT
    client.force_login(users[1])
    assert client.get(endpoint).status_code == client.get(result_url).status_code == 404
    client.logout()
    assert client.get(endpoint).status_code == client.get(result_url).status_code == 404
    # Replacement retains the previous package in its own private directory.
    client.force_login(staff)
    assert post_result(client, event, export_zip(**{'run/match-result.json': b'{"final_score":0}'})).status_code == 302
    current = RunRecording.objects.get(current=True)
    assert current.pk != recording.pk
    assert client.get(f'/recordings/{current.pk}/player/').json()['result']['scores']['final_score'] == '0.00'
    assert client.get(endpoint).json()['result'] == expected


@pytest.mark.parametrize('content', [None, b'{broken', b'[]', b'null', b'\xff', b' ' * (1024 * 1024 + 1), b'{"final_score":1e999999999999999999999999}'])
def test_legacy_or_invalid_result_metadata_does_not_prevent_playback(client, event, content):
    client.force_login(event[-1])
    assert post_result(client, event, export_zip(**{'run/match-result.json': content})).status_code == 302
    recording = RunRecording.objects.get()
    response = client.get(f'/recordings/{recording.pk}/player/')
    assert response.status_code == 200 and response.json()['url']
    assert response.json()['result'] == {'available': False, 'scores': {}, 'times': {}, 'event_history_available': False, 'events': []}


@pytest.mark.parametrize('metadata', [
    {'final_score': None, 'last_event': None},
    {'final_score': True, 'field_score': 'NaN', 'exit_bonus': 'Infinity', 'map_bonus': {}, 'remaining_seconds': -1},
    {'final_score': '1e9999999', 'last_event': []},
])
def test_missing_invalid_values_are_not_replaced_with_zero_or_inferred_events(client, event, metadata):
    client.force_login(event[-1])
    assert post_result(client, event, export_zip(**{'run/match-result.json': json.dumps(metadata).encode()})).status_code == 302
    result = client.get(f'/recordings/{RunRecording.objects.get().pk}/player/').json()['result']
    assert not result['available'] and not result['event_history_available']
    assert all(value is None for value in [*result['scores'].values(), *result['times'].values()])


@pytest.mark.parametrize('events,available', [
    (None, False), ([], True),
    ([{'timestamp': '01:45', 'time_seconds': 105, 'text': 'Successful Target Identification +60', 'playback_time_ms': 1000}], True),
    ([{'timestamp': '07:34', 'text': 'Missing playback timestamp'}], False),
    ([{'timestamp': '07:34', 'text': 'Invalid time', 'playback_time_ms': -1}], False),
    ([{'timestamp': 'invalid', 'text': 'Invalid timestamp', 'playback_time_ms': 1000}], False),
])
def test_exported_event_history_is_detected_and_static_last_event_is_not_used(client, event, events, available):
    client.force_login(event[-1])
    metadata = {**RESULT, 'events': events, 'last_event': '07:34 Static final event must not follow the player'}
    assert post_result(client, event, export_zip(**{'run/match-result.json': json.dumps(metadata).encode()})).status_code == 302
    result = client.get(f'/recordings/{RunRecording.objects.get().pk}/player/').json()['result']
    assert result['event_history_available'] == available
    assert 'last_event' not in result  # Only the original HTML owns timeline synchronization.


@pytest.mark.parametrize('missing', ['run/replay.x3d', 'run/replay.json', 'run/textures/floor.jpg'])
def test_missing_dependencies_name_the_file(client, event, missing):
    client.force_login(event[-1])
    response = post_result(client, event, export_zip(**{missing: None}))
    assert response.status_code == 200 and f'Missing export file: {missing}'.encode() in response.content
    assert not RunRecording.objects.exists()


@pytest.mark.parametrize('reference', ['file:///local-export/events.js', 'http://localhost:8000/events.js',
                                     'https://127.0.0.1/events.js', 'http://[::1]/events.js', 'C:/recording/events.js'])
def test_computer_local_dependencies_are_rejected_before_saving(client, event, reference):
    client.force_login(event[-1])
    with zipfile.ZipFile(export_zip()) as archive: html = archive.read('run/replay.html')
    html = html.replace(b'</head>', f'<script src="{reference}"></script></head>'.encode())
    response = post_result(client, event, export_zip(**{'run/replay.html': html}))
    assert response.status_code == 200 and b'Computer-local reference:' in response.content
    assert not RunRecording.objects.exists()
