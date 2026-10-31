from datetime import timedelta
import pytest
from django.utils import timezone
from arena.models import Announcement, Challenge, Programme, Score
from arena.control_forms import SlideshowForm

pytestmark=pytest.mark.django_db

def values(c,**changes):
    fields=SlideshowForm.Meta.fields
    from arena.slide_settings import TEXTS,COLORS
    return {'form':'slideshow',**{name:getattr(c,name) for name in fields},**{'text_'+k:v for k,(_,v) in TEXTS.items()},**{'color_'+k:v for k,(_,v) in COLORS.items()},**changes}


def test_slideshow_public_only_and_same_for_admin(client,event):
    c,r,teams,users,staff=event
    challenge=Challenge.objects.create(competition=c,name='Field',primary=True,expected_rounds=1)
    r.challenge=challenge;r.save()
    Score.objects.create(team=teams[0],round=r,raw=80)
    Score.objects.create(team=teams[1],round=r,raw=100)
    Announcement.objects.create(competition=c,title='Private notice',body='secret-body',public=False,author=staff)
    now=timezone.now()
    for title,confirmed,archived in [('Visible event',True,None),('Draft event',False,None),('Removed event',True,now)]:
        Programme.objects.create(competition=c,source_key=title,title=title,starts_at=now,ends_at=now+timedelta(minutes=10),confirmed=confirmed,archived_at=archived)
    page=client.get('/slide');assert page.status_code==200 and b'slideshow.js' in page.content
    data=client.get('/slide/data/');assert data.status_code==200 and 'no-store' in data['Cache-Control']
    public=data.json();assert [e['title'] for e in public['schedule']]==['Visible event']
    result=public['results'][0];assert not result['rankings_released']
    assert result['rows'][0]['rank'] is None and result['rows'][0]['scores'][0]['raw']=='80.00'
    for private in [b'leader101',b'Private notice',b'secret-body',b'Draft event',b'Removed event',b'blob_key',b'password',b'/files/']:
        assert private not in data.content
    client.force_login(staff);admin=client.get('/slide/data/').json()
    for key in ['competition','schedule','results','settings']:assert admin[key]==public[key]
    challenge.rankings_released=True;challenge.save()
    ranked=client.get('/slide/data/').json()['results'][0]
    assert ranked['rows'][0]['name']==teams[1].name and ranked['rows'][0]['rank']==1
    assert client.post('/slide/data/').status_code==405


def test_disable_removes_every_public_record_and_filters_archives(client,event):
    c,r,teams,users,staff=event
    challenge=Challenge.objects.create(competition=c,name='Removed challenge',archived_at=timezone.now())
    assert client.get('/slide/data/').json()['results']==[]
    c.slideshow_enabled=False;c.save()
    data=client.get('/slide/data/').json()
    assert data['enabled'] is False and 'competition' not in data and 'results' not in data and 'schedule' not in data


def test_slideshow_settings_staff_only_and_no_competition_side_effects(client,event):
    c,r,teams,users,staff=event
    old=(c.name,c.starts_at,c.ends_at,c.workbook_enabled)
    client.force_login(users[0]);assert client.post('/control/',values(c,slide_intro_seconds=10)).status_code in (302,403)
    c.refresh_from_db();assert c.slide_intro_seconds==12
    client.force_login(staff)
    response=client.get('/control/?editor=slideshow')
    assert response.status_code==200 and b'Results (seconds)' in response.content
    response=client.post('/control/',values(c,slide_intro_seconds=7))
    assert response.status_code==302 and response.url.endswith('#competition-settings')
    c.refresh_from_db();assert c.slide_intro_seconds==7
    assert (c.name,c.starts_at,c.ends_at,c.workbook_enabled)==old
    response=client.get('/control/');assert b'Slideshow settings' in response.content and b'/slide' in response.content


