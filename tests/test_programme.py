import datetime as dt
from html.parser import HTMLParser

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from arena.models import Announcement, Competition, Programme, Round, Team
from arena.programme import programme_context


def seed_programme(event):
    competition, round_, teams, *_ = event
    marker = Programme.objects.create(competition=competition, source_key='quarantine',
        title='Quarantine due', starts_at=round_.quarantine_at,
        ends_at=round_.quarantine_at + dt.timedelta(minutes=15))
    runs = [Programme.objects.create(competition=competition, source_key=f'run-{index}',
        title='Round 1', round=round_, team=team, field='A',
        starts_at=round_.starts_at + dt.timedelta(minutes=15 * index),
        ends_at=round_.starts_at + dt.timedelta(minutes=15 * (index + 1)))
        for index, team in enumerate(teams)]
    return competition, round_, marker, runs


class ProgrammeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        start = dt.datetime(2026, 10, 23, 15, tzinfo=dt.timezone.utc)
        competition = Competition.objects.create(starts_at=start-dt.timedelta(days=1), ends_at=start+dt.timedelta(days=3))
        round_ = Round.objects.create(competition=competition, number=1, opens_at=start-dt.timedelta(hours=3),
            quarantine_at=start-dt.timedelta(minutes=15), starts_at=start, ends_at=start+dt.timedelta(hours=1))
        teams = [Team.objects.create(competition=competition, code=f'{code}CA', name=f'Team {code}',
            country='Canada', leader_email=f'leader{code}@example.test') for code in [101, 102]]
        cls.event = (competition, round_, teams)

    def test_round_group_has_one_deadline_and_preserves_order(self):
        competition, round_, marker, runs = seed_programme(self.event)
        context = programme_context([marker, *runs], competition)
        blocks = [block for day in context['programme_days'] for block in day['blocks']]
        assert len(blocks) == 1
        assert blocks[0]['round'] == round_
        assert blocks[0]['runs'] == runs


    def test_unmatched_quarantine_marker_is_not_hidden(self):
        competition, _, marker, _ = seed_programme(self.event)
        marker.starts_at += dt.timedelta(minutes=1)
        context = programme_context([marker], competition)
        assert any(block.get('event')==marker for day in context['programme_days'] for block in day['blocks'])


    def test_programme_versions_change_with_schedule_and_team_names(self):
        competition, _, marker, runs = seed_programme(self.event)
        original = programme_context([marker, *runs], competition)['programme_version']
        runs[0].starts_at += dt.timedelta(minutes=1)
        changed_time = programme_context([marker, *runs], competition)['programme_version']
        assert original != changed_time
        runs[0].team.name = 'New public team name'
        assert changed_time != programme_context([marker, *runs], competition)['programme_version']


    def test_public_and_fragment_use_new_design_and_exclude_private_data(self):
        _, _, _, runs = seed_programme(self.event)
        day = timezone.localtime(runs[0].starts_at).date().isoformat()
        for path in ['/', '/schedule/', '/schedule/fragment/']:
            response = self.client.get(path, {'day': day})
            assert response.status_code == 200
            html = response.content.decode()
            assert 'aria-orientation="vertical"' in html
            assert 'data-programme-round=' in html
            assert 'Quarantine' in html
            assert 'Organizer-managed schedule' in html
            assert 'leader101@example.test' not in html
            assert 'ASR<span>/26' not in html
            assert 'href="/playbacks/"' not in html
            assert 'data-programme-day="' + day + '"' in html
            class RoundDetails(HTMLParser):
                def __init__(self):
                    super().__init__(); self.rounds=[]
                def handle_starttag(self,tag,attrs):
                    attrs=dict(attrs)
                    if tag=='details' and 'data-programme-round' in attrs:
                        self.rounds.append(attrs)
            parser=RoundDetails();parser.feed(html)
            assert parser.rounds and all('open' not in attrs for attrs in parser.rounds)


    def test_fragment_rejects_post_without_changing_schedule(self):
        seed_programme(self.event)
        assert self.client.post('/schedule/fragment/').status_code == 405
        assert Programme.objects.count() == 3


    def test_notice_board_keeps_public_titles_visible_and_bodies_collapsed(self):
        competition, *_ = seed_programme(self.event)
        staff=get_user_model().objects.create_user(username='organizer',is_staff=True)
        for index in range(2):
            Announcement.objects.create(competition=competition,title=f'Public update {index}',
                body='Escaped <script>bad()</script> content',public=True,author=staff,
                created_at=timezone.now()+dt.timedelta(seconds=index))
        Announcement.objects.create(competition=competition,title='Private team briefing',
            body='Confidential instructions',public=False,author=staff)
        html=self.client.get('/').content.decode()
        assert 'id="league-announcements"' in html and 'View team notices' in html
        assert 'Public update 0' in html and 'Public update 1' in html
        assert 'Private team briefing' not in html and 'Confidential instructions' not in html
        assert '<script>bad()</script>' not in html and '&lt;script&gt;bad()&lt;/script&gt;' in html
        class Notices(HTMLParser):
            def __init__(self):
                super().__init__();self.open=[]
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='details' and 'data-programme-notice' in attrs:
                    self.open.append('open' in attrs)
        parser=Notices();parser.feed(html)
        assert parser.open==[False,False]
