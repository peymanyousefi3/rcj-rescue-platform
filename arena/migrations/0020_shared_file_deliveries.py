import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0019_superteam_profiles_complaints'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='FileShare',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(max_length=180)),
                ('general', models.BooleanField(default=False)),
                ('public', models.BooleanField(default=False)),
                ('public_approved', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('archived_at', models.DateTimeField(blank=True, null=True)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ('competition', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='arena.competition')),
                ('targets', models.ManyToManyField(blank=True, to='arena.team')),
            ],
            options={
                'ordering': ['-created_at', '-pk'],
            },
        ),
        migrations.AddField(
            model_name='asset',
            name='share',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='files', to='arena.fileshare'),
        ),
    ]
