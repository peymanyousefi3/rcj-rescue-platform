from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from arena.control_forms import ManageAnnouncementForm
from arena.mail import announcement_recipients
from arena.models import Announcement, EmailConfiguration, EmailDelivery, Notification
from arena.services import announce, queue_announcement_copy

pytestmark=pytest.mark.django_db


def data(**extra):
    return {'form':'notice','title':'Format review','body':'Please review this sample.','recipient_module':'1',
        'targets':[],'email_recipients':'Peyman <owner@example.test>','send_email':'on',**extra}


def test_direct_recipient_form_and_admin_create_edit_remain_private(client,event):
    c,r,teams,users,staff=event
    form=ManageAnnouncementForm(data(),competition=c)
    assert form.is_valid(),form.errors
    client.force_login(staff)
    page=client.get('/control/?editor=notice').content.decode()
    assert page.count('name="email_recipients"')==1
    assert page.index('name="email_recipients"')<page.index('name="send_email"')
    response=client.post('/control/?editor=notice',data(),HTTP_X_ASR_EDITOR='1')
    assert response.status_code==200 and response.json()['redirect']=='/control/#announce'
    notice=Announcement.objects.get();delivery=EmailDelivery.objects.get()
    assert notice.email_recipients=='Peyman <owner@example.test>' and not notice.targets.exists()
    assert not notice.public and not notice.general and not Notification.objects.exists()
    assert delivery.team_id is None and delivery.recipient=='owner@example.test'
    assert 'Dear Peyman,' in delivery.body and '/portal/' not in delivery.body
    assert delivery.subject=='RoboCup ASR 2026 - Junior Rescue Simulation - Format review'
    assert 'Best regards,\nRoboCup ASR 2026 Organizing Team\nJunior Rescue Simulation League' in delivery.body
    edit=client.get(f'/control/?editor=notice&notice={notice.pk}').content.decode()
    assert 'Peyman &lt;owner@example.test&gt;' in edit
    # Saving an edit without the email checkbox must not send another copy.
    response=client.post('/control/?editor=notice',data(record_id=notice.pk,send_email='',title='Revised topic'),HTTP_X_ASR_EDITOR='1')
    assert response.status_code==200 and EmailDelivery.objects.count()==1
    notice.refresh_from_db();assert notice.title=='Revised topic'
    assert EmailDelivery.objects.get().expires_at is not None
    response=client.post('/control/?editor=notice',data(record_id=notice.pk),HTTP_X_ASR_EDITOR='1')
    assert response.status_code==200 and EmailDelivery.objects.count()==2
    for user in [None,*users]:
        if user: client.force_login(user)
        else: client.logout()
        assert b'owner@example.test' not in client.get('/').content
        if user:
            assert b'Format review' not in client.get('/portal/announcements/').content
            assert client.get('/control/?editor=notice').status_code==302


def test_direct_recipients_dedupe_validation_and_team_greetings(event):
    c,r,teams,users,staff=event
    assert announcement_recipients('Peyman <OWNER@example.test>\nowner@example.test\nmentor@example.test')==[
        {'name':'Peyman','email':'OWNER@example.test'},{'name':'','email':'mentor@example.test'}]
    for value in ['not an address','Name <one@example.test> <two@example.test>',
                  'one@example.test\r\nBcc: other@example.test','Name <one@example.test>junk']:
        with pytest.raises(ValidationError): announcement_recipients(value)
        form=ManageAnnouncementForm(data(email_recipients=value),competition=c)
        assert not form.is_valid() and set(form.errors)=={'email_recipients'}
    notice=announce(user=staff,competition=c,title='Briefing\n update',body='<script>unsafe</script>',general=False,
        public=False,target_ids=[teams[0].pk],email_recipients=f'Duplicate <{teams[0].leader_email}>\nNew Mentor <extra@example.test>')
    assert EmailDelivery.objects.count()==2 and Notification.objects.count()==1
    assert EmailDelivery.objects.get(team=teams[0]).body.startswith(f'Dear {teams[0].name} Mentor,')
    extra=EmailDelivery.objects.get(team=None)
    assert 'Dear New Mentor,' in extra.html_body and '&lt;script&gt;' in extra.html_body and '/portal/' not in extra.html_body
    assert '\n' not in extra.subject
    queue_announcement_copy(notice,notice.targets.all(),resend=True)
    assert EmailDelivery.objects.count()==4


def test_embedded_original_logo_and_announcement_copies_do_not_affect_reset(event,settings):
    settings.DEBUG=True
    EmailConfiguration.objects.create(enabled=True,sender_email='asr@example.test',host='smtp.example.test',
        announcement_cc='organizer@example.test',announcement_bcc='observer@example.test')
    announce(user=event[4],competition=event[0],title='Sample',body='Please review.',general=False,
        public=False,target_ids=[],email_recipients='Peyman <owner@example.test>')
    EmailDelivery.objects.create(dedupe_key='password-reset:private',recipient='owner@example.test',subject='Reset',body='Private')
    with patch('arena.management.commands.deliver_mail.mail_connection',return_value=(mail.get_connection(),'asr@example.test')):
        call_command('deliver_mail',stdout=StringIO())
    announcement,reset=mail.outbox
    assert announcement.to==['owner@example.test'] and announcement.cc==['organizer@example.test'] and announcement.bcc==['observer@example.test']
    mime=announcement.message()
    image=next(part for part in mime.walk() if part.get_content_type()=='image/png')
    assert image['Content-ID']=='<asr-2026-logo>' and image.get_content_disposition()=='inline'
    original=Path(__file__).resolve().parents[1]/'static/arena/brand/asr-email.png'
    assert image.get_payload(decode=True)==original.read_bytes()
    assert 'cid:asr-2026-logo' in announcement.alternatives[0].content
    assert 'text-align:left' in announcement.alternatives[0].content
    assert not reset.cc and not reset.bcc and not reset.attachments
