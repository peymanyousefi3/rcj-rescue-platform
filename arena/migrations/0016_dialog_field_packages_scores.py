from django.db import migrations, models


def preserve_saved_scores(apps,schema_editor):
    apps.get_model('arena','Score').objects.filter(normalized__isnull=False).update(normalized_override=True)


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0015_runrecording'),
    ]

    operations = [
        migrations.AddField(
            model_name='asset',
            name='field_info',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='asset',
            name='map_role',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='round',
            name='map_general',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='round',
            name='map_public',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='round',
            name='map_targets',
            field=models.ManyToManyField(blank=True, related_name='round_maps', to='arena.team'),
        ),
        migrations.AddField(
            model_name='score',
            name='normalized_override',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(preserve_saved_scores,migrations.RunPython.noop),
    ]
