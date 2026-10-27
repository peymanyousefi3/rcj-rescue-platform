from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection,connections
from arena.models import Asset,AuditEvent
from arena.services import upload_asset

@pytest.mark.django_db(transaction=True)
def test_concurrent_replacements_preserve_one_current_version(event):
    if connection.vendor!='postgresql': pytest.skip('Row-lock race requires PostgreSQL.')
    barrier=Barrier(2)
    save=default_storage.save
    def overlap(*args,**kwargs):
        key=save(*args,**kwargs)
        barrier.wait(timeout=10)
        return key
    def submit(index):
        connections.close_all()
        try:
            return upload_asset(user=event[3][0],team=event[2][0],round_=event[1],kind='round_code',
                file=SimpleUploadedFile(f'v{index}.bin',f'version-{index}'.encode()),attested=True).pk
        finally: connections.close_all()
    with patch('arena.services.default_storage.save',side_effect=overlap):
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids=list(pool.map(submit,[1,2]))
    assert len(set(ids))==2
    assert Asset.objects.count()==2
    assert Asset.objects.filter(current=True).count()==1
    assert AuditEvent.objects.filter(action='file.uploaded').count()==2
    assert AuditEvent.objects.filter(action='file.superseded').count()==1


@pytest.mark.django_db(transaction=True)
def test_concurrent_quarantine_replacement_accepts_only_one_writer(event):
    if connection.vendor!='postgresql': pytest.skip('Row-lock race requires PostgreSQL.')
    import datetime as dt
    from django.utils import timezone
    from django.core.exceptions import PermissionDenied
    from arena.services import save_quarantine,upload_quarantine_files
    quarantine=save_quarantine(user=event[4],competition=event[0],name='Concurrent quarantine',
        instructions='',deadline=timezone.now()+dt.timedelta(hours=1),all_teams=True,targets=[])
    original=upload_quarantine_files(user=event[3][0],team=event[2][0],quarantine=quarantine,
        files=[SimpleUploadedFile('original.bin',b'original')])[0]
    barrier=Barrier(2)
    def submit(index):
        connections.close_all()
        try:
            barrier.wait(timeout=10)
            try:
                return upload_quarantine_files(user=event[3][0],team=event[2][0],quarantine=quarantine,
                    files=[SimpleUploadedFile(f'v{index}.bin',b'replacement')],replacement_id=original.pk)[0].pk
            except PermissionDenied:
                return None
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids=list(pool.map(submit,[1,2]))
    assert sum(pk is not None for pk in ids)==1
    assert Asset.objects.filter(quarantine=quarantine).count()==2
    assert Asset.objects.filter(quarantine=quarantine,current=True).count()==1
    assert AuditEvent.objects.filter(action='file.superseded').count()==1
