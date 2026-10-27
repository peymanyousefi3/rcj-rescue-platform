from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0011_competition_counted_rounds'),
    ]

    operations = [
        migrations.AddField(
            model_name='emailconfiguration',
            name='announcement_bcc',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='emailconfiguration',
            name='announcement_cc',
            field=models.TextField(blank=True, default=''),
        ),
    ]
