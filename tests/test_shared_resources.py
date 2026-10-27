from html import escape
import re

import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from arena.models import Asset, Competition, Membership, Team
from arena.access import can_download

pytestmark=pytest.mark.django_db


def upload(client,event,audience,targets):
    client.force_login(event[4])
    response=client.post('/control/',{'form':'managed-upload','destination':'organizer',
        'audience':audience,'targets':[team.pk for team in targets],
        'files':[SimpleUploadedFile('briefing.txt',b'One shared document')]})
    assert response.status_code==302
    return Asset.objects.get()


@pytest.mark.parametrize('audience,selected,public,general',[
    ('selected',1,False,False),('all',2,False,True),
    ('public',0,True,False),('public_selected',1,True,False),('public_all',2,True,True)])
def test_one_blob_one_admin_row_for_every_resource_audience(client,event,audience,selected,public,general):
    c,r,teams,users,staff=event
    asset=upload(client,event,audience,teams[:selected])
    assert asset.public_copy==public and asset.general==general and asset.team_id is None
    assert asset.targets.count()==selected and not asset.public_approved
    assert default_storage.exists(asset.blob_key)
    asset.scan_status='clean';asset.save()
    page=client.get('/control/').content.decode()
    assert page.count(f'class="file-title" href="/files/{asset.pk}/"')==1
    if selected:
        assert 'recipient-name-list' in page
        assert teams[0].name in page
    for i,user in enumerate(users):
        client.force_login(user)
        assert client.get(f'/files/{asset.pk}/').status_code==(200 if i<selected else 404)
        assert (b'briefing.txt' in client.get('/portal/resources/').content)==(i<selected)
    client.logout();assert client.get(f'/files/{asset.pk}/').status_code==404
    client.force_login(staff)
    client.post('/control/action/',{'action':'approve-file','id':asset.pk})
    asset.refresh_from_db();assert asset.public_approved==public
    client.logout();assert client.get(f'/files/{asset.pk}/').status_code==(200 if public else 404)
    assert (b'briefing.txt' in client.get('/resources/').content)==public
    assert Asset.objects.count()==1


def test_edit_shared_recipients_publication_and_replacement_keep_one_current_record(client,event):
    c,r,teams,users,staff=event
    asset=upload(client,event,'public_selected',teams[:1]);asset.scan_status='clean';asset.save()
    editor=client.get(f'/control/?editor=file&file={asset.pk}').content.decode()
    assert 'name="public_visibility"' in editor and 'checked' in editor
    # One edit changes the audience on the same file; public exposure still needs approval.
    result=client.post('/control/',{'form':'file','record_id':asset.pk,'recipient_module':'1',
        'title':'Shared briefing','original_name':asset.original_name,'targets':[team.pk for team in teams],
        'public_visibility':'on'})
    assert result.status_code==302
    asset.refresh_from_db();assert asset.general and asset.public_copy and asset.targets.count()==2
    client.post('/control/action/',{'action':'approve-file','id':asset.pk})
    result=client.post('/control/',{'form':'managed-upload','replacement':asset.pk,'destination':'organizer',
        'audience':'public_all','targets':[team.pk for team in teams],
        'files':SimpleUploadedFile('briefing-v2.txt',b'Revised shared document')})
    assert result.status_code==302
    current=Asset.objects.get(current=True)
    asset.refresh_from_db();assert not asset.current and not asset.public_approved
    assert current.public_copy and current.general and current.targets.count()==2 and not current.public_approved
    # Previous versions stay in history; a replacement is never published without its own approval.
    current.scan_status='clean';current.save()
    client.logout();assert client.get(f'/files/{current.pk}/').status_code==404
    client.force_login(users[1]);assert client.get(f'/files/{current.pk}/').status_code==200
    client.force_login(staff)
    result=client.post('/control/',{'form':'file','record_id':current.pk,'recipient_module':'1',
        'title':'Private briefing','original_name':current.original_name,'targets':[teams[0].pk]})
    assert result.status_code==302
    current.refresh_from_db();assert not current.public_copy and not current.general and not current.public_approved
    client.force_login(users[1]);assert client.get(f'/files/{current.pk}/').status_code==404
    client.force_login(users[0]);assert client.get(f'/files/{current.pk}/').status_code==200


def test_shared_files_never_skip_scanning_or_cross_competition_privacy(client,event):
    c,r,teams,users,staff=event
    asset=upload(client,event,'public_all',teams)
    assert not can_download(users[0],asset)
    asset.scan_status='rejected';asset.public_approved=True;asset.save()
    assert not can_download(users[0],asset)
    asset.scan_status='clean';asset.public_approved=False;asset.save()
    other=Competition.objects.create(slug='other',starts_at=c.starts_at,ends_at=c.ends_at)
    team=Team.objects.create(competition=other,code='OTHER',name='Other competition')
    Membership.objects.filter(user=users[0]).update(team=team)
    assert not can_download(users[0],asset)
    client.force_login(users[0]);assert client.get(f'/files/{asset.pk}/').status_code==404


