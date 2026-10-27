from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0022_runrecording_video'),
    ]

    operations = [
        migrations.AddField(
            model_name='challenge',
            name='rankings_released',
            field=models.BooleanField(default=False),
        ),
    ]