@pytest.mark.parametrize('changes',[{'slide_intro_seconds':2},{'slide_results_seconds':121},{'slide_refresh_seconds':1},{'slide_intro':False,'slide_schedule':False,'slide_results':False},{'color_ink':'url(https://evil.test)'},{'qr_destination':'http://example.com'}])
def test_settings_validation(event,changes):
    c=event[0];form=SlideshowForm(values(c,**changes),instance=c)
    assert not form.is_valid()


def test_schedule_date_boundaries_and_updates(client,event):
    from arena.slideshow import display_day
    from datetime import datetime,time
    c,r,teams,users,staff=event
    first=timezone.localtime(c.starts_at).date();last=c.display_end_date
    def at(day):return timezone.make_aware(datetime.combine(day,time(12)))
    for day,title in [(first,'First day'),(first+timedelta(days=1),'Middle day'),(last,'Last day')]:
        Programme.objects.create(competition=c,source_key=title,title=title,starts_at=at(day),ends_at=at(day)+timedelta(hours=1))
    assert display_day(c,at(first-timedelta(days=4)))==first
    assert display_day(c,at(first+timedelta(days=1)))==first+timedelta(days=1)
    assert display_day(c,at(last))==last
    assert display_day(c,at(last+timedelta(days=4)))==last
    from unittest.mock import patch
    with patch('arena.slideshow.timezone.now',return_value=at(last+timedelta(days=4))):
        data=client.get('/slide/data/').json()
    assert [e['title'] for e in data['schedule']]==['Last day']
    assert data['schedule_date']==last.isoformat()
    c.banner_title='Fresh title';c.save()
    assert client.get('/slide/data/').json()['competition']['banner_title']=='Fresh title'


def test_only_released_public_map_metadata_appears(client,event):
    from arena.models import Asset
    c,r,teams,users,staff=event
    r.challenge=Challenge.objects.create(competition=c,name='Field',primary=True);r.save()
    Asset.objects.create(competition=c,round=r,kind='map',map_role='info_json',field_info={'maximum_score':500},
        uploader=staff,original_name='info.json',blob_key='private/info.json',size=10,sha256='a'*64,scan_status='clean')
    def maximum():return client.get('/slide/data/').json()['results'][0]['rounds'][0]['maximum']
    assert maximum() is None
    r.completed=True;r.maps_released=True;r.map_public=False;r.save();assert maximum() is None
    r.map_public=True;r.save();assert maximum()=='500.00'
    assert b'private/info.json' not in client.get('/slide/data/').content
    r.archived_at=timezone.now();r.save()
    assert client.get('/slide/data/').json()['results'][0]['rounds']==[]


def test_design_content_images_and_access(client,event):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from tests.test_competition_branding import picture
    c,r,teams,users,staff=event;client.force_login(staff)
    response=client.post('/control/?editor=slideshow',values(c,text_welcome='Hello teams',color_accent='#123456',image_cover=picture()))
    assert response.status_code==302
    c.refresh_from_db();assert c.slide_design['texts']['welcome']=='Hello teams'
    client.logout();data=client.get('/slide/data/').json()
    assert data['design']['texts']['welcome']=='Hello teams' and data['design']['colors']['accent']=='#123456'
    url=data['design']['images']['cover'];image=client.get(url)
    assert image.status_code==200 and image['Content-Type']=='image/png'
    assert client.get(f'/slide/qr/{c.pk}/')['Content-Type']=='image/png'
    c.slide_design['images']['cover']='private/controller.json';c.save()
    assert client.get(url).status_code==404
    client.force_login(staff)
    before=c.slide_design.copy()
    response=client.post('/control/?editor=slideshow',values(c,image_cover=SimpleUploadedFile('unsafe.svg',b'<svg/>')))
    assert response.status_code==200;c.refresh_from_db();assert c.slide_design==before


