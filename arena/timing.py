"""Eight-minute run clock: enter remaining time, persist elapsed seconds."""
import re
from django import forms
from django.core.exceptions import ValidationError

RUN_ALLOWANCE_SECONDS = 8 * 60
TIME_ERROR = 'Enter remaining time from 0:00 to 8:00, or whole seconds from 0 to 480.'


def format_clock(seconds):
    if seconds is None:
        return ''
    minutes, seconds = divmod(seconds, 60)
    return f'{minutes}:{seconds:02d}'


def parse_remaining(value):
    value = str(value).strip() if value is not None else ''
    if not value:
        return None
    if re.fullmatch(r'[0-9]{1,3}', value):
        seconds = int(value)
    elif re.fullmatch(r'[0-9]{1,2}:[0-5][0-9]', value):
        minutes, seconds = map(int, value.split(':'))
        seconds += minutes * 60
    else:
        raise ValidationError(TIME_ERROR)
    if seconds > RUN_ALLOWANCE_SECONDS:
        raise ValidationError(TIME_ERROR)
    return seconds


class RemainingTimeField(forms.Field):
    def __init__(self, **kwargs):
        kwargs.setdefault('required', False)
        kwargs.setdefault('label', 'Remaining time')
        kwargs.setdefault('help_text', 'Enter m:ss or whole seconds remaining out of 8:00. Elapsed time is calculated automatically; leave unknown times blank.')
        kwargs.setdefault('widget', forms.TextInput(attrs={'placeholder': 'm:ss', 'maxlength': 5,
            'data-remaining-time': '', 'autocomplete': 'off',
            'pattern': r'([0-9]{1,3}|[0-9]{1,2}:[0-5][0-9])'}))
        super().__init__(**kwargs)

    def to_python(self, value):
        return parse_remaining(value)

    def prepare_value(self, value):
        return format_clock(value) if isinstance(value, int) else value
