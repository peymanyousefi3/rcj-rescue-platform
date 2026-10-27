import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0018_announcement_email_recipients'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='quarantine',
            name='challenge',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='arena.challenge'),
        ),
        migrations.AddField(
            model_name='team',
            name='members',
            field=models.ManyToManyField(blank=True, related_name='superteam_groups', to='arena.team'),
        ),
        migrations.AddField(
            model_name='team',
            name='superteam_challenge',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='superteams', to='arena.challenge'),
        ),
        migrations.AlterField(
            model_name='asset',
            name='kind',
            field=models.CharField(choices=[('round_file', 'Submission file'), ('round_code', 'Submission file'), ('round_json', 'Submission file'), ('tdp', 'TDP'), ('video', 'Video'), ('code', 'Code'), ('bom', 'BOM'), ('poster', 'Poster'), ('resource', 'Resource'), ('map', 'Map'), ('quarantine_file', 'Quarantine File'), ('complaint_file', 'Complaint File')], max_length=20),
        ),
        migrations.CreateModel(
            name='Complaint',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('subject', models.CharField(max_length=180)),
                ('message', models.TextField(max_length=12000)),
                ('status', models.CharField(choices=[('submitted', 'Submitted'), ('reviewing', 'Under review'), ('resolved', 'Resolved')], default='submitted', max_length=12)),
                ('response', models.TextField(blank=True, max_length=12000)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ('competition', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='arena.competition')),
                ('team', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='arena.team')),
            ],
            options={
                'ordering': ['-created_at', '-pk'],
            },
        ),
        migrations.AddField(
            model_name='asset',
            name='complaint',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='attachments', to='arena.complaint'),
        ),
    ]
