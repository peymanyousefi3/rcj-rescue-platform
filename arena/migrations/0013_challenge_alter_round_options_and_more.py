import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0012_emailconfiguration_announcement_bcc_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Challenge',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('category', models.CharField(choices=[('main', 'Main challenge'), ('side', 'Side challenge'), ('superteam', 'SuperTeam challenge')], default='side', max_length=12)),
                ('expected_rounds', models.PositiveSmallIntegerField(default=1)),
                ('calculation', models.CharField(choices=[('sum', 'Sum'), ('average', 'Average'), ('best', 'Best scores')], default='sum', max_length=12)),
                ('top_count', models.PositiveSmallIntegerField(default=1)),
                ('score_source', models.CharField(choices=[('normalized', 'Normalized score'), ('raw', 'Raw score')], default='normalized', max_length=12)),
                ('primary', models.BooleanField(default=False, editable=False)),
                ('archived_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'ordering': ['-primary', 'name', 'pk'],
            },
        ),
        migrations.AlterModelOptions(
            name='round',
            options={'ordering': ['challenge_id', 'number']},
        ),
        migrations.RemoveConstraint(
            model_name='round',
            name='unique_competition_round',
        ),
        migrations.RemoveConstraint(
            model_name='round',
            name='round_valid_times',
        ),
        migrations.AddField(
            model_name='quarantine',
            name='opens_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='round',
            name='submissions_enabled',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='challenge',
            name='competition',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='arena.competition'),
        ),
        migrations.AddField(
            model_name='round',
            name='challenge',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='arena.challenge'),
        ),
        migrations.AddConstraint(
            model_name='round',
            constraint=models.UniqueConstraint(fields=('competition', 'challenge', 'number'), name='unique_challenge_round'),
        ),
        migrations.AddConstraint(
            model_name='round',
            constraint=models.UniqueConstraint(condition=models.Q(('challenge__isnull', True)), fields=('competition', 'number'), name='unique_uncategorized_round'),
        ),
        migrations.AddConstraint(
            model_name='round',
            constraint=models.CheckConstraint(condition=models.Q(('opens_at__lt', models.F('quarantine_at')), ('starts_at__lt', models.F('ends_at'))), name='round_valid_times'),
        ),
        migrations.AddConstraint(
            model_name='challenge',
            constraint=models.UniqueConstraint(fields=('competition', 'name'), name='unique_challenge_name'),
        ),
        migrations.AddConstraint(
            model_name='challenge',
            constraint=models.UniqueConstraint(condition=models.Q(('primary', True)), fields=('competition',), name='one_primary_challenge'),
        ),
    ]
