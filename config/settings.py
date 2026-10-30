import os
import secrets
from datetime import timedelta
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv('DJANGO_DEBUG') == '1'
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', '')
if not SECRET_KEY and not DEBUG:
    raise ImproperlyConfigured('DJANGO_SECRET_KEY is required outside local development.')
SECRET_KEY = SECRET_KEY or secrets.token_urlsafe(64)
ALLOWED_HOSTS = [s.strip() for s in os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if s.strip()]
CSRF_TRUSTED_ORIGINS = [s for s in os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if s]
PUBLIC_ORIGIN = os.getenv('PUBLIC_ORIGIN', 'http://127.0.0.1:8000' if DEBUG else '').rstrip('/')
if not DEBUG and not PUBLIC_ORIGIN.startswith('https://'):
    raise ImproperlyConfigured('PUBLIC_ORIGIN must be an HTTPS origin.')
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'django_otp', 'django_otp.plugins.otp_static', 'django_otp.plugins.otp_totp',
    'two_factor', 'axes', 'arena.apps.ArenaConfig',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware', 'whitenoise.middleware.WhiteNoiseMiddleware',
    'arena.middleware.ProxyAddressMiddleware', 'arena.middleware.UploadBoundaryMiddleware',
    'arena.middleware.ReplaySessionMiddleware', 'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware', 'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware', 'axes.middleware.AxesMiddleware',
    'arena.middleware.SecurityBoundaryMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True,
    'OPTIONS': {'context_processors': ['django.template.context_processors.request',
    'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages',
    'arena.context.site_context']}}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': dj_database_url.config(default=f'sqlite:///{BASE_DIR / "var/db.sqlite3"}', conn_max_age=0)}
if not DEBUG and DATABASES['default']['ENGINE'] != 'django.db.backends.postgresql':
    raise ImproperlyConfigured('Production requires PostgreSQL for transactional upload locks.')
if DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql':
    DATABASES['default'].setdefault('OPTIONS', {}).update({
        'pool': {'min_size': 0, 'max_size': int(os.getenv('DB_POOL_MAX_SIZE', '4')),
                 'timeout': 10, 'max_waiting': 16},
        'options': '-c statement_timeout=30000 -c lock_timeout=10000 -c idle_in_transaction_session_timeout=60000',
    })
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 14}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
PASSWORD_HASHERS = ['django.contrib.auth.hashers.Argon2PasswordHasher', 'django.contrib.auth.hashers.PBKDF2PasswordHasher']
AUTHENTICATION_BACKENDS = ['axes.backends.AxesStandaloneBackend', 'django.contrib.auth.backends.ModelBackend']
AXES_FAILURE_LIMIT = 8
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_LOCKOUT_PARAMETERS = [['username', 'ip_address']]
AXES_RESET_ON_SUCCESS = True
AXES_SENSITIVE_PARAMETERS = ['username', 'password', 'otp_token']
AXES_IPWARE_PROXY_COUNT = 0
REQUIRE_STAFF_OTP = os.getenv('REQUIRE_STAFF_OTP', '0' if DEBUG else '1') == '1'
LOGIN_URL = 'two_factor:login'
LOGIN_REDIRECT_URL = '/portal/'
LOGOUT_REDIRECT_URL = '/'
PASSWORD_RESET_TIMEOUT = 3600
LANGUAGE_CODE = 'en-ca'
TIME_ZONE = 'America/Toronto'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
CACHES = {'default': {'BACKEND':'django.core.cache.backends.locmem.LocMemCache',
    'TIMEOUT':300,'OPTIONS':{'MAX_ENTRIES':16}}}
