import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0014_preserve_main_challenge'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='RunRecording',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('current', models.BooleanField(default=True)),
                ('published', models.BooleanField(default=False)),
                ('entry_path', models.CharField(max_length=1000)),
                ('preview_path', models.CharField(max_length=1000)),
                ('scene_path', models.CharField(max_length=1000)),
                ('animation_path', models.CharField(max_length=1000)),
                ('player_version', models.CharField(default='R2023b', max_length=30)),
                ('frame_count', models.PositiveIntegerField()),
                ('duration_ms', models.PositiveBigIntegerField()),
                ('manifest', models.JSONField(default=dict)),
                ('round', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='arena.round')),
                ('team', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='arena.team')),
                ('uploaded_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
                'constraints': [models.UniqueConstraint(condition=models.Q(('current', True)), fields=('round', 'team'), name='one_current_run_recording')],
            },
        ),
    ]
