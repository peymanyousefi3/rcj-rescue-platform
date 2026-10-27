import json
from datetime import timedelta
import pytest
from django.utils import timezone
from arena.models import Announcement,Programme,Quarantine,Round
from arena.control_forms import RoundForm
from arena.scheduling import lineup_data,revision

pytestmark=pytest.mark.django_db

def stamp(value):return timezone.localtime(value).strftime('%Y-%m-%dT%H:%M')


def test_new_round_arranges_teams_in_same_save_and_computes_its_finish(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    rows=[{'team':str(teams[1].pk),'duration':12,'gap':3},{'team':str(teams[0].pk),'duration':17,'gap':5}]
    response=client.post('/control/',{'form':'round','number':2,'starts_at':stamp(r.starts_at),'lineup-lineup':json.dumps(rows)})
    assert response.status_code==302
    created=Round.objects.get(number=2);assert created.duration_minutes==37 and not created.submissions_enabled
    runs=list(Programme.objects.filter(round=created));assert [run.team_id for run in runs]==[teams[1].pk,teams[0].pk]
    assert runs[1].ends_at==created.ends_at
    assert response.url=='/control/#rounds'
    html=client.get(f'/control/?editor=round&round={created.pk}').content.decode();assert 'data-lineup-editor' in html and '<html' not in html
    fields=RoundForm(competition=c).fields
    assert not {'ends_at','duration_minutes','end_mode','playback_url','playback_released'}&set(fields)


def test_calendar_modal_and_competition_range(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    page=client.get('/control/');assert page.context['calendar_first_day']==timezone.localtime(c.starts_at).date().isoformat()
    response=client.get('/control/?editor=event&starts_at=2026-10-23T09:00:00&ends_at=2026-10-23T09:45:00')
    assert b'<html' not in response.content and b'editor-type-switch' in response.content
    assert response.context['form']['duration_minutes'].value()==45
    bad=client.post('/control/?editor=event',{'form':'event','_return':'programme','title':'Test'})
    assert bad.status_code==200 and b'errorlist' in bad.content and b'<html' not in bad.content
    good=client.post('/control/?editor=event',{'form':'event','_return':'programme','title':'Test','starts_at':'2026-10-23T09:00','end_mode':'duration','duration_minutes':25})
    assert good.status_code==302 and good.url=='/control/#programme'
    json_save=client.post('/control/?editor=event',{'form':'event','_return':'programme','title':'Accessible create','starts_at':'2026-10-23T10:00','end_mode':'duration','duration_minutes':20},HTTP_X_ASR_EDITOR='1')
    assert json_save.json()['redirect']=='/control/#programme'
    old_start,old_end=c.starts_at,c.ends_at
    data={'form':'competition','name':c.name,'location':c.location,'phase':c.phase,
        'first_day':timezone.localtime(c.starts_at).date().isoformat(),'last_day':timezone.localtime(c.ends_at).date().isoformat()}
    assert client.post('/control/',data).status_code==302
    c.refresh_from_db();assert c.starts_at==old_start and c.ends_at==old_end
    data.update(first_day='2026-10-22',last_day='2026-10-25')
    assert client.post('/control/',data).status_code==302
    page=client.get('/control/');assert page.context['calendar_first_day']=='2026-10-22' and page.context['calendar_end_day']=='2026-10-26'


def test_shared_recipient_module_supports_none_selected_all_and_public(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    base={'form':'notice','title':'Selected teams','body':'Private notice','recipient_module':'1','targets':[str(teams[0].pk)]}
    assert client.post('/control/',base).status_code==302
    notice=Announcement.objects.get();assert not notice.public and not notice.general and list(notice.targets.all())==[teams[0]]
    base.update(title='Public only',targets=[],public_visibility='on')
    assert client.post('/control/',base).status_code==302
    assert Announcement.objects.get(title='Public only').public and not Announcement.objects.get(title='Public only').targets.exists()
    base.update(title='All teams',targets=[str(t.pk) for t in teams],public_visibility='')
    assert client.post('/control/',base).status_code==302
    assert Announcement.objects.get(title='All teams').general
    data={'form':'quarantine','name':'Private request','deadline':stamp(timezone.now()+timedelta(days=1)),'recipient_module':'1','targets':[],'public_visibility':'on'}
    assert client.post('/control/',data).status_code==200 and not Quarantine.objects.exists()
    data['targets']=[str(t.pk) for t in teams]
    assert client.post('/control/',data).status_code==302 and Quarantine.objects.get().all_teams
    html=client.get('/control/').content.decode();assert '<select name="audience"' not in html and '<select name="all_teams"' not in html
