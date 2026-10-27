"""Fictional setup must never seed credentials, send mail or overwrite scores."""
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from arena.models import Challenge, Competition, EmailDelivery, Score, Team


@pytest.mark.django_db
def test_fictional_setup_requires_owner_and_refuses_repeat():
    call_command('bootstrap_event')
    competition = Competition.objects.get(slug='asr26')
    assert competition.name == 'Demonstration Rescue Competition'
    assert Team.objects.count() == 5
    assert not get_user_model().objects.exists()
    assert not EmailDelivery.objects.exists()
    with pytest.raises(CommandError, match='administrator'):
        call_command('seed_demo')
    get_user_model().objects.create(username='local-organizer', is_staff=True, is_active=True)
    call_command('seed_demo')
    assert get_user_model().objects.count() == 1
    assert Score.objects.count() == 39
    assert Team.objects.count() == 7
    assert not EmailDelivery.objects.exists()
    assert not Challenge.objects.filter(rankings_released=True).exists()
    with pytest.raises(CommandError, match='already exist'):
        call_command('seed_demo')
    assert Score.objects.count() == 39


@pytest.mark.django_db
def test_demo_refuses_a_real_competition():
    call_command('bootstrap_event')
    Competition.objects.filter(slug='asr26').update(name='Real competition')
    with pytest.raises(CommandError, match='fictional'):
        call_command('seed_demo')
    call_command('bootstrap_event')
    assert Competition.objects.get(slug='asr26').name == 'Real competition'
    assert not Score.objects.exists()
