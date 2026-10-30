"""Isolated evidence for operational and privacy controls; never uses real accounts."""
import json
import time
from collections import Counter
from unittest.mock import patch

import pytest
from django.contrib.auth import authenticate, get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, DatabaseError
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from arena.models import Asset, Challenge, EmailConfiguration, EmailDelivery, Score, Team
from arena.services import upload_asset

pytestmark = pytest.mark.django_db


def test_query_growth_is_bounded_for_large_team_lists(client, event):
    competition, round_, teams, users, staff = event
    challenge = Challenge.objects.create(competition=competition, name='Main', primary=True)
    round_.challenge = challenge; round_.save()
    samples = []
    for target in (2, 50):
        extra = target - Team.objects.count()
        Team.objects.bulk_create([Team(competition=competition,code=f'BENCH{i:03}', name=f'Benchmark {i}')
                                 for i in range(extra)])
        Score.objects.bulk_create([Score(round=round_,team=t,raw=100,normalized=1)
                                   for t in Team.objects.exclude(score__round=round_)])
        for identity, path in [('public','/results/'),('admin','/control/')]:
            client.logout()
            if identity == 'admin':client.force_login(staff)
            with CaptureQueriesContext(connection) as captured:
                started = time.perf_counter(); response = client.get(path)
                seconds = time.perf_counter()-started
            assert response.status_code == 200
            samples.append({'teams':target,'view':identity,'queries':len(captured),'seconds':round(seconds,4)})
    print('QUERY_PROFILE',json.dumps(samples))
    for identity in ('public','admin'):
        pair=[s for s in samples if s['view']==identity]
        assert pair[1]['queries'] <= pair[0]['queries']+5, samples


def test_reset_response_has_no_existence_or_delivery_oracle(event):
    user=event[3][0]; user.email='known@example.test'; user.save()
    responses=[]; timings={}
    for label,email in [('known',user.email),('unknown','unknown@example.test')]:
        timings[label]=[]
        for n in range(5):
            client=Client(REMOTE_ADDR=f'192.0.2.{n+1}')
            started=time.perf_counter();response=client.post('/accounts/reset/',{'email':email},follow=True)
            timings[label].append(round(time.perf_counter()-started,4))
            responses.append((response.status_code,response.request['PATH_INFO'],response.content))
    assert all(r==responses[0] for r in responses)
    assert EmailDelivery.objects.filter(recipient=user.email).count()==5
    assert not EmailDelivery.objects.filter(recipient='unknown@example.test').exists()
    print('RESET_TIMINGS',json.dumps(timings))


def test_lockout_does_not_lock_unrelated_team_or_ip(event,settings):
    settings.AXES_ENABLED=True
    first,second=event[3]
    from django.test import RequestFactory
    factory=RequestFactory()
    for _ in range(settings.AXES_FAILURE_LIMIT):
        assert authenticate(factory.post('/account/login/',REMOTE_ADDR='192.0.2.10'),username=first.username,password='wrong') is None
    assert authenticate(factory.post('/account/login/',REMOTE_ADDR='192.0.2.10'),username=first.username,password='A-secure-test-password-2026') is None
    assert authenticate(factory.post('/account/login/',REMOTE_ADDR='192.0.2.11'),username=first.username,password='A-secure-test-password-2026') == first
    assert authenticate(factory.post('/account/login/',REMOTE_ADDR='192.0.2.10'),username=second.username,password='A-secure-test-password-2026') == second


def test_key_rotation_and_retirement_do_not_expose_smtp_credential(event,settings):
    from arena.mail import credential_cipher,mail_connection
    from django.core.exceptions import ImproperlyConfigured
    old='synthetic-original-signing-key-for-rotation-only'
    current='synthetic-replacement-signing-key-for-rotation-only'
    encrypted=credential_cipher(old).encrypt(b'synthetic-mail-credential').decode()
    EmailConfiguration.objects.create(pk=1,enabled=True,host='smtp.example.test',sender_email='sender@example.test',password_encrypted=encrypted)
    settings.SECRET_KEY=current;settings.SECRET_KEY_FALLBACKS=[old]
    with patch('arena.mail.get_connection') as connection_factory:
        mail_connection();assert connection_factory.call_args.kwargs['password']=='synthetic-mail-credential'
    settings.SECRET_KEY_FALLBACKS=[]
    with pytest.raises(ImproperlyConfigured):mail_connection()
    config=EmailConfiguration.objects.get(pk=1)
    config.password_encrypted=credential_cipher().encrypt(b'rotated-mail-credential').decode();config.save()
    with patch('arena.mail.get_connection') as connection_factory:
        mail_connection();assert connection_factory.call_args.kwargs['password']=='rotated-mail-credential'


@pytest.mark.parametrize('revoke',['password','disable','logout'])
def test_incident_revocation_invalidates_copied_sessions_and_downloads(event,revoke):
    user=event[3][0];other=event[3][1]
    asset=upload_asset(user=user,team=event[2][0],kind='tdp',file=SimpleUploadedFile('private.txt',b'synthetic private marker'))
    owner=Client();owner.force_login(user);copied=Client();copied.cookies=owner.cookies.copy()
    response=copied.get(f'/files/{asset.pk}/');assert response.status_code==200
    if response.streaming:list(response.streaming_content)
    if revoke=='password':user.set_password('synthetic-rotated-password-2026');user.save()
    elif revoke=='disable':user.is_active=False;user.save()
    else:owner.post('/accounts/logout/')
    assert copied.get(f'/files/{asset.pk}/').status_code==404
    assert copied.get('/portal/').status_code==302
    outsider=Client();outsider.force_login(other);assert outsider.get(f'/files/{asset.pk}/').status_code==404


def test_runtime_failure_pages_are_generic_and_private(client,event,settings):
    settings.DEBUG=False
    client.raise_request_exception=False
    with patch('arena.views.current_competition',side_effect=RuntimeError('SYNTHETIC-SECRET-MUST-NOT-LEAK')):
        page=client.get('/results/')
    assert page.status_code==500
    assert b'Before retrying an upload' in page.content
    assert b'SYNTHETIC-SECRET-MUST-NOT-LEAK' not in page.content
    with patch('django.db.connection.cursor',side_effect=DatabaseError('synthetic database failure')):
        for path in ['/health/','/ready/']:
            response=client.get(path)
            assert response.status_code==503
            assert b'synthetic database failure' not in response.content
            assert 'no-store' in response['Cache-Control']


def test_risky_release_controls_are_server_enforced_not_just_ui(client,event):
    c,r,teams,users,staff=event
    client.force_login(users[0])
    before=(r.maps_released,c.archive_released)
    client.post('/control/action/',{'action':'release-archive'})
    r.refresh_from_db();c.refresh_from_db()
    assert (r.maps_released,c.archive_released)==before
