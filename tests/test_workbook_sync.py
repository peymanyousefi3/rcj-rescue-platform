from unittest.mock import MagicMock, patch

import pytest
import requests
from django.core.management import call_command
from django.core.management.base import CommandError

from arena.models import AuditEvent, Competition, Programme, Round
from tests.test_workbook import public_workbook


@pytest.mark.django_db
def test_shared_link_sync_uses_validated_workbook(event, monkeypatch):
    monkeypatch.setenv('SOURCE_WORKBOOK_ID', 'verified-workbook-id')
    monkeypatch.setenv('SOURCE_WORKBOOK_ACCESS', 'shared_link')
    response = MagicMock()
    response.__enter__.return_value = response
    response.iter_content.return_value = [public_workbook()]
    with patch('arena.management.commands.sync_workbook.requests.get', return_value=response) as get:
        # The fixed October fixture can contain past deadlines as the event proceeds.
        call_command('sync_workbook', initial_past_import=True)
    get.assert_called_once_with('https://drive.google.com/uc',
        params={'export': 'download', 'id': 'verified-workbook-id'}, stream=True, timeout=20)
    assert Programme.objects.count() == 60
    assert Round.objects.get(pk=event[1].pk).opens_at == event[1].opens_at
    assert Competition.objects.get(pk=event[0].pk).workbook_last_synced is not None
    assert AuditEvent.objects.filter(action='workbook.synced').count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize('failure', ['timeout', 'oversized', 'invalid'])
def test_shared_link_failure_preserves_existing_data(event, monkeypatch, failure):
    monkeypatch.setenv('SOURCE_WORKBOOK_ID', 'verified-workbook-id')
    monkeypatch.setenv('SOURCE_WORKBOOK_ACCESS', 'shared_link')
    competition, round_, *_ = event
    Programme.objects.create(competition=competition, source_key='asr26:keep', title='Keep this event',
        starts_at=round_.starts_at, ends_at=round_.ends_at)
    response = MagicMock()
    response.__enter__.return_value = response
    if failure == 'timeout':
        response.iter_content.side_effect = requests.Timeout()
    else:
        response.iter_content.return_value = [b'x' * (10 * 1024 * 1024 + 1) if failure == 'oversized' else public_workbook(mode='Invalid')]
    with patch('arena.management.commands.sync_workbook.requests.get', return_value=response):
        with pytest.raises(requests.Timeout if failure == 'timeout' else CommandError):
            call_command('sync_workbook')
    assert list(Programme.objects.values_list('title', flat=True)) == ['Keep this event']
    competition.refresh_from_db()
    assert competition.workbook_last_synced is None
    assert competition.workbook_digest == ''
    assert not AuditEvent.objects.filter(action='workbook.synced').exists()
