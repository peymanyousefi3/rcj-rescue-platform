import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from arena.models import Membership

pytestmark = pytest.mark.django_db


def test_team_can_change_password_without_changing_ownership(client, event):
    user = event[3][0]
    old_password = 'A-secure-test-password-2026'
    new_password = 'Maple-River-Sunset-42'
    other_session = Client()
    assert client.login(username=user.username, password=old_password)
    assert other_session.login(username=user.username, password=old_password)
    assert b'Change password' in client.get('/portal/').content
    page = client.get('/accounts/password/')
    assert page.status_code == 200
    assert 'no-store' in page['Cache-Control']
    response = client.post('/accounts/password/', {
        'old_password': old_password,
        'new_password1': new_password,
        'new_password2': new_password,
    })
    assert response.status_code == 302 and response.url == '/portal/'
    user.refresh_from_db()
    assert user.check_password(new_password) and not user.check_password(old_password)
    assert not user.is_staff and not user.is_superuser
    assert Membership.objects.get(user=user).team == event[2][0]
    assert client.get('/portal/').status_code == 200
    assert other_session.get('/portal/').status_code == 302
    fresh = Client()
    assert not fresh.login(username=user.username, password=old_password)
    assert fresh.login(username=user.username, password=new_password)
    assert fresh.get('/portal/').status_code == 200


@pytest.mark.parametrize('old,new1,new2', [
    ('wrong-password', 'Maple-River-Sunset-42', 'Maple-River-Sunset-42'),
    ('A-secure-test-password-2026', 'short', 'short'),
    ('A-secure-test-password-2026', 'Maple-River-Sunset-42', 'Different-Password-43'),
])
def test_password_change_rejects_invalid_input(client, event, old, new1, new2):
    user = event[3][0]
    client.force_login(user)
    before = user.password
    response = client.post('/accounts/password/', {
        'old_password': old, 'new_password1': new1, 'new_password2': new2,
    })
    assert response.status_code == 200 and response.context['form'].errors
    user.refresh_from_db()
    assert user.password == before


def test_password_change_requires_session_and_csrf(event):
    assert Client().get('/accounts/password/').status_code == 302
    client = Client(enforce_csrf_checks=True)
    client.force_login(event[3][0])
    assert client.post('/accounts/password/', {}).status_code == 403


def test_registered_email_can_be_used_as_team_sign_in(client, event):
    email = event[2][0].leader_email
    user = get_user_model().objects.create_user(username=email, email=email,
        password='Maple-River-Sunset-42')
    Membership.objects.create(user=user, team=event[2][0])
    assert client.login(username=email, password='Maple-River-Sunset-42')
    assert client.get('/portal/').status_code == 200
    assert client.get('/control/').status_code == 302


def test_login_has_one_clear_action_and_preserves_validation(client,event):
    page=client.get('/account/login/')
    html=page.content.decode()
    assert '<h1>Sign in</h1>' in html and '>Sign in</button>' in html
    assert '>Next</button>' not in html and '>Back</button>' not in html and '>Cancel</a>' not in html
    assert 'Forgot your password?' in html and 'csrfmiddlewaretoken' in html
    data={'login_view-current_step':'auth','auth-username':event[3][0].username,'auth-password':'wrong-password'}
    invalid=client.post('/account/login/',data)
    assert invalid.status_code==200 and invalid.context['wizard']['form'].errors
    assert '_auth_user_id' not in client.session
    data['auth-password']='A-secure-test-password-2026'
    response=client.post('/account/login/',data)
    assert response.status_code==302 and response.url=='/portal/'
    assert client.get('/portal/').status_code==200


