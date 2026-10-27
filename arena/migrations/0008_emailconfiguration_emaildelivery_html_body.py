from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0007_generic_multi_file_submissions'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailConfiguration',
            fields=[
                ('id', models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ('enabled', models.BooleanField(default=False)),
                ('sender_name', models.CharField(default='ASR 26 Rescue Simulation', max_length=120)),
                ('sender_email', models.EmailField(blank=True, max_length=254)),
                ('host', models.CharField(blank=True, max_length=253)),
                ('port', models.PositiveIntegerField(default=587)),
                ('security', models.CharField(choices=[('starttls', 'STARTTLS'), ('ssl', 'SSL/TLS')], default='starttls', max_length=8)),
                ('username', models.CharField(blank=True, max_length=254)),
                ('password_encrypted', models.TextField(blank=True, editable=False)),
            ],
        ),
        migrations.AddField(
            model_name='emaildelivery',
            name='html_body',
            field=models.TextField(blank=True),
        ),
    ]
