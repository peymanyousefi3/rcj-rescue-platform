import datetime as dt
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from arena.models import Competition, Membership, Round, Team

@pytest.fixture
def event(db,settings,tmp_path):
    settings.STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage','OPTIONS':{'location':str(tmp_path)}},
        'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}}
    now=timezone.now()
    c=Competition.objects.create(workbook_enabled=True,starts_at=now-dt.timedelta(days=1),ends_at=now+dt.timedelta(days=2))
    r=Round.objects.create(competition=c,number=1,opens_at=now-dt.timedelta(hours=1),
        quarantine_at=now+dt.timedelta(hours=1),starts_at=now+dt.timedelta(hours=2),ends_at=now+dt.timedelta(hours=3))
    teams=[Team.objects.create(competition=c,code=f'{n}CA',name=f'Team {n}',country='Canada',leader_email=f'leader{n}@example.test') for n in [101,102]]
    users=[]
    for i,t in enumerate(teams):
        u=get_user_model().objects.create_user(username=f'team{i}',password='A-secure-test-password-2026')
        Membership.objects.create(user=u,team=t);users.append(u)
    staff=get_user_model().objects.create_user(username='organizer',password='Admin-test-password-2026',is_staff=True)
    return c,r,teams,users,staff