@pytest.mark.parametrize('remember', [False, True])
def test_organizer_login_still_requires_authenticator_code(client,event,settings,remember):
    from django_otp.oath import totp
    from django_otp.plugins.otp_totp.models import TOTPDevice
    device=TOTPDevice.objects.create(user=event[4],name='default',confirmed=True)
    client.get('/account/login/')
    response=client.post('/account/login/',{'login_view-current_step':'auth',
        'auth-username':event[4].username,'auth-password':'Admin-test-password-2026',
        **({'remember_browser':'on'} if remember else {})})
    html=response.content.decode()
    assert response.status_code==200 and response.context['wizard']['steps'].current=='token'
    assert 'Verify your identity' in html and '>Verify code</button>' in html
    assert '>Next</button>' not in html and '>Back</button>' not in html and '>Cancel</a>' not in html
    assert '_auth_user_id' not in client.session
    response=client.post('/account/login/',{'login_view-current_step':'token',
        'token-otp_token':str(totp(device.bin_key)).zfill(6)})
    assert response.status_code==302
    assert client.session['otp_device_id']==device.persistent_id
    assert bool(response.cookies[settings.SESSION_COOKIE_NAME]['expires']) is remember
    assert client.session.get_expiry_age()==(settings.REMEMBER_SESSION_AGE if remember else settings.SESSION_COOKIE_AGE)


@pytest.mark.parametrize('remember', [False, True])
def test_browser_sign_in_lifetime_and_restart(client,event,settings,remember):
    from datetime import timedelta
    from unittest.mock import patch
    from django.utils import timezone
    from arena.models import EmailDelivery
    settings.SESSION_COOKIE_SECURE=True
    page=client.get('/account/login/',secure=True)
    assert b'Keep me signed in for 30 days' in page.content
    response=client.post('/account/login/?next=/control/',{
        'login_view-current_step':'auth','auth-username':event[4].username,
        'auth-password':'Admin-test-password-2026',
        **({'remember_browser':'on'} if remember else {})},secure=True)
    assert response.status_code==302 and response.url=='/control/'
    cookie=response.cookies[settings.SESSION_COOKIE_NAME]
    assert cookie['httponly'] and cookie['secure'] and cookie['samesite']=='Lax'
    assert bool(cookie['expires']) is remember
    assert cookie['max-age']==(settings.REMEMBER_SESSION_AGE if remember else '')
    assert 'Admin-test-password-2026' not in repr(dict(client.session))
    # A reopened browser retains only cookies with an explicit expiry.
    restarted=Client()
    if cookie['expires']: restarted.cookies[settings.SESSION_COOKIE_NAME]=cookie.value
    assert restarted.get('/control/',secure=True).status_code==(200 if remember else 302)
    with patch('django.utils.timezone.now',return_value=timezone.now()+timedelta(hours=2)):
        assert client.get('/control/',secure=True).status_code==(200 if remember else 302)
    if remember:
        with patch('django.utils.timezone.now',return_value=timezone.now()+timedelta(days=31)):
            assert restarted.get('/control/',secure=True).status_code==302
    assert not EmailDelivery.objects.exists()


@pytest.mark.parametrize('revoke', ['logout','password','disabled'])
def test_remembered_browser_does_not_bypass_account_revocation(client,event,settings,revoke):
    user=event[4]
    client.get('/account/login/')
    response=client.post('/account/login/',{'login_view-current_step':'auth',
        'auth-username':user.username,'auth-password':'Admin-test-password-2026','remember_browser':'on'})
    assert response.status_code==302
    other=Client();other.cookies[settings.SESSION_COOKIE_NAME]=client.cookies[settings.SESSION_COOKIE_NAME].value
    assert other.get('/control/').status_code==200
    if revoke=='logout':
        assert client.post('/accounts/logout/').status_code==302
    elif revoke=='password':
        user.set_password('A-different-secure-password-2026');user.save()
    else:
        user.is_active=False;user.save()
    assert other.get('/control/').status_code==302


def test_login_requires_csrf(event):
    client=Client(enforce_csrf_checks=True)
    assert client.post('/account/login/',{'login_view-current_step':'auth'}).status_code==403


