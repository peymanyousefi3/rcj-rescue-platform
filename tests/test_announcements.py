from io import StringIO
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.core.management import call_command, CommandError
from django.utils import timezone

from arena.forms import AnnouncementForm, EmailConfigurationForm
from arena.mail import credential_cipher, email_ready, mail_connection
from arena.models import AuditEvent, EmailConfiguration, EmailDelivery, Notification
from arena.services import announce

pytestmark=pytest.mark.django_db

@pytest.mark.parametrize('general,public',[(True,True),(True,False),(False,True),(False,False)])
def test_announcement_audiences_and_personalization(client,event,general,public):
    c,r,teams,users,staff=event
    notice=announce(user=staff,competition=c,title='Round briefing',body='Arrive early.\nBring your files.',
        general=general,public=public,target_ids=[teams[0].pk])
    expected=teams if general else teams[:1]
    assert set(notice.targets.all())==set(expected)
    assert Notification.objects.count()==len(expected)
    assert EmailDelivery.objects.count()==len(expected)
    for team in expected:
        message=EmailDelivery.objects.get(team=team)
        assert message.recipient==team.leader_email
        assert f'Dear {team.name} Mentor,' in message.body and f'Dear {team.name} Mentor,' in message.html_body
        assert f'#announcement-{notice.pk}' in message.body
        assert 'Arrive early.<br>Bring your files.' in message.html_body
    assert ('Round briefing' in client.get('/').content.decode())==public
    assert ('Round briefing' in client.get('/schedule/fragment/').content.decode())==public
    for team,user in zip(teams,users):
        client.force_login(user)
        response=client.get('/notices/fragment/')
        assert response.status_code==200 and 'no-store' in response['Cache-Control']
        assert ('Round briefing' in response.json()['html'])==(team in expected)
        assert response.json()['unread']==int(team in expected)
        assert ('Round briefing' in client.get('/portal/announcements/').content.decode())==(team in expected)

def test_announcement_validation_escaping_and_access(client,event):
    c,r,teams,users,staff=event
    assert not AnnouncementForm({'title':'Title','body':'Body'},competition=c).is_valid()
    with pytest.raises(PermissionDenied):
        announce(user=users[0],competition=c,title='No',body='No',general=True,public=False,target_ids=[])
    teams[0].name='<img src=x onerror=alert(1)>';teams[0].save()
    announce(user=staff,competition=c,title='Safe\nsubject',body='<script>bad()</script>',general=False,public=False,target_ids=[teams[0].pk])
    message=EmailDelivery.objects.get()
    assert '\n' not in message.subject
    assert '<script>' not in message.html_body and '&lt;script&gt;' in message.html_body
    assert '<img src=x' not in message.html_body and '&lt;img' in message.html_body
    assert client.get('/notices/fragment/').status_code==302
    client.force_login(users[0]);before=client.get('/notices/fragment/').json()
    notification=Notification.objects.get()
    client.post(f'/notices/{notification.pk}/read/')
    after=client.get('/notices/fragment/').json()
    assert before['version']!=after['version'] and after['unread']==0
    assert 'Mark as read' not in after['html']
    client.force_login(users[1])
    assert client.post(f'/notices/{notification.pk}/read/').status_code==404

def test_delivery_multipart_single_recipient_retry_and_deduplication(event,settings):
    settings.DEBUG=True
    announce(user=event[4],competition=event[0],title='Briefing',body='Text',general=True,public=False,target_ids=[])
    call_command('deliver_mail',stdout=StringIO())
    assert len(mail.outbox)==2
    for message in mail.outbox:
        assert len(message.to)==1 and not message.cc and not message.bcc
        assert message.alternatives[0].mimetype=='text/html'
        assert 'Dear Team' in message.body
        assert message.extra_headers['Message-ID'].startswith('<asr26-')
    call_command('deliver_mail',stdout=StringIO())
    assert len(mail.outbox)==2
    item=EmailDelivery.objects.first();item.sent_at=None;item.attempts=0;item.save()
    with patch('django.core.mail.EmailMultiAlternatives.send',side_effect=RuntimeError('secret credential must not be logged')):
        call_command('deliver_mail',stdout=StringIO())
    item.refresh_from_db()
    assert item.sent_at is None and item.attempts==1 and item.last_error=='RuntimeError'
    assert item.next_attempt_at>timezone.now()

