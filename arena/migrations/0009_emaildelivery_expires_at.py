from datetime import timedelta
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


def expire_existing_links(apps, schema_editor):
    Delivery = apps.get_model('arena', 'EmailDelivery')
    for item in Delivery.objects.using(schema_editor.connection.alias).filter(
            Q(dedupe_key__startswith='password-reset:') | Q(dedupe_key__startswith='invite:') |
            Q(dedupe_key__startswith='reinvite:'), expires_at=None).iterator():
        item.expires_at = item.created_at + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT)
        item.save(update_fields=['expires_at'])


class Migration(migrations.Migration):
    dependencies = [('arena', '0008_emailconfiguration_emaildelivery_html_body')]
    operations = [
        migrations.AddField(model_name='emaildelivery', name='expires_at',
            field=models.DateTimeField(blank=True, null=True)),
        migrations.RunPython(expire_existing_links, migrations.RunPython.noop),
    ]
