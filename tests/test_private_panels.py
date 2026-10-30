import datetime as dt
from unittest.mock import patch

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from arena.access import can_download, public_asset
from arena.models import Announcement, Asset, EmailDelivery, Notification
from arena.programme import programme_context
from arena.services import announce, delete_submission, resend_invitation, upload_asset

pytestmark = pytest.mark.django_db


def private_file(event, kind='tdp'):
    return upload_asset(user=event[3][0], team=event[2][0], kind=kind,
        file=SimpleUploadedFile('private.txt', b'private team content'))


@pytest.mark.parametrize('kind', ['tdp','video','code','bom','poster','round_code','round_json'])
def test_all_team_uploads_stay_private_when_every_release_is_open(client, event, kind):
    c, r, teams, users, staff = event
    asset = upload_asset(user=users[0], team=teams[0], kind=kind,
        round_=r if kind.startswith('round_') else None, attested=True,
        file=SimpleUploadedFile('payload.json', b'{"robot":{}}'))
    asset.scan_status='clean'; asset.public_approved=True; asset.save()
    c.phase='finished'; c.archive_released=True; c.ends_at=timezone.now()-dt.timedelta(seconds=1); c.save()
    asset.refresh_from_db()
    assert not public_asset(asset)
    for user, status in [(None,404),(users[1],404),(users[0],200),(staff,200)]:
        client.logout()
        if user: client.force_login(user)
        assert client.get(f'/files/{asset.pk}/').status_code==status


def test_public_copy_is_independent_and_cannot_be_created_or_removed_by_team(client,event):
    c,r,teams,users,staff=event
    original=private_file(event)
    with pytest.raises(PermissionDenied):
        upload_asset(user=users[0],team=teams[0],kind='tdp',public_copy=True,
            file=SimpleUploadedFile('forged.txt',b'forged'))
    copy=upload_asset(user=staff,team=teams[0],kind='tdp',public_copy=True,
        file=SimpleUploadedFile('public.txt',b'public copy'))
    original.refresh_from_db()
    assert original.current and copy.current and original.blob_key!=copy.blob_key
    with pytest.raises(PermissionDenied): delete_submission(user=users[0],asset_id=copy.pk)
    copy.scan_status='clean';copy.public_approved=True;copy.save()
    assert not public_asset(copy)
    c.phase='finished';c.archive_released=True;c.ends_at=timezone.now()-dt.timedelta(seconds=1);c.save()
    copy.refresh_from_db()
    assert public_asset(copy)
    assert client.get(f'/files/{copy.pk}/').status_code==200
    assert client.get(f'/files/{original.pk}/').status_code==404
    client.force_login(users[0])
    html=client.get('/portal/documents/').content.decode()
    assert 'private.txt' in html and 'public.txt' not in html
    assert private_file(event).current


def test_admin_cannot_approve_private_files_even_after_scan(client,event):
    asset=private_file(event);asset.scan_status='clean';asset.save()
    client.force_login(event[4])
    assert client.post('/control/action/',{'action':'approve-file','id':asset.pk}).status_code==302
    asset.refresh_from_db();assert not asset.public_approved


