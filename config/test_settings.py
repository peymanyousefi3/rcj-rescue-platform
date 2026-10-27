import os
os.environ.setdefault('DJANGO_DEBUG','1')
os.environ.setdefault('DJANGO_SECRET_KEY','test-only-key-do-not-use-in-production')
from .settings import *  # noqa: F403
REQUIRE_STAFF_OTP = False
AXES_ENABLED = False
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
STORAGES = {
    'default': {'BACKEND':'django.core.files.storage.FileSystemStorage','OPTIONS':{'location':str(BASE_DIR/'var/test-private')}},
    'staticfiles': {'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
ALLOWED_HOSTS = ['testserver','localhost','127.0.0.1']
