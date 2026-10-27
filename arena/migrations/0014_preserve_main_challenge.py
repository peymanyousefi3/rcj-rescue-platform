from django.db import migrations


def preserve_main(apps,schema_editor):
    Competition=apps.get_model('arena','Competition')
    Challenge=apps.get_model('arena','Challenge')
    Round=apps.get_model('arena','Round')
    for competition in Competition.objects.all():
        rounds=Round.objects.filter(competition=competition)
        count=rounds.count()
        challenge=Challenge.objects.create(competition=competition,name='Main competition',category='main',
            expected_rounds=max(count,1),calculation='best',top_count=min(competition.counted_rounds,max(count,1)),primary=True)
        rounds.update(challenge=challenge)


class Migration(migrations.Migration):
    dependencies=[('arena','0013_challenge_alter_round_options_and_more')]
    operations=[migrations.RunPython(preserve_main,migrations.RunPython.noop)]
