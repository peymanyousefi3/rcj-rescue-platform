import re
from django import template
from django.utils.html import format_html, format_html_join

register = template.Library()


@register.filter
def announcement_bold(value):
    """Support paired **bold** markers while escaping all announcement text."""
    parts = re.split(r'\*\*(.+?)\*\*', str(value), flags=re.S)
    return format_html_join('', '{}', ((format_html('<strong>{}</strong>', part) if i % 2 else format_html('{}', part),)
                                      for i, part in enumerate(parts)))


@register.filter
def announcement_plain(value):
    return re.sub(r'\*\*(.+?)\*\*', r'\1', str(value), flags=re.S)
