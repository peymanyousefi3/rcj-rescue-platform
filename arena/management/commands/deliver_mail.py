from datetime import timedelta
from email.mime.image import MIMEImage
from pathlib import Path
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.contrib.staticfiles import finders
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from arena.models import EmailConfiguration, EmailDelivery
from arena.mail import mail_connection, recipient_list
from django.core.exceptions import ImproperlyConfigured

class Command(BaseCommand):
    help='Deliver queued invitations and leader announcements with retries. No real mail in DEBUG.'
    def handle(self,*args,**options):
        try:
            connection, sender = mail_connection()
        except ImproperlyConfigured as exc:
            raise CommandError(str(exc)) from None
        config=EmailConfiguration.objects.filter(pk=1).first()
        sent=0
        for _ in range(50):
            with transaction.atomic():
                item=EmailDelivery.objects.select_for_update(of=('self',),skip_locked=True).filter(
                    sent_at=None,next_attempt_at__lte=timezone.now(),attempts__lt=12).filter(
                    Q(expires_at=None) | Q(expires_at__gt=timezone.now())).filter(
                    Q(team=None) | Q(team__active=True)).first()
                if not item: break
                item.attempts+=1
                try:
                    # SMTP is at-least-once. A stable Message-ID helps deduplicate ambiguous retries.
                    # Account recovery and invitations must never copy announcement observers.
                    cc=recipient_list(config.announcement_cc) if config and item.dedupe_key.startswith('announcement:') else []
                    bcc=recipient_list(config.announcement_bcc) if config and item.dedupe_key.startswith('announcement:') else []
                    cc=[address for address in cc if address.lower()!=item.recipient.lower()]
                    bcc=[address for address in bcc if address.lower() not in {item.recipient.lower(),*(address.lower() for address in cc)}]
                    message=EmailMultiAlternatives(item.subject,item.body,from_email=sender,to=[item.recipient],cc=cc,bcc=bcc,connection=connection,
                        headers={'Message-ID':f'<asr26-{item.pk}@{settings.PUBLIC_ORIGIN.split("://")[-1].split("/")[0]}>'})
                    if item.html_body:
                        message.attach_alternative(item.html_body,'text/html')
                        if 'cid:asr-2026-logo' in item.html_body and item.dedupe_key.startswith('announcement:'):
                            logo=MIMEImage(Path(finders.find('arena/brand/asr-email.png')).read_bytes(),_subtype='png')
                            logo.add_header('Content-ID','<asr-2026-logo>')
                            logo.add_header('Content-Disposition','inline',filename='ASR.png')
                            message.mixed_subtype='related'
                            message.attach(logo)
                    if message.send(fail_silently=False) != 1:
                        raise RuntimeError('Email backend did not accept the message.')
                    item.sent_at=timezone.now()
                    item.last_error=''
                    sent+=1
                except Exception as exc:
                    item.last_error=type(exc).__name__
                    item.next_attempt_at=timezone.now()+timedelta(seconds=min(3600,30*2**item.attempts))
                item.save(update_fields=['attempts','sent_at','last_error','next_attempt_at'])
        self.stdout.write(f'{sent} queued messages delivered.')