def test_shared_upload_and_announcement_list_recipient_names_once(client,event):
    from arena.services import announce
    from arena.models import Announcement, EmailDelivery
    c,r,teams,users,staff=event
    asset=upload(client,event,'selected',teams)
    notice=announce(user=staff,competition=c,title='Shared update',body='One announcement',
        general=True,public=True,target_ids=[],queue_email=False)
    page=client.get('/control/').content.decode()
    assert Announcement.objects.count()==1 and notice.targets.count()==len(teams)
    assert not EmailDelivery.objects.exists()
    file_section=page.split('id="files"',1)[1].split('id="announce"',1)[0]
    assert file_section.count('<tr data-search-row')==1
    file_row=re.search(r'<tr data-search-row.*?</tr>',file_section,re.S).group()
    notice_section=page.split('id="announce"',1)[1]
    for team in teams:
        assert str(team.pk) in file_row
        assert f'<li>{escape(team.name)}</li>' in file_row
        assert f'<li>{escape(team.name)}</li>' in notice_section


# Closing a streamed response finishes its request; use committed transactions so
# Django may close/reopen the PostgreSQL connection between requests.
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('initial_audience',['all','selected'])
def test_recipient_edits_revoke_existing_sessions_and_saved_download_links_immediately(client,event,initial_audience):
    c,r,teams,users,staff=event
    asset=upload(client,event,initial_audience,teams)
    asset.scan_status='clean';asset.save()
    original_key=asset.blob_key
    url=f'/files/{asset.pk}/'
    sessions=[Client(),Client()]
    for session,user in zip(sessions,users): session.force_login(user)
    for session in sessions:
        response=session.get(url)
        assert response.status_code==200 and 'no-store' in response['Cache-Control']
        assert b''.join(response.streaming_content)==b'One shared document'
        response.close()
        assert url.encode() in session.get('/portal/resources/').content

    def recipients(selected):
        response=client.post('/control/',{'form':'file','record_id':asset.pk,'recipient_module':'1',
            'title':'Updated recipients','original_name':asset.original_name,
            'targets':[team.pk for team in selected]})
        assert response.status_code==302
        asset.refresh_from_db()
        assert not asset.general and not asset.public_copy
        assert asset.blob_key==original_key and Asset.objects.count()==1

    recipients(teams[:1])
    # The same authenticated clients reuse the exact URL; no logout, new link, delay or cache bust.
    for headers in [{},{'HTTP_RANGE':'bytes=0-4'},
                    {'HTTP_IF_MODIFIED_SINCE':'Wed, 21 Oct 2037 00:00:00 GMT'},
                    {'HTTP_IF_NONE_MATCH':'*'}]:
        response=sessions[1].get(url,**headers)
        assert response.status_code==404 and 'no-store' in response['Cache-Control']
        assert b'One shared document' not in response.content
    assert url.encode() not in sessions[1].get('/portal/resources/').content
    for session in [sessions[0],client]:
        response=session.get(url);assert response.status_code==200;response.close()
    recipients(teams[1:])
    assert sessions[0].get(url).status_code==404
    response=sessions[1].get(url);assert response.status_code==200;response.close()
    assert url.encode() in sessions[1].get('/portal/resources/').content
    assert url.encode() not in sessions[0].get('/portal/resources/').content
    from arena.models import EmailDelivery
    assert not EmailDelivery.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_public_access_is_explicit_and_can_be_withdrawn_on_the_same_record(client,event):
    c,r,teams,users,staff=event
    asset=upload(client,event,'public_all',teams)
    asset.scan_status='clean';asset.save()
    client.post('/control/action/',{'action':'approve-file','id':asset.pk})
    team=Client();team.force_login(users[1]);visitor=Client();url=f'/files/{asset.pk}/'
    edit={'form':'file','record_id':asset.pk,'recipient_module':'1',
        'title':'Audience update','original_name':asset.original_name,'targets':[teams[0].pk]}
    # Removing a dashboard recipient does not override intentionally public visitor access.
    assert client.post('/control/',{**edit,'public_visibility':'on'}).status_code==302
    assert url.encode() not in team.get('/portal/resources/').content
    for session in [team,visitor]:
        response=session.get(url);assert response.status_code==200;response.close()
    # Clearing Public in that same editor revokes both guest access and the removed team's link.
    assert client.post('/control/',edit).status_code==302
    for session in [team,visitor]: assert session.get(url).status_code==404
    asset.refresh_from_db()
    assert not asset.public_copy and not asset.public_approved and Asset.objects.count()==1
    response=client.get(url);assert response.status_code==200;response.close()
