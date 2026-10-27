from django.db import migrations, models


def use_field_average(apps,schema_editor):
    Competition=apps.get_model('arena','Competition')
    Challenge=apps.get_model('arena','Challenge')
    for competition in Competition.objects.filter(slug='asr26'):
        competition.workbook_enabled=False
        competition.save(update_fields=['workbook_enabled'])
        for challenge in Challenge.objects.filter(competition=competition,primary=True):
            challenge.discard_count=max(0,challenge.expected_rounds-challenge.top_count) if challenge.calculation=='best' else 0
            challenge.discard_count=min(challenge.discard_count,max(0,challenge.expected_rounds-1))
            challenge.calculation='trimmed_mean';challenge.score_source='normalized';challenge.tie_break='none'
            challenge.save(update_fields=['calculation','score_source','discard_count','tie_break'])


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0016_dialog_field_packages_scores'),
    ]

    operations = [
        migrations.AddField(
            model_name='challenge',
            name='discard_count',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='challenge',
            name='tie_break',
            field=models.CharField(choices=[('none', 'Shared rank (tie)'), ('retained', 'Highest retained round scores')], default='none', max_length=12),
        ),
        migrations.AddField(
            model_name='round',
            name='zero_score_policy',
            field=models.CharField(choices=[('pending', 'Await organizer decision'), ('exclude', 'Exclude this round for every team'), ('zero', 'Assign zero to every team')], default='pending', max_length=12),
        ),
        migrations.AlterField(
            model_name='challenge',
            name='calculation',
            field=models.CharField(choices=[('trimmed_mean', 'Average after discards (%)'), ('sum', 'Sum'), ('average', 'Average'), ('best', 'Best scores')], default='trimmed_mean', max_length=12),
        ),
        migrations.AlterField(
            model_name='competition',
            name='workbook_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(use_field_average,migrations.RunPython.noop),
    ]
