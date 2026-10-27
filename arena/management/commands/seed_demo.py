"""Populate fictional demonstration scores and workflows; never seed credentials or email."""
from datetime import timedelta
from django.core.management.base import BaseCommand,CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from arena.models import Competition,Challenge,Round,Team,Score,Programme,Quarantine,Announcement
from arena.scoring import normalize_round

class Command(BaseCommand):
    help='Populate the fictional bootstrap competition for a local walkthrough. Creates no accounts and sends no email.'
    @transaction.atomic
    def handle(self,*args,**options):
        c=Competition.objects.get(slug='asr26')
        if c.name!='Demonstration Rescue Competition':raise CommandError('Only the fictional demonstration competition can be populated.')
        if Score.objects.filter(round__competition=c).exists():raise CommandError('Demo scores already exist; no records were changed.')
        author=get_user_model().objects.filter(is_staff=True,is_active=True).first()
        if author is None:raise CommandError('Create your own administrator first with createsuperuser.')
        now=timezone.now();offset=timedelta(days=(timezone.localdate()-timezone.localtime(c.starts_at).date()).days)
        for r in Round.objects.filter(competition=c):
            for field in ['opens_at','quarantine_at','starts_at','ends_at']:setattr(r,field,getattr(r,field)+offset)
            r.save()
        for event in Programme.objects.filter(competition=c):
            event.starts_at+=offset;event.ends_at+=offset;event.save()
        c.starts_at+=offset;c.ends_at+=offset;c.phase='running';c.save()
        teams=list(Team.objects.regular().filter(competition=c).order_by('code'))
        main=c.challenge_set.get(primary=True)
        for r in main.round_set.all():
            for i,t in enumerate(teams):Score.objects.create(round=r,team=t,raw=1000-i*95+r.number*23)
            normalize_round(r)
        relay=Challenge.objects.create(competition=c,name='SuperTeam Rescue Relay',category='superteam',expected_rounds=2,calculation='sum',score_source='raw')
        groups=[]
        for i in range(2):
            pair=Team.objects.create(competition=c,code=f'PAIR{i+1:02}',name=['Aurora + Atlas','Cedar + Orbit'][i],country='Demo',superteam_challenge=relay)
            pair.members.set(teams[i*2:i*2+2]);groups.append(pair)
        for n in range(1,3):
            start=c.starts_at+timedelta(days=1,hours=n)
            r=Round.objects.create(competition=c,challenge=relay,number=n,name=f'Relay mission {n}',opens_at=start-timedelta(hours=2),quarantine_at=start-timedelta(hours=1),starts_at=start,ends_at=start+timedelta(minutes=30))
            for i,t in enumerate(groups):
                Score.objects.create(round=r,team=t,raw=650+n*30-i*80)
                Programme.objects.create(competition=c,source_key=f'demo-relay-{n}-{i}',title=r.name,round=r,team=t,starts_at=start+timedelta(minutes=15*i),ends_at=start+timedelta(minutes=15*(i+1)))
            normalize_round(r)
        Quarantine.objects.create(competition=c,name='Round 2 controller submission',instructions='Demonstration request. Submit the complete controller package before the deadline.',opens_at=now-timedelta(hours=1),deadline=now+timedelta(hours=2))
        Announcement.objects.create(competition=c,title='Competition briefing',body='**Welcome to the demonstration.** Check the programme, review your run times and prepare your submissions.',general=True,public=True,author=author)
        self.stdout.write('Fictional scores, SuperTeams, schedule, upload request and announcement created. No accounts or emails were created.')