def test_login_recovery_code_remains_available(client,event):
    from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
    from django_otp.plugins.otp_totp.models import TOTPDevice
    TOTPDevice.objects.create(user=event[4],name='default',confirmed=True)
    backup=StaticDevice.objects.create(user=event[4],name='backup')
    token=StaticToken.objects.create(device=backup,token='12743698')
    client.get('/account/login/')
    response=client.post('/account/login/',{'login_view-current_step':'auth',
        'auth-username':event[4].username,'auth-password':'Admin-test-password-2026'})
    assert b'Use a recovery code' in response.content
    response=client.post('/account/login/',{'wizard_goto_step':'backup'})
    assert response.context['wizard']['steps'].current=='backup'
    assert b'<h1>Use a recovery code</h1>' in response.content
    response=client.post('/account/login/',{'login_view-current_step':'backup','backup-otp_token':token.token})
    assert response.status_code==302 and '_auth_user_id' in client.session
    assert not StaticToken.objects.filter(pk=token.pk).exists()


@pytest.mark.parametrize('step', ['welcome', 'generator'])
def test_authenticator_setup_cancel_leaves_wizard_without_bypassing_mfa(client,event,settings,step):
    import re
    from django_otp.plugins.otp_totp.models import TOTPDevice
    settings.REQUIRE_STAFF_OTP=True
    client.force_login(event[4])
    page=client.get('/account/two_factor/setup/')
    if step=='generator':
        page=client.post('/account/two_factor/setup/',{'setup_view-current_step':'welcome'})
    assert page.context['wizard']['steps'].current==step
    cancel=re.search(r'<a\s+href="([^"]+)"\s+class="([^"]+)">\s*Cancel\s*</a>',page.content.decode())
    assert cancel and {'button','secondary'} <= set(cancel[2].split())
    assert cancel[1]=='/'
    response=client.get(cancel[1],follow=True)
    assert response.status_code==200 and response.redirect_chain==[]
    assert response.wsgi_request.path=='/'
    assert not TOTPDevice.objects.filter(user=event[4]).exists()
    assert client.get('/control/').url=='/account/two_factor/setup/'
    assert client.get('/account/two_factor/setup/').context['wizard']['steps'].current=='welcome'


def test_first_time_organizer_can_open_both_admin_panels_without_enrollment(client,event,settings):
    from django_otp.plugins.otp_totp.models import TOTPDevice
    settings.REQUIRE_STAFF_OTP=False
    staff=event[4];staff.is_superuser=True;staff.save()
    client.get('/account/login/')
    response=client.post('/account/login/',{'login_view-current_step':'auth',
        'auth-username':staff.username,'auth-password':'Admin-test-password-2026'},follow=True)
    assert response.status_code==200 and response.wsgi_request.path=='/control/'
    assert all('two_factor/setup' not in url for url,status in response.redirect_chain)
    assert client.get('/system/').status_code==200
    assert client.get('/system/arena/team/').status_code==200
    assert client.get('/control/audit.csv').status_code==200
    assert not TOTPDevice.objects.filter(user=staff).exists()


def test_optional_enrollment_does_not_bypass_an_existing_authenticator(client,event,settings):
    from django_otp.plugins.otp_totp.models import TOTPDevice
    settings.REQUIRE_STAFF_OTP=False
    TOTPDevice.objects.create(user=event[4],name='default',confirmed=True)
    client.force_login(event[4])
    for path in ['/control/','/system/','/control/audit.csv']:
        response=client.get(path)
        assert response.status_code==302 and response.url.startswith('/account/login/?next=')
    response=client.get('/system/login/')
    assert response.status_code==302 and response.url.startswith('/account/login/')


def test_system_sign_in_uses_the_same_account_login(client):
    response=client.get('/system/login/?next=/system/arena/team/')
    assert response.status_code==302 and response.url=='/account/login/?next=/system/arena/team/'
