import re
import pytest
from django.core import mail
from arena.control_forms import ManageAnnouncementForm
from arena.models import Announcement, Challenge, EmailDelivery, Notification, Team
from arena.services import announce
from arena.templatetags.announcements import announcement_bold

pytestmark = pytest.mark.django_db


def pairs(event):
    c, _, teams, _, _ = event
    challenge = Challenge.objects.create(competition=c, name='Relay', category='superteam')
    others = [Team.objects.create(competition=c, code=f'OTHER{i}', name=f'Other {i}', leader_email=f'other{i}@example.test') for i in range(2)]
    groups = [Team.objects.create(competition=c, code=f'PAIR{i}', name=f'Pair {i}', superteam_challenge=challenge) for i in range(2)]
    groups[0].members.set(teams)
    groups[1].members.set(others)
    return others, groups


def test_unchecked_superteams_stay_excluded_on_send_edit_and_reopen(client, event):
    c, _, teams, users, admin = event
    others, groups = pairs(event)
    regular = teams + others
    client.force_login(admin)
    data = dict(form='notice', title='Individual notice', body='**Bring your files**', recipient_module='1',
                targets=[str(t.pk) for t in regular], send_email='on')
    assert client.post('/control/', data).status_code == 302
    notice = Announcement.objects.get()
    assert not notice.general
    assert set(notice.targets.all()) == set(regular)
    assert set(Notification.objects.values_list('team_id', flat=True)) == {t.pk for t in regular}
    form = ManageAnnouncementForm(competition=c, notice=notice)
    assert set(map(str, form['targets'].value())) == {str(t.pk) for t in regular}
    assert set(EmailDelivery.objects.values_list('team_id', flat=True)) == {t.pk for t in regular}
    assert EmailDelivery.objects.count() == len(regular)
    # Start with every profile, then deselect both groups in the same editor.
    all_notice = announce(user=admin, competition=c, title='Original all', body='Before', general=True, public=False, target_ids=[], queue_email=False)
    assert set(all_notice.targets.all()) == set(regular + groups)
    data.update(record_id=all_notice.pk, title='Edited selection', send_email='')
    assert client.post('/control/', data).status_code == 302
    all_notice.refresh_from_db()
    assert not all_notice.general and set(all_notice.targets.all()) == set(regular)
    assert not all_notice.notification_set.filter(team__in=groups).exists()
    assert set(map(str, ManageAnnouncementForm(competition=c, notice=all_notice)['targets'].value())) == {str(t.pk) for t in regular}
    client.force_login(users[0])
    assert b'Individual notice' in client.get('/portal/announcements/').content
    assert b'Individual notice' not in client.get(f'/portal/superteams/{groups[0].pk}/announcements/').content
    assert not mail.outbox


def test_legacy_all_notice_reopens_with_actual_saved_recipients(event):
    c, _, teams, _, admin = event
    notice = announce(user=admin, competition=c, title='Before pair creation', body='Saved', general=True, public=False, target_ids=[], queue_email=False)
    pairs(event)
    form = ManageAnnouncementForm(competition=c, notice=notice)
    assert set(map(str, form['targets'].value())) == {str(t.pk) for t in teams}


def test_bold_is_safe_and_consistent_in_home_dashboard_admin_and_email(client, event):
    c, _, teams, users, admin = event
    body = 'Please **bring <script>alert(1)</script>**.\n**On time**; unmatched ** remains.'
    notice = announce(user=admin, competition=c, title='Formatted notice', body=body, general=False, public=True, target_ids=[teams[0].pk])
    expected = '<strong>bring &lt;script&gt;alert(1)&lt;/script&gt;</strong>'
    html = client.get('/').content.decode()
    assert expected in html and '<strong>On time</strong>' in html and 'unmatched ** remains' in html
    assert '<aside class="programme-announcements"' in html
    assert ' open' not in re.search(r'<details[^>]+data-programme-notice=[^>]*>', html).group()
    client.force_login(users[0])
    assert expected in client.get('/portal/announcements/').content.decode()
    assert expected in client.get('/notices/fragment/').json()['html']
    client.force_login(admin)
    assert expected in client.get('/control/').content.decode()
    delivery = EmailDelivery.objects.get()
    assert expected in delivery.html_body and '**On time**' not in delivery.body and 'On time' in delivery.body
    assert '<script>' not in str(announcement_bold('**<script>** <img>'))
    assert str(announcement_bold('plain **unfinished')) == 'plain **unfinished'


def test_superteam_setup_is_nested_in_team_accounts(client, event):
    client.force_login(event[4])
    html = client.get('/control/').content.decode()
    accounts = html.split('id="accounts"', 1)[1].split('id="competition-settings"', 1)[0]
    assert '<section class="team-groups" id="superteams"' in accounts
    assert '<a href="#superteams">' not in html and '<a href="#accounts">' in html
