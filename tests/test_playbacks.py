"""Playback pages use uploaded recordings in a modal, never legacy external URLs."""
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from arena.forms import PlaybackForm
from arena.models import Competition, Round

@override_settings(SECURE_SSL_REDIRECT=False, REQUIRE_STAFF_OTP=False, STORAGES={'default':{'BACKEND':'django.core.files.storage.InMemoryStorage'},'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class PlaybackTests(TestCase):
    def setUp(self):
        now=timezone.now()
        self.competition=Competition.objects.create(starts_at=now-timedelta(days=2),ends_at=now+timedelta(days=2))
        self.round=Round.objects.create(competition=self.competition,number=1,opens_at=now-timedelta(days=1),quarantine_at=now-timedelta(hours=3),starts_at=now-timedelta(hours=2),ends_at=now-timedelta(hours=1),playback_url='https://recordings.example.test/round-1/index.html')
        self.staff=get_user_model().objects.create_user(username='playback-organizer',is_staff=True)

    def test_legacy_urls_never_rendered_or_embedded_even_when_released(self):
        for completed,released in [(False,False),(True,False),(False,True)]:
            self.round.completed=completed;self.round.playback_released=released;self.round.save()
            response=self.client.get('/playbacks/')
            self.assertEqual(response.status_code,200)
            self.assertNotContains(response,self.round.playback_url)
            self.assertNotIn('recordings.example.test',response['Content-Security-Policy'])
        self.round.completed=True;self.round.playback_released=True;self.round.save()
        response=self.client.get('/playbacks/')
        self.assertNotContains(response,self.round.playback_url)
        self.assertNotContains(response,'Open recording in a new tab')
        self.assertContains(response,'data-replay-dialog')
        self.assertIn("frame-src 'self';",response['Content-Security-Policy'])
        self.assertNotIn('recordings.example.test',self.client.get('/')['Content-Security-Policy'])

    def test_explicit_completion_allows_early_release_but_release_flag_alone_does_not(self):
        self.round.completed=True;self.round.playback_released=True;self.round.ends_at=timezone.now()+timedelta(hours=1);self.round.save()
        self.assertTrue(self.round.playback_open)
        self.assertNotContains(self.client.get('/playbacks/'),self.round.playback_url)
        form=PlaybackForm({'round':self.round.pk,'playback_url':self.round.playback_url,'released':'on'},competition=self.competition)
        self.assertTrue(form.is_valid())
        self.round.completed=False;self.round.save()
        self.assertFalse(self.round.playback_open)
        form=PlaybackForm({'round':self.round.pk,'playback_url':self.round.playback_url,'released':'on'},competition=self.competition)
        self.assertFalse(form.is_valid())

    def test_organizer_can_save_publish_and_withdraw_after_completion(self):
        self.round.completed=True;self.round.save()
        self.client.force_login(self.staff)
        data={'form':'playback','round':self.round.pk,'playback_url':self.round.playback_url,'released':'on'}
        self.assertEqual(self.client.post('/control/',data).status_code,302)
        self.round.refresh_from_db();self.assertTrue(self.round.playback_open)
        del data['released'];self.client.post('/control/',data)
        self.round.refresh_from_db();self.assertFalse(self.round.playback_open)

    def test_anonymous_cannot_configure_recordings(self):
        response=self.client.post('/control/',{'form':'playback','round':self.round.pk,'playback_url':'https://other.example.test/index.html'})
        self.assertEqual(response.status_code,302)
        self.round.refresh_from_db();self.assertEqual(self.round.playback_url,'https://recordings.example.test/round-1/index.html')

    def test_only_https_urls_without_embedded_credentials_are_accepted(self):
        for url in ['http://recordings.example.test/index.html','javascript:alert(1)','https://user:password@recordings.example.test/index.html']:
            form=PlaybackForm({'round':self.round.pk,'playback_url':url},competition=self.competition)
            self.assertFalse(form.is_valid(),url)
