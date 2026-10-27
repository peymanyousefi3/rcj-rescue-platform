from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0003_request_quota'),
    ]

    operations = [
        migrations.AddField(
            model_name='round',
            name='playback_released',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='round',
            name='playback_url',
            field=models.URLField(blank=True, max_length=1000),
        ),
    ]
