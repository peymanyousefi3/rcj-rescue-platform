"""Reject over-budget multipart bodies before temporary storage or form side effects."""
import shutil
import tempfile
from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.core.files.uploadhandler import FileUploadHandler


class BoundedUploadHandler(FileUploadHandler):
    chunk_size = 64 * 1024
    def __init__(self, request=None):
        super().__init__(request)
        self.total = self.count = self.disk_checked = 0
    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.file_bytes = 0
        self.count += 1
        if self.count > settings.UPLOAD_MAX_FILES:
            raise RequestDataTooBig('Too many files in one upload.')
    def receive_data_chunk(self, raw_data, start):
        self.file_bytes += len(raw_data)
        self.total += len(raw_data)
        if self.file_bytes > settings.UPLOAD_MAX_FILE_BYTES or self.total > settings.UPLOAD_MAX_BATCH_BYTES:
            raise RequestDataTooBig('Upload exceeds the configured file/batch budget.')
        if not self.disk_checked or self.total - self.disk_checked >= 1024**2:
            if shutil.disk_usage(settings.FILE_UPLOAD_TEMP_DIR).free < settings.UPLOAD_MIN_FREE_BYTES:
                raise RequestDataTooBig('Temporary upload storage is unavailable.')
            self.disk_checked = self.total
        return raw_data
    def file_complete(self, file_size):
        return None
