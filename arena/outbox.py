"""Backpressure for the durable outbox; messages are not sent in request handlers."""
from django.conf import settings
from django.core.exceptions import ValidationError
from .models import EmailDelivery
from django.db.models import Q
from django.utils import timezone


def queue_delivery(**values):
    # The bound may overshoot by already-running requests, not by an unbounded backlog.
    if EmailDelivery.objects.filter(sent_at=None,attempts__lt=12).filter(Q(expires_at=None)|Q(expires_at__gt=timezone.now())).count() >= settings.MAIL_MAX_PENDING:
        raise ValidationError('The outgoing queue is full. Try again later or contact the organizer.')
    return EmailDelivery.objects.create(**values)