def email_data(**extra):
    return dict(provider='smtp',enabled=True,sender_name='ASR organizers',sender_email='asr@example.test',host='smtp.example.test',
        port=587,security='starttls',username='asr@example.test',password='synthetic-only-password',**extra)

def test_admin_config_encrypts_preserves_and_removes_secret(client,event,settings):
    client.force_login(event[3][0])
    assert client.post('/control/',{'form':'email-settings',**email_data()}).status_code==302
    assert not EmailConfiguration.objects.exists()
    client.force_login(event[4])
    response=client.post('/control/',{'form':'email-settings',**email_data()})
    assert response.status_code==302
    config=EmailConfiguration.objects.get()
    assert 'synthetic-only-password' not in config.password_encrypted
    assert credential_cipher().decrypt(config.password_encrypted.encode()).decode()=='synthetic-only-password'
    page=client.get('/control/').content.decode()
    assert 'synthetic-only-password' not in page and config.password_encrypted not in page
    assert 'synthetic-only-password' not in str(list(AuditEvent.objects.values()))
    data=email_data();data['password']=''
    form=EmailConfigurationForm(data,instance=config);assert form.is_valid(),form.errors
    saved=form.save();assert saved.password_encrypted==config.password_encrypted
    assert email_ready()
    with patch('arena.mail.get_connection') as get_connection:
        connection,sender=mail_connection()
        assert sender=='ASR organizers <asr@example.test>'
        assert get_connection.call_args.kwargs['use_tls'] and not get_connection.call_args.kwargs['use_ssl']
        assert get_connection.call_args.kwargs['password']=='synthetic-only-password'
    data.update(enabled=False,clear_password=True)
    form=EmailConfigurationForm(data,instance=saved);assert form.is_valid(),form.errors
    assert not form.save().password_encrypted and not email_ready()
    with pytest.raises(ImproperlyConfigured):mail_connection()
    with pytest.raises(CommandError):call_command('deliver_mail',stdout=StringIO())

def test_mail_settings_validation_and_missing_configuration(event,settings):
    for field,value in [('host','https://bad.test:22'),('port',70000),('sender_name','ASR\nBcc: bad@example.test'),('sender_email',''),('security','plain')]:
        data=email_data();data[field]=value
        assert not EmailConfigurationForm(data).is_valid()
    settings.DEBUG=False;settings.EMAIL_HOST='';settings.DEFAULT_FROM_EMAIL=''
    EmailDelivery.objects.create(dedupe_key='old-invite',subject='Setup',body='Text only',recipient='synthetic@example.test')
    with pytest.raises(CommandError):call_command('deliver_mail',stdout=StringIO())
    assert EmailDelivery.objects.get().attempts==0
    settings.DEBUG=True
    call_command('deliver_mail',stdout=StringIO())
    assert len(mail.outbox)==1 and not mail.outbox[0].alternatives

def test_mail_configuration_ssl_and_key_rotation(event,settings):
    data=email_data();data.update(security='ssl',port=465)
    form=EmailConfigurationForm(data);assert form.is_valid(),form.errors
    config=form.save()
    old_secret=settings.SECRET_KEY
    settings.SECRET_KEY='rotated-synthetic-secret';settings.SECRET_KEY_FALLBACKS=[old_secret]
    with patch('arena.mail.get_connection') as connection:
        mail_connection()
        assert connection.call_args.kwargs['use_ssl'] and not connection.call_args.kwargs['use_tls']
        assert connection.call_args.kwargs['password']=='synthetic-only-password'
    settings.SECRET_KEY_FALLBACKS=[]
    with pytest.raises(ImproperlyConfigured):mail_connection()

