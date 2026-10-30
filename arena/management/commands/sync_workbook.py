import hashlib
import io
import os
import re
from urllib.parse import urljoin,urlsplit
from pathlib import Path
import requests
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from google.auth import default
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from arena.models import Competition, AuditEvent
from arena.workbook import apply_snapshot, parse_workbook


def download_shared_workbook(identifier):
    if not identifier or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',identifier):
        raise CommandError('SOURCE_WORKBOOK_ID must be a Google file identifier.')
    url='https://drive.google.com/uc';params={'export':'download','id':identifier}
    for attempt in range(5):
        parsed=urlsplit(url);host=(parsed.hostname or '').lower()
        if (parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443)
                or not (host.endswith('.google.com') or host.endswith('.googleusercontent.com'))):
            raise CommandError('Workbook redirect left the approved Google download hosts.')
        with requests.get(url,params=params,allow_redirects=False,stream=True,timeout=20) as response:
            if response.status_code in [301,302,303,307,308]:
                url=urljoin(url,response.headers['Location']);params=None;continue
            response.raise_for_status();content=bytearray()
            for chunk in response.iter_content(1024*1024):
                content.extend(chunk)
                if len(content)>10*1024*1024:raise CommandError('Workbook too large.')
            return bytes(content)
    raise CommandError('Too many workbook redirects.')


class Command(BaseCommand):
    help='Sync a validated private Drive XLSX or native Google Sheet; preserve last good data on errors.'
    def add_arguments(self,parser):
        parser.add_argument('--file',type=Path)
        parser.add_argument('--initial-past-import',action='store_true')
    def handle(self,*args,**options):
        competition=Competition.objects.get(slug='asr26')
        if not competition.workbook_enabled:
            self.stdout.write('Workbook updates paused; competition data is managed in the admin panel.');return
        if options['file']:
            if options['file'].stat().st_size>10*1024*1024: raise CommandError('Workbook too large.')
            content=options['file'].read_bytes()
        elif os.getenv('SOURCE_WORKBOOK_ACCESS') == 'shared_link':
            content=download_shared_workbook(os.getenv('SOURCE_WORKBOOK_ID'))
        else:
            identifier=os.getenv('SOURCE_WORKBOOK_ID')
            if not identifier: raise CommandError('SOURCE_WORKBOOK_ID is not configured.')
            credentials,_=default(scopes=['https://www.googleapis.com/auth/drive.readonly'])
            drive=build('drive','v3',credentials=credentials,cache_discovery=False)
            meta=drive.files().get(fileId=identifier,fields='mimeType,size',supportsAllDrives=True).execute()
            if int(meta.get('size',0))>10*1024*1024: raise CommandError('Workbook too large.')
            if meta['mimeType']=='application/vnd.google-apps.spreadsheet':
                request=drive.files().export_media(fileId=identifier,mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            elif meta['mimeType']=='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
                request=drive.files().get_media(fileId=identifier,supportsAllDrives=True)
            else: raise CommandError('Expected XLSX or native Google Sheet.')
            stream=io.BytesIO()
            transfer=MediaIoBaseDownload(stream,request,chunksize=1024*1024)
            done=False
            while not done:
                _,done=transfer.next_chunk(num_retries=2)
                if stream.tell()>10*1024*1024: raise CommandError('Workbook too large.')
            content=stream.getvalue()
        digest=hashlib.sha256(content).hexdigest()
        if digest==competition.workbook_digest:
            self.stdout.write('Workbook unchanged.');return
        try:
            snapshot=parse_workbook(content,year=competition.starts_at.year)
            count=apply_snapshot(snapshot,digest,competition,allow_initial_deadlines=options['initial_past_import'])
        except (ValidationError,ValueError,KeyError,IndexError) as exc:
            raise CommandError('Workbook rejected; last good data retained: '+str(exc)) from exc
        AuditEvent.objects.create(action='workbook.synced',sha256=digest,detail={'events':count,'score_mode':snapshot['mode']})
        self.stdout.write(f'Synchronized {count} programme entries; score mode: {snapshot["mode"]}.')
