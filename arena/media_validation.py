"""Bound memory used by JSON, scene, image and script validation."""
from django.conf import settings
from django.core.exceptions import ValidationError


def bounded_read(stream):
    data = stream.read(settings.VALIDATION_MAX_BYTES + 1)
    if len(data) > settings.VALIDATION_MAX_BYTES:
        raise ValidationError('This validation file exceeds the configured processing limit.')
    return data