def test_gmail_preset_normalizes_connection_and_preserves_secret(client,event):
    data={'provider':'gmail','sender_name':'ASR organizers','sender_email':'Organizer@gmail.com',
        'password':'abcd efgh ijkl mnop','host':'attacker.test','port':25,'security':'plain','username':'wrong'}
    form=EmailConfigurationForm(data)
    assert form.is_valid(),form.errors
    config=form.save()
    assert not config.enabled
    assert (config.host,config.port,config.security,config.username)==('smtp.gmail.com',587,'starttls','organizer@gmail.com')
    assert credential_cipher().decrypt(config.password_encrypted.encode()).decode()=='abcdefghijklmnop'
    assert EmailConfigurationForm(instance=config)['provider'].value()=='gmail'
    with pytest.raises(ImproperlyConfigured):mail_connection()
    with patch('arena.mail.get_connection') as connection:
        mail_connection(allow_paused=True)
        assert connection.call_args.kwargs==dict(host='smtp.gmail.com',port=587,username='organizer@gmail.com',
            password='abcdefghijklmnop',use_tls=True,use_ssl=False,timeout=20)
    data.update(password='',enabled=True)
    form=EmailConfigurationForm(data,instance=config)
    assert form.is_valid(),form.errors
    assert form.save().password_encrypted==config.password_encrypted
    client.force_login(event[4])
    page=client.get('/control/').content.decode()
    assert 'Check saved connection' in page
    assert 'Google App passwords' in client.get('/control/?editor=email-settings').content.decode()
    assert 'abcdefghijklmnop' not in page and config.password_encrypted not in page

@pytest.mark.parametrize('password',['ordinary-password','short','abcd efgh ijkl mnöр'])
def test_gmail_rejects_non_app_password(password):
    form=EmailConfigurationForm({'provider':'gmail','sender_email':'owner@gmail.com','password':password})
    assert not form.is_valid() and 'password' in form.errors

def test_gmail_saved_password_requires_same_account_and_provider():
    data=email_data()
    form=EmailConfigurationForm(data);assert form.is_valid()
    config=form.save()
    data.update(provider='gmail',password='')
    form=EmailConfigurationForm(data,instance=config)
    assert not form.is_valid() and 'password' in form.errors
    data.update(password='abcdefghijklmnop')
    form=EmailConfigurationForm(data,instance=config);assert form.is_valid(),form.errors
    config=form.save()
    data.update(sender_email='other@gmail.com',password='')
    form=EmailConfigurationForm(data,instance=config)
    assert not form.is_valid() and 'password' in form.errors
    data.update(enabled=False,clear_password=True)
    form=EmailConfigurationForm(data,instance=config);assert form.is_valid(),form.errors
    assert not form.save().password_encrypted

@pytest.mark.parametrize('succeeds',[True,False])
def test_saved_connection_check_authenticates_without_sending(client,event,succeeds):
    data=email_data();data['enabled']=False
    form=EmailConfigurationForm(data);assert form.is_valid()
    form.save()
    with patch('arena.mail.get_connection') as connection:
        client.force_login(event[3][0])
        assert client.post('/control/',{'form':'email-check'}).status_code==302
        connection.assert_not_called()
        client.force_login(event[4])
        if not succeeds:
            connection.return_value.open.side_effect=RuntimeError('synthetic-secret-must-not-be-shown')
        response=client.post('/control/',{'form':'email-check'},follow=True)
        connection.return_value.open.assert_called_once()
        connection.return_value.close.assert_called_once()
        connection.return_value.send_messages.assert_not_called()
    assert ('authenticated successfully' in response.content.decode())==succeeds
    assert 'synthetic-secret-must-not-be-shown' not in response.content.decode()
    assert not EmailDelivery.objects.exists() and not EmailConfiguration.objects.get().enabled
    assert AuditEvent.objects.get(action='email.connection_checked').detail=={'success':succeeds}

