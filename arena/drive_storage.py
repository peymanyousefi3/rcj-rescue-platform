"""Private Drive storage: API only, no public sharing or Drive URLs in responses."""
import os
from django.core.files import File
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible
from google.auth import default
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

@deconstructible
class PrivateDriveStorage(Storage):
    def service(self):
        credentials, _ = default(scopes=['https://www.googleapis.com/auth/drive.file'])
        return build('drive','v3',credentials=credentials,cache_discovery=False)
    def _save(self, name, content):
        # Dedicated folder must be restricted to the service principal. Never use shared competition folders.
        folder = os.environ['GOOGLE_DRIVE_PRIVATE_FOLDER_ID']
        result = self.service().files().create(body={'name': name.split('/')[-1], 'parents':[folder]},
            media_body=MediaIoBaseUpload(content,'application/octet-stream',resumable=True),
            fields='id', supportsAllDrives=True).execute()
        return result['id']
    def _open(self,name,mode='rb'):
        import tempfile
        output = tempfile.SpooledTemporaryFile(max_size=512*1024)
        request = self.service().files().get_media(fileId=name, supportsAllDrives=True)
        download = MediaIoBaseDownload(output,request,chunksize=1024*1024)
        done = False
        while not done:
            _, done = download.next_chunk(num_retries=2)
        output.seek(0)
        return File(output,name=name)
    def exists(self,name):
        # Each UUID object name is new; create() returns a provider-generated ID.
        return False
    def delete(self,name):
        self.service().files().delete(fileId=name, supportsAllDrives=True).execute()
    def size(self,name):
        result = self.service().files().get(fileId=name, fields='size', supportsAllDrives=True).execute()
        return int(result['size'])
    def url(self,name):
        raise NotImplementedError('Private files must pass application authorization.')
