import hashlib
import os
import socket
import struct
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import transaction
from arena.models import Asset, AuditEvent

def scan_stream(stream):
    digest=hashlib.sha256()
    with socket.create_connection((os.getenv('CLAMAV_HOST','127.0.0.1'),int(os.getenv('CLAMAV_PORT','3310'))),timeout=15) as sock:
        sock.settimeout(60)
        sock.sendall(b'zINSTREAM\0')
        while True:
            chunk=stream.read(64*1024)
            if not chunk: break
            digest.update(chunk)
            sock.sendall(struct.pack('!I',len(chunk))+chunk)
        sock.sendall(struct.pack('!I',0))
        reply=b''
        while b'\0' not in reply and len(reply)<4096:
            chunk=sock.recv(4096)
            if not chunk: break
            reply+=chunk
    result=reply.rstrip(b'\0').decode('utf-8','replace')
    if result=='stream: OK': return 'clean',digest.hexdigest()
    if result.endswith(' FOUND'): return 'rejected',digest.hexdigest()
    raise OSError('Scanner did not return a complete verdict.')

class Command(BaseCommand):
    help='Scan pending uploads. Scanner failures keep files private and pending.'
    def handle(self,*args,**options):
        for _ in range(20):
            with transaction.atomic():
                asset=Asset.objects.select_for_update(skip_locked=True).filter(scan_status='pending').first()
                if not asset: break
                try:
                    with default_storage.open(asset.blob_key,'rb') as file:
                        status,digest=scan_stream(file)
                    if digest!=asset.sha256: status='rejected'
                    asset.scan_status=status
                    asset.save(update_fields=['scan_status'])
                    AuditEvent.objects.create(action='file.scanned',team=asset.team,object_id=str(asset.pk),
                        sha256=asset.sha256,detail={'status':status})
                except Exception as exc:
                    self.stderr.write(f'Scanning unavailable ({type(exc).__name__}); pending files remain private.')
                    break
