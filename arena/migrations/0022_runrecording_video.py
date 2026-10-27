from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0021_score_elapsed_seconds'),
    ]

    operations = [
        migrations.AddField(
            model_name='runrecording',
            name='video_key',
            field=models.CharField(blank=True, max_length=240),
        ),
        migrations.AddField(
            model_name='runrecording',
            name='video_name',
            field=models.CharField(blank=True, max_length=180),
        ),
        migrations.AddField(
            model_name='runrecording',
            name='video_type',
            field=models.CharField(blank=True, max_length=30),
        ),
    ]
