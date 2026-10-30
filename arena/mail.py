import base64
import hashlib
import re
from email.utils import formataddr

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.mail import get_connection
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email

from .models import EmailConfiguration


def credential_cipher(secret=None):
    # Separate the SMTP encryption key from other uses of Django's strong secret.
    digest = hashlib.sha256(('asr26-smtp:' + (secret or settings.SECRET_KEY)).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def email_ready():
    config = EmailConfiguration.objects.filter(pk=1).first()
    if config:
        return bool(config.enabled and config.host and config.sender_email)
    return bool(settings.EMAIL_HOST and settings.DEFAULT_FROM_EMAIL)


def mail_connection(*, allow_paused=False):
    config = EmailConfiguration.objects.filter(pk=1).first()
    if config is None:
        if not settings.DEBUG and not email_ready():
            raise ImproperlyConfigured('SMTP and sender are not configured; queued messages retained.')
        return get_connection(), settings.DEFAULT_FROM_EMAIL
    if (not config.enabled and not allow_paused) or not config.host or not config.sender_email:
        raise ImproperlyConfigured('Email delivery is paused or incomplete; queued messages retained.')
    password = ''  # nosec B105
    if config.password_encrypted:
        for secret in [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]:
            try:
                password = credential_cipher(secret).decrypt(config.password_encrypted.encode()).decode()
                break
            except InvalidToken:
                continue
        else:
            raise ImproperlyConfigured('Re-enter the SMTP credential after encryption key rotation.')
    connection = get_connection(host=config.host, port=config.port, username=config.username,
        password=password, use_tls=config.security=='starttls', use_ssl=config.security=='ssl', timeout=20)
    return connection, formataddr((config.sender_name, config.sender_email))


def recipient_list(value):
    """Strict address-only list; never allow display names or injected headers."""
    addresses=[]
    for candidate in value.replace(';',',').replace('\n',',').split(','):
        address=candidate.strip()
        if not address: continue
        validate_email(address)
        if address.lower() not in [item.lower() for item in addresses]: addresses.append(address)
    return addresses


def announcement_recipients(value):
    """One address per line, optionally personalized as Name <email>."""
    recipients=[];seen=set()
    for line in value.splitlines():
        line=line.strip()
        if not line: continue
        match=re.fullmatch(r'(?:(?P<name>[^<>]+?)\s*<(?P<email>[^<>]+)>|(?P<plain>[^<>]+))',line)
        if not match:
            raise ValidationError('Enter one email address per line, optionally as Name <email>.')
        name=(match['name'] or '').strip()
        address=(match['email'] or match['plain']).strip()
        validate_email(address)
        if len(name)>120: raise ValidationError('Recipient names must be 120 characters or fewer.')
        if address.lower() not in seen:
            recipients.append({'name':name,'email':address});seen.add(address.lower())
    return recipients
