from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0006_alter_asset_kind_quarantine_asset_quarantine_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='asset',
            name='one_current_package_slot',
        ),
        migrations.AlterField(
            model_name='asset',
            name='kind',
            field=models.CharField(choices=[('round_file', 'Submission file'), ('round_code', 'Submission file'), ('round_json', 'Submission file'), ('tdp', 'TDP'), ('video', 'Video'), ('code', 'Code'), ('bom', 'BOM'), ('poster', 'Poster'), ('resource', 'Resource'), ('map', 'Map'), ('quarantine_file', 'Quarantine File')], max_length=20),
        ),
        migrations.AddConstraint(
            model_name='asset',
            constraint=models.UniqueConstraint(condition=models.Q(('current', True), ('deleted_at__isnull', True), ('kind__in', ['tdp', 'video', 'code', 'bom', 'poster']), ('public_copy', True)), fields=('team', 'kind', 'public_copy'), name='one_current_package_slot'),
        ),
    ]
