from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0017_field_average_after_discards'),
    ]

    operations = [
        migrations.AddField(
            model_name='announcement',
            name='email_recipients',
            field=models.TextField(blank=True, default=''),
        ),
    ]