def test_admin_upload_forms_cover_private_round_files_and_separate_public_copy(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    for kind in ['tdp','video','code','bom','poster','round_file']:
        response=client.post('/control/',{'form':'private-upload','team':teams[0].pk,'kind':kind,
            'round':r.pk if kind.startswith('round_') else '', 'attested':'on',
            'file':SimpleUploadedFile('admin.json', b'{"robot":{}}')})
        assert response.status_code==302,(kind,[str(m) for m in response.context['messages']])
        assert Asset.objects.get(kind=kind,public_copy=False).team_id==teams[0].pk
    assert client.post('/control/',{'form':'public-upload','team':teams[0].pk,'kind':'tdp',
        'file':SimpleUploadedFile('archive.pdf',b'public')}).status_code==302
    assert Asset.objects.filter(public_copy=True,kind='tdp').count()==1
    client.force_login(users[1])
    assert client.post('/control/',{'form':'public-upload'}).status_code==302
    assert Asset.objects.count()==7


def test_cross_team_delete_and_notice_read_are_denied(client,event):
    a=private_file(event)
    notice=announce(user=event[4],competition=event[0],title='Only team A',body='Private details',
        general=False,public=False,target_ids=[event[2][0].pk])
    notification=Notification.objects.get(announcement=notice)
    client.force_login(event[3][1])
    assert client.post(f'/files/{a.pk}/remove/').status_code==403
    assert client.post(f'/notices/{notification.pk}/read/').status_code==404
    assert b'Private details' not in client.get('/portal/announcements/').content
    assert b'Private details' not in client.get('/schedule/fragment/').content
    a.refresh_from_db();notification.refresh_from_db()
    assert a.current and notification.read_at is None


def test_admin_setup_link_is_private_single_use_and_not_emailed(client,event):
    from django.contrib.auth import get_user_model
    client.force_login(event[4])
    response=client.post('/control/action/',{'action':'setup-link','id':event[2][0].pk})
    assert response.status_code==200
    assert 'no-store' in response['Cache-Control'] and response['Referrer-Policy']=='no-referrer'
    link=response.context['setup_link'];account=response.context['account']
    assert not EmailDelivery.objects.exists()
    token=link.rsplit('/',2)[1]
    assert default_token_generator.check_token(account,token)
    # The built-in confirmation flow consumes the token when the password changes.
    anonymous=Client()
    confirm=anonymous.get(link.replace('http://localhost:8000',''))
    if confirm.status_code==400:  # PUBLIC_ORIGIN may be overridden by a test runner.
        from urllib.parse import urlsplit
        confirm=anonymous.get(urlsplit(link).path)
    assert confirm.status_code==302
    response=anonymous.post(confirm['Location'],{'new_password1':'New-team-password-2026!',
        'new_password2':'New-team-password-2026!'})
    assert response.status_code==302
    account=get_user_model().objects.get(pk=account.pk)
    assert account.check_password('New-team-password-2026!')
    assert not default_token_generator.check_token(account,token)
    client.force_login(event[3][1])
    assert client.post('/control/action/',{'action':'setup-link','id':event[2][0].pk}).status_code==302


def test_reset_queues_without_smtp_and_returns_same_response_for_unknown_email(client,event,settings):
    event[3][0].email='reset@example.test';event[3][0].save()
    settings.EMAIL_HOST=''
    with patch('django.core.mail.EmailMultiAlternatives.send',side_effect=AssertionError('Must queue')):
        known=client.post('/accounts/reset/',{'email':'reset@example.test'})
        unknown=client.post('/accounts/reset/',{'email':'unknown@example.test'})
    assert known.status_code==unknown.status_code==302
    assert known['Location']==unknown['Location']
    assert EmailDelivery.objects.get().recipient=='reset@example.test'


def test_public_announcement_refresh_version_never_includes_private_notices(event):
    c=event[0];before=programme_context([],c)['programme_version']
    notice=Announcement.objects.create(competition=c,author=event[4],title='Private',body='Secret',general=False)
    assert programme_context([],c)['programme_version']==before
    notice.general=True;notice.public=True;notice.save()
    public=programme_context([],c)
    assert public['programme_version']!=before and public['public_announcements']==[notice]
    notice.body='Updated';notice.save()
    assert programme_context([],c)['programme_version']!=public['programme_version']


def test_every_admin_mutation_requires_csrf_and_mfa(event,settings):
    client=Client(enforce_csrf_checks=True);client.force_login(event[4])
    assert client.post('/control/action/',{'action':'setup-link','id':event[2][0].pk}).status_code==403
    settings.REQUIRE_STAFF_OTP=True
    assert client.post('/control/action/',{'action':'setup-link','id':event[2][0].pk}).status_code==302
    assert not EmailDelivery.objects.exists()


def test_history_private_and_suspension_revokes_existing_session(client,event):
    old=private_file(event);private_file(event)
    client.force_login(event[3][0])
    assert client.get(f'/files/{old.pk}/').status_code==200
    other=Client();other.force_login(event[3][1])
    assert other.get(f'/files/{old.pk}/').status_code==404
    admin=Client();admin.force_login(event[4])
    admin.post('/control/action/',{'action':'suspend-team','id':event[2][0].pk})
    assert client.get('/portal/').status_code==302
    assert client.get(f'/files/{old.pk}/').status_code==404
    admin.post('/control/action/',{'action':'reactivate-team','id':event[2][0].pk})
    event[3][0].refresh_from_db();assert event[3][0].is_active


def test_trusted_proxy_uses_one_validated_ip_and_ignores_untrusted_headers(settings):
    from django.test import RequestFactory
    from arena.middleware import ProxyAddressMiddleware
    middleware=ProxyAddressMiddleware(lambda request: request.META['REMOTE_ADDR'])
    request=RequestFactory().get('/',REMOTE_ADDR='127.0.0.1',HTTP_X_ASR_CLIENT_IP='2001:db8::1',HTTP_X_ASR_PROXY_TOKEN='test-only-ingress-secret')
    settings.TRUST_PROXY_CLIENT_IP=False
    assert middleware(request)=='127.0.0.1'
    settings.TRUST_PROXY_CLIENT_IP=True
    settings.PROXY_SHARED_SECRET='test-only-ingress-secret'
    assert middleware(request)=='2001:db8::1'
    request=RequestFactory().get('/',REMOTE_ADDR='127.0.0.1',HTTP_X_ASR_CLIENT_IP='203.0.113.1, 192.0.2.1',HTTP_X_ASR_PROXY_TOKEN='test-only-ingress-secret')
    assert middleware(request)=='127.0.0.1'


def test_proxy_visitors_have_separate_anonymous_rate_limits(settings,event):
    from django.test import RequestFactory
    from arena.middleware import ProxyAddressMiddleware
    from arena.throttle import allow_request
    from django.contrib.auth.models import AnonymousUser
    settings.TRUST_PROXY_CLIENT_IP=True
    settings.PROXY_SHARED_SECRET='test-only-ingress-secret'
    def check(request):
        request.user=AnonymousUser()
        return allow_request(request,limit=1,period=3600)[0]
    middleware=ProxyAddressMiddleware(check)
    factory=RequestFactory()
    def request(ip): return factory.post('/accounts/reset/',REMOTE_ADDR='172.20.0.2',HTTP_X_ASR_CLIENT_IP=ip,HTTP_X_ASR_PROXY_TOKEN='test-only-ingress-secret')
    assert middleware(request('203.0.113.1'))
    assert not middleware(request('203.0.113.1'))
    assert middleware(request('203.0.113.2'))
