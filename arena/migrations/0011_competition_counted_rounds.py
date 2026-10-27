from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('arena', '0010_remove_asset_one_current_package_slot_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='competition',
            name='counted_rounds',
            field=models.PositiveSmallIntegerField(default=6),
        ),
    ]
