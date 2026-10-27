from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from .models import AuditEvent, Membership

@receiver(user_logged_in)
def login_record(sender, request, user, **kwargs):
    membership = Membership.objects.filter(user=user).first()
    AuditEvent.objects.create(actor=user, team_id=membership.team_id if membership else None, action='auth.login')

@receiver(user_logged_out)
def logout_record(sender, request, user, **kwargs):
    if user:
        AuditEvent.objects.create(actor=user, action='auth.logout')

@receiver(user_login_failed)
def failed_record(sender, credentials, request, **kwargs):
    # Never persist supplied passwords, OTPs, raw cookies or unknown usernames.
    AuditEvent.objects.create(action='auth.failed')
