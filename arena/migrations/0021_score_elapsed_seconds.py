from django.core.validators import MaxValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('arena', '0020_shared_file_deliveries')]
    operations = [
        migrations.AddField(model_name='score', name='elapsed_seconds',
            field=models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(480)],
                help_text='Elapsed run time in seconds, converted from the time remaining out of 8 minutes.')),
        migrations.AddConstraint(model_name='score', constraint=models.CheckConstraint(
            condition=models.Q(elapsed_seconds__isnull=True) | models.Q(elapsed_seconds__lte=480),
            name='score_elapsed_within_allowance')),
    ]
