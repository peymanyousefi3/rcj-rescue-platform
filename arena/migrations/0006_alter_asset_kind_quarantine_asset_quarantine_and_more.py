import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0005_remove_asset_one_current_package_slot_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='asset',
            name='kind',
            field=models.CharField(choices=[('round_code', 'Round Code'), ('round_json', 'Round Json'), ('tdp', 'TDP'), ('video', 'Video'), ('code', 'Code'), ('bom', 'BOM'), ('poster', 'Poster'), ('resource', 'Resource'), ('map', 'Map'), ('quarantine_file', 'Quarantine File')], max_length=20),
        ),
        migrations.CreateModel(
            name='Quarantine',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=180)),
                ('instructions', models.TextField(blank=True, max_length=4000)),
                ('deadline', models.DateTimeField()),
                ('all_teams', models.BooleanField(default=True)),
                ('competition', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='arena.competition')),
                ('round', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='arena.round')),
            ],
            options={
                'ordering': ['deadline', 'name', 'pk'],
            },
        ),
        migrations.AddField(
            model_name='asset',
            name='quarantine',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='arena.quarantine'),
        ),
        migrations.CreateModel(
            name='QuarantineTeam',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('deadline', models.DateTimeField(blank=True, null=True)),
                ('quarantine', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='team_deadlines', to='arena.quarantine')),
                ('team', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='arena.team')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('quarantine', 'team'), name='one_quarantine_team')],
            },
        ),
    ]