def test_round_runs_are_one_schedule_block_and_empty_days_stay_empty(client,event):
    from arena.slideshow import display_day
    from datetime import datetime,time
    from unittest.mock import patch
    c,r,teams,users,staff=event
    today=timezone.localdate();start=timezone.make_aware(datetime.combine(today,time(10)))
    for i,team in enumerate(teams):Programme.objects.create(competition=c,source_key=str(i),title='Run',round=r,team=team,starts_at=start+timedelta(minutes=10*i),ends_at=start+timedelta(minutes=10*(i+1)))
    data=client.get('/slide/data/').json();assert len(data['schedule'])==1
    assert data['schedule'][0]['start']=='10:00' and data['schedule'][0]['end']=='10:20'
    tomorrow=today+timedelta(days=1)
    with patch('arena.slideshow.timezone.now',return_value=timezone.make_aware(datetime.combine(tomorrow,time(12)))):
        data=client.get('/slide/data/').json()
    assert data['schedule_date']==tomorrow.isoformat() and data['schedule']==[]


def test_last_competition_day_does_not_fall_back_to_an_earlier_day(event):
    from arena.slideshow import display_day
    from datetime import datetime,time
    c=event[0];first=timezone.localtime(c.starts_at).date();last=c.display_end_date
    start=timezone.make_aware(datetime.combine(first,time(10)))
    Programme.objects.create(competition=c,source_key='only-first',title='Opening',starts_at=start,ends_at=start+timedelta(hours=1))
    assert display_day(c,timezone.make_aware(datetime.combine(last+timedelta(days=1),time(12))))==last


def test_shared_values_are_prefilled_and_stay_linked_after_saving(client,event):
    from arena.branding import branding_urls
    from arena.slide_settings import TEXTS
    c,r,teams,users,staff=event
    c.header_title='Example Junior';c.name='Example Cup';c.short_name='EC 2028';c.league_name='Rescue Simulation';c.save()
    challenge=Challenge.objects.create(competition=c,name='Field challenge',primary=True)
    r.challenge=challenge;r.save()
    form=SlideshowForm(instance=c)
    assert form['text_event_name'].value()=='Example Cup'
    assert form['text_event_short'].value()=='EC 2028'
    assert form['text_brand_word'].value()=='Example'
    assert form['text_results_title'].value()=='Field challenge'
    assert form['auto_event_name'].value() is True
    body=values(c)
    from django.conf import settings
    body['qr_destination']=settings.PUBLIC_ORIGIN
    for key,(_,default) in TEXTS.items():
        body['text_'+key]=form['text_'+key].value()
        if '{' in default:body['auto_'+key]='on'
    client.force_login(staff);assert client.post('/control/?editor=slideshow',body).status_code==302
    c.refresh_from_db();assert c.slide_design['texts']['event_name']=='{competition_name}'
    c.name='Updated Cup';c.short_name='Updated short';c.header_title='Changed Junior';c.save()
    data=client.get('/slide/data/').json()
    assert data['design']['texts']['event_name']=='Updated Cup'
    assert data['design']['texts']['brand_word']=='Changed'
    assert data['design']['images']['cover']==branding_urls(c)['banner']
    assert SlideshowForm(instance=c)['text_event_name'].value()=='Updated Cup'


def test_manual_override_and_return_to_automatic(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    assert client.post('/control/?editor=slideshow',values(c,text_event_name='Display title')).status_code==302
    c.refresh_from_db();c.name='Different competition';c.save()
    assert client.get('/slide/data/').json()['design']['texts']['event_name']=='Display title'
    form=SlideshowForm(instance=c);assert form['auto_event_name'].value() is False
    assert client.post('/control/?editor=slideshow',values(c,text_event_name='Display title',auto_event_name='on')).status_code==302
    assert client.get('/slide/data/').json()['design']['texts']['event_name']=='Different competition'


def test_slideshow_prefill_does_not_render_competition_names_as_html(client,event):
    c=event[0];c.name='<img src=x onerror=alert(1)>';c.save()
    client.force_login(event[-1]);html=client.get('/control/?editor=slideshow').content
    assert b'Current display: &lt;img' in html and b'Current display: <img' not in html
