from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0009_emaildelivery_expires_at'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='asset',
            name='one_current_package_slot',
        ),
        migrations.AddField(
            model_name='announcement',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='competition',
            name='workbook_enabled',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='programme',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='quarantine',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='round',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