def test_connection_check_requires_saved_credential(client,event):
    client.force_login(event[4])
    with patch('arena.views.mail_connection') as connection:
        response=client.post('/control/',{'form':'email-check'},follow=True)
        connection.assert_not_called()
    assert 'Connection failed' in response.content.decode()


def test_expired_account_links_are_preserved_but_never_delivered(event,settings,client):
    from datetime import timedelta
    from arena.forms import QueuedPasswordResetForm
    settings.DEBUG=True
    old=EmailDelivery.objects.create(dedupe_key='password-reset:expired',subject='Expired reset',
        body='Expired secret link',recipient='synthetic@example.test',
        expires_at=timezone.now()-timedelta(seconds=1))
    normal=EmailDelivery.objects.create(dedupe_key='notice:pending',subject='Notice',
        body='Ordinary announcement',recipient='synthetic@example.test')
    user=event[3][0];user.email='leader0@example.test';user.save()
    form=QueuedPasswordResetForm({'email':user.email})
    assert form.is_valid()
    form.save(domain_override='example.test',use_https=True)
    fresh=EmailDelivery.objects.get(dedupe_key__startswith='password-reset:',expires_at__gt=timezone.now())
    assert 3500<(fresh.expires_at-fresh.created_at).total_seconds()<=3600
    call_command('deliver_mail',stdout=StringIO())
    old.refresh_from_db();normal.refresh_from_db();fresh.refresh_from_db()
    assert old.sent_at is None and old.attempts==0
    assert normal.sent_at is not None and fresh.sent_at is not None
    assert all('Expired secret link' not in message.body for message in mail.outbox)
    client.force_login(event[4])
    response=client.get('/control/')
    assert response.context['email_pending']==0


def test_announcement_cc_bcc_never_copy_account_messages(event,settings):
    settings.DEBUG=True
    config=EmailConfiguration.objects.create(enabled=True,sender_email='announcements@example.test',host='smtp.example.test',
        announcement_cc='canada@example.test',announcement_bcc='owner@example.test')
    announce(user=event[4],competition=event[0],title='Briefing',body='Team notice',general=True,public=False,target_ids=[])
    for prefix in ['password-reset','invite','reinvite']:
        EmailDelivery.objects.create(dedupe_key=prefix+':private',subject=prefix,body='Private account link',recipient='leader@example.test')
    with patch('arena.management.commands.deliver_mail.mail_connection',return_value=(mail.get_connection(),'announcements@example.test')):
        call_command('deliver_mail',stdout=StringIO())
    assert len(mail.outbox)==5
    for message in mail.outbox:
        if message.subject in ['password-reset','invite','reinvite']:
            assert not message.cc and not message.bcc
        else:
            assert message.cc==['canada@example.test'] and message.bcc==['owner@example.test']
            assert len(message.to)==1
            assert 'Bcc:' not in message.message().as_string()
            assert 'owner@example.test' not in message.message().as_string()
    assert all(item.sent_at for item in EmailDelivery.objects.all())


def test_announcement_copy_config_validation_and_admin_privacy(client,event):
    data=email_data();data.update(announcement_cc='canada@example.test; canada@example.test\nother@example.test',
        announcement_bcc='owner@example.test')
    client.force_login(event[4]);assert client.post('/control/',{'form':'email-settings',**data}).status_code==302
    config=EmailConfiguration.objects.get()
    assert config.announcement_cc=='canada@example.test\nother@example.test' and config.announcement_bcc=='owner@example.test'
    data['announcement_cc']='canada@example.test\r\nBcc: attacker@example.test'
    form=EmailConfigurationForm(data,instance=config)
    assert not form.is_valid() and 'announcement_cc' in form.errors
    client.force_login(event[3][0]);assert b'owner@example.test' not in client.get('/portal/announcements/').content