PRIVATE_ROOT = BASE_DIR / 'var/private'
FILE_UPLOAD_TEMP_DIR = str(PRIVATE_ROOT / '.upload-tmp')
Path(FILE_UPLOAD_TEMP_DIR).mkdir(parents=True, exist_ok=True, mode=0o700)
FILE_UPLOAD_PERMISSIONS = 0o600
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o700
STORAGE_BACKEND = os.getenv('STORAGE_BACKEND', 'local')
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage', 'OPTIONS': {'location': str(PRIVATE_ROOT)}},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
if STORAGE_BACKEND == 's3':
    STORAGES['default'] = {'BACKEND': 'storages.backends.s3.S3Storage', 'OPTIONS': {
        'access_key': os.environ['AWS_ACCESS_KEY_ID'], 'secret_key': os.environ['AWS_SECRET_ACCESS_KEY'],
        'bucket_name': os.environ['AWS_STORAGE_BUCKET_NAME'], 'endpoint_url': os.environ['AWS_S3_ENDPOINT_URL'],
        'region_name': os.getenv('AWS_S3_REGION_NAME', 'auto'), 'default_acl': None,
        'file_overwrite': False, 'querystring_auth': True,
    }}
elif STORAGE_BACKEND == 'drive':
    STORAGES['default'] = {'BACKEND': 'arena.drive_storage.PrivateDriveStorage'}
elif STORAGE_BACKEND != 'local':
    raise ImproperlyConfigured('Unsupported private storage backend.')
FILE_UPLOAD_MAX_MEMORY_SIZE = 512 * 1024
# Generous, configurable resource budgets; file types remain unrestricted for private submissions.
UPLOAD_MAX_FILE_BYTES = int(os.getenv('UPLOAD_MAX_FILE_BYTES', str(1024**3)))
UPLOAD_MAX_BATCH_BYTES = int(os.getenv('UPLOAD_MAX_BATCH_BYTES', str(2*1024**3)))
UPLOAD_MAX_FILES = int(os.getenv('UPLOAD_MAX_FILES', '5000'))
UPLOAD_TEAM_MAX_BYTES = int(os.getenv('UPLOAD_TEAM_MAX_BYTES', str(20*1024**3)))
UPLOAD_MIN_FREE_BYTES = int(os.getenv('UPLOAD_MIN_FREE_BYTES', str(512*1024**2)))
RECORDING_MAX_EXTRACTED_BYTES = int(os.getenv('RECORDING_MAX_EXTRACTED_BYTES', str(512*1024**2)))
VALIDATION_MAX_BYTES = int(os.getenv('VALIDATION_MAX_BYTES', str(64*1024**2)))
IMAGE_MAX_PIXELS = int(os.getenv('IMAGE_MAX_PIXELS','16000000'))
if any(value<=0 for value in [UPLOAD_MAX_FILE_BYTES,UPLOAD_MAX_BATCH_BYTES,UPLOAD_MAX_FILES,UPLOAD_TEAM_MAX_BYTES,UPLOAD_MIN_FREE_BYTES,RECORDING_MAX_EXTRACTED_BYTES,VALIDATION_MAX_BYTES,IMAGE_MAX_PIXELS]):
    raise ImproperlyConfigured('Upload, storage and validation budgets must be positive.')
FILE_UPLOAD_HANDLERS = ['arena.uploads.BoundedUploadHandler',
                        'django.core.files.uploadhandler.TemporaryFileUploadHandler']
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FILES = UPLOAD_MAX_FILES
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = True
EMAIL_TIMEOUT = 20
MAIL_MAX_PENDING = int(os.getenv('MAIL_MAX_PENDING','10000'))
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'no-reply@localhost' if DEBUG else '')
SESSION_COOKIE_NAME = 'asr_session'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 3600
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
REMEMBER_SESSION_AGE = 30 * 24 * 60 * 60
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
if os.getenv('TRUST_PROXY_HTTPS') == '1':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
TRUST_PROXY_CLIENT_IP = os.getenv('TRUST_PROXY_CLIENT_IP', '0') == '1'
PROXY_SHARED_SECRET = os.getenv('PROXY_SHARED_SECRET', '')
if TRUST_PROXY_CLIENT_IP and len(PROXY_SHARED_SECRET) < 32:
    raise ImproperlyConfigured('Trusted client-IP forwarding requires a fresh PROXY_SHARED_SECRET of at least 32 characters.')
LOGGING = {'version': 1, 'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'WARNING'}}
