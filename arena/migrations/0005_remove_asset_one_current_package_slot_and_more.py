import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0004_round_playback_released_round_playback_url'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='asset',
            name='one_current_package_slot',
        ),
        migrations.AddField(
            model_name='asset',
            name='public_copy',
            field=models.BooleanField(default=False, help_text='Separate organizer upload intended for public release. Team submissions always remain private.'),
        ),
        migrations.AlterField(
            model_name='emaildelivery',
            name='team',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='arena.team'),
        ),
        migrations.AddConstraint(
            model_name='asset',
            constraint=models.UniqueConstraint(condition=models.Q(('current', True), ('deleted_at__isnull', True), ('kind__in', ['tdp', 'video', 'code', 'bom', 'poster'])), fields=('team', 'kind', 'public_copy'), name='one_current_package_slot'),
        ),
    ]
