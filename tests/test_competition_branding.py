import io
from datetime import timedelta
from unittest.mock import patch
import pytest
from PIL import Image
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from arena.control_forms import CompetitionForm
from arena.models import Competition,Score,Team

pytestmark=pytest.mark.django_db

def picture(name='logo.png',color='#2047a5'):
    out=io.BytesIO();Image.new('RGB',(80,40),color).save(out,'PNG')
    return SimpleUploadedFile(name,out.getvalue(),content_type='image/png')

def values(c,**changes):
    return {'form':'competition','name':c.name,'short_name':'RCJ Review','header_title':'RoboCupJunior',
        'league_name':'Junior Rescue Simulation','location':'Test venue','banner_title':'Simulation Finals',
        'banner_subtitle':'Hosted by Example Federation','first_day':timezone.localtime(c.starts_at).date().isoformat(),
        'last_day':c.display_end_date.isoformat(),'phase':c.phase,**changes}

def test_branding_editor_saves_images_and_text_without_touching_scores(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    oldteams=list(Team.objects.values());old_scores=list(Score.objects.values());dates=(c.starts_at,c.ends_at)
    response=client.post('/control/',{**values(c),'logo':picture(),'partner_logo':picture('partner.png'),'banner_image':picture('banner.jpg')})
    assert response.status_code==302
    c.refresh_from_db();assert c.header_title=='RoboCupJunior' and c.banner_title=='Simulation Finals'
    assert (c.starts_at,c.ends_at)==dates and list(Team.objects.values())==oldteams and list(Score.objects.values())==old_scores
    assert all(getattr(c,key).startswith(f'branding/{c.pk}/') for key in ['logo_key','partner_logo_key','banner_key'])
    client.logout();html=client.get('/').content
    assert b'Simulation Finals' in html and b'Hosted by Example Federation' in html
    assert f'/branding/{c.pk}/logo/'.encode() in html and b'RoboCupJunior' in html
    image=client.get(f'/branding/{c.pk}/logo/');assert image.status_code==200 and image['Content-Type']=='image/png'
    content=b''.join(image.streaming_content);assert content.startswith(b'\x89PNG')
    assert 'no-cache' in image['Cache-Control'] and 'sandbox' in image['Content-Security-Policy']

@pytest.mark.parametrize('content,name',[(b'<svg><script>alert(1)</script></svg>','logo.svg'),(b'<html>unsafe</html>','logo.png'),(b'not an image','bad.jpg')])
def test_invalid_branding_upload_cannot_change_event(client,event,content,name):
    c=event[0];client.force_login(event[-1]);old=c.name
    response=client.post('/control/',{**values(c,name='Should not save'),'logo':SimpleUploadedFile(name,content)})
    assert response.status_code==200;c.refresh_from_db();assert c.name==old and c.logo_key==''

def test_branding_is_staff_only_and_public_route_cannot_point_to_private_data(client,event):
    c=event[0];client.force_login(event[3][0]);assert client.post('/control/',values(c)).status_code in [302,403]
    c.refresh_from_db();assert c.short_name!='RCJ Review'
    c.logo_key='recordings/private/controller.json';c.save(update_fields=['logo_key'])
    assert client.get(f'/branding/{c.pk}/logo/').status_code==404
    assert client.get(f'/branding/{c.pk}/anything/').status_code==404
    assert client.post(f'/branding/{c.pk}/logo/').status_code==405

def test_replacement_and_removal_preserve_old_images(client,event):
    c=event[0];client.force_login(event[-1]);assert client.post('/control/',{**values(c),'logo':picture()}).status_code==302
    c.refresh_from_db();old=c.logo_key
    assert client.post('/control/',{**values(c),'logo':picture(color='#ffffff')}).status_code==302
    c.refresh_from_db();assert c.logo_key!=old and default_storage.exists(old)
    assert client.post('/control/',{**values(c),'remove_logo':'on'}).status_code==302
    c.refresh_from_db();assert not c.logo_key and default_storage.exists(old)
    assert client.get(f'/branding/{c.pk}/logo/').status_code==404

def test_exclusive_end_date_displays_the_last_competition_day(event):
    c=event[0];end=timezone.localtime(c.ends_at).replace(hour=0,minute=0,second=0,microsecond=0)
    c.ends_at=end;assert c.display_end_date==(end-timedelta(days=1)).date()

def test_branding_controls_are_grouped_and_keep_modal_ids_unique(client,event):
    client.force_login(event[-1]);response=client.get('/control/?editor=competition')
    assert response.status_code==200
    for text in [b'Event identity',b'Public logos',b'Homepage banner',b'Competition dates',b'dialog_competition_logo']:
        assert text in response.content


def test_branding_popup_shows_current_default_images(client,event):
    client.force_login(event[-1]);html=client.get('/control/?editor=competition').content
    for text in [b'Current competition logo',b'Current homepage banner image',b'brand/platform.svg',b'brand/platform-hero.svg',b'No image is currently displayed.',b'Leave this empty to keep the image shown above.']:
        assert text in html
    assert html.count(b'name="logo"')==1 and html.count(b'name="banner_image"')==1

def test_editing_text_keeps_uploaded_images_and_reloads_saved_previews(client,event):
    c=event[0];client.force_login(event[-1])
    assert client.post('/control/',{**values(c),'logo':picture(),'partner_logo':picture(),'banner_image':picture()}).status_code==302
    c.refresh_from_db();keys=(c.logo_key,c.partner_logo_key,c.banner_key)
    html=client.get('/control/?editor=competition').content
    for slot in ['logo','partner','banner']:assert f'/branding/{c.pk}/{slot}/'.encode() in html
    assert client.post('/control/',values(c,header_title='Updated title')).status_code==302
    c.refresh_from_db();assert keys==(c.logo_key,c.partner_logo_key,c.banner_key)


def test_branding_entry_precedes_scoring_and_all_fields_render_once(client,event):
    client.force_login(event[-1]);html=client.get('/control/').content
    assert html.index(b'Edit branding &amp; event details')<html.index(b'id="challenge-editor"')
    c=event[0];form=CompetitionForm(instance=c)
    html=client.get('/control/?editor=competition',HTTP_X_ASR_EDITOR='1').content
    for name in form.fields:assert html.count(f'name="{name}"'.encode())==1,name
