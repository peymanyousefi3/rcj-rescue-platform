"""Create an untracked local Docker configuration. Never overwrite existing secrets."""
from pathlib import Path
import os,secrets
root=Path(__file__).resolve().parents[1]
target=root/'.env'
if target.exists():raise SystemExit('.env already exists; nothing was changed.')
values={'DJANGO_DEBUG':'1','DJANGO_SECRET_KEY':secrets.token_urlsafe(64),'POSTGRES_PASSWORD':secrets.token_urlsafe(32),'APP_DB_PASSWORD':secrets.token_urlsafe(32),'PROXY_SHARED_SECRET':secrets.token_urlsafe(48),'DJANGO_ALLOWED_HOSTS':'localhost,127.0.0.1','PUBLIC_ORIGIN':'http://127.0.0.1:8000','STORAGE_BACKEND':'local','CLAMAV_HOST':'clamav','REQUIRE_STAFF_OTP':'0'}
fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as file:file.write(''.join(f'{key}={value}\n' for key,value in values.items()))
print('Created private local .env. No administrator account or shared password was created.')
