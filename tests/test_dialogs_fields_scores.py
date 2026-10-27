import io,json,struct
from datetime import timedelta
from decimal import Decimal
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile as Upload
from django.utils import timezone
from arena.models import Asset,Score,Quarantine,Challenge,Programme
from arena.recordings import result_revision
from arena.scheduling import revision

pytestmark=pytest.mark.django_db

def stamp(value): return timezone.localtime(value).strftime('%Y-%m-%dT%H:%M')

def score(client,r,t,raw,**extra):
    return client.post(f'/control/results/{r.pk}/{t.pk}/',{'revision':result_revision(r,t),'raw':raw,**extra},HTTP_X_ASR_EDITOR='1')

def package():
    from PIL import Image
    image=io.BytesIO();Image.new('RGB',(32,32),'#d9e7f6').save(image,format='JPEG')
    doc=json.dumps({'asset':{'version':'2.0'},'scenes':[{}]}).encode();doc+=b' '*((-len(doc))%4)
    glb=struct.pack('<4sII',b'glTF',2,len(doc)+20)+struct.pack('<II',len(doc),0x4E4F534A)+doc
    return {'wbt':Upload('field.wbt',b'#VRML_SIM R2023b utf8\nWorldInfo {}'),
        'map_json':Upload('controller.json',b'{"tiles":[]}'),
        'info_json':Upload('field-info.json',b'{"name":"Test field","website":"https://example.org/field","dimensions":{"width":12}}'),
        'glb':Upload('field.glb',glb),'jpeg':Upload('field.jpg',image.getvalue())}

def round_data(r,teams,**extra):
    return {'form':'round','record_id':r.pk,'number':r.number,'name':r.name,'starts_at':stamp(r.starts_at),
        'revision':revision(r),'lineup-lineup':json.dumps([{'team':str(t.pk),'duration':15,'gap':0} for t in teams]),
        'recipient_module':'1','targets':[str(teams[0].pk)],**extra}

def test_automatic_normalization_updates_entire_round_and_override_survives(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    assert score(client,r,teams[0],'40').status_code==200
    assert Score.objects.get(team=teams[0]).normalized==1
    assert score(client,r,teams[1],'80').status_code==200
    assert Score.objects.get(team=teams[0]).normalized==Decimal('.5')
    assert score(client,r,teams[0],'40',normalized_override='on',normalized='.75').status_code==200
    assert score(client,r,teams[1],'100').status_code==200
    assert Score.objects.get(team=teams[0]).normalized==Decimal('.75')
    assert score(client,r,teams[0],'40').status_code==200
    assert Score.objects.get(team=teams[0]).normalized==Decimal('.4')
    assert score(client,r,teams[1],'').status_code==200
    assert Score.objects.get(team=teams[1]).normalized is None
    assert Score.objects.get(team=teams[0]).normalized==1
    assert score(client,r,teams[0],'0').status_code==200
    assert Score.objects.get(team=teams[0]).normalized==0
    assert score(client,r,teams[0],'',normalized_override='on',normalized='.5').status_code==200
    assert Score.objects.get(team=teams[0]).raw==0


def test_every_record_editor_returns_complete_form_and_stays_private(client,event):
    c,r,teams,users,staff=event
    quarantine=Quarantine.objects.create(competition=c,name='Request',deadline=r.starts_at)
    challenge=Challenge.objects.create(competition=c,name='Relay')
    client.force_login(staff)
    for kind,id_ in [('round',r.pk),('team',teams[0].pk),('window',r.pk),('quarantine',quarantine.pk),('challenge',challenge.pk),('event',''),('notice',''),('competition',''),('email-settings',''),('managed-upload','')]:
        url=f'/control/?editor={kind}&{kind}={id_}'
        response=client.get(url)
        assert response.status_code==200 and b'<html' not in response.content and b'class="admin-form"' in response.content,(kind,response.status_code)
    response=client.get(f'/control/?editor=round&round={r.pk}')
    for field in ['wbt','map_json','info_json','glb','jpeg','targets','maps_released']:
        assert f'name="{field}"'.encode() in response.content
    assert b'data-lineup-editor' in response.content and b'public_visibility' in response.content
    client.force_login(users[0]);assert client.get(f'/control/?editor=round&round={r.pk}').status_code==302


def test_field_upload_validation_scan_release_recipient_privacy_and_history(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    r.starts_at=timezone.now()-timedelta(hours=2);r.ends_at=timezone.now()-timedelta(hours=1);r.save()
    data=round_data(r,teams,completed='on',maps_released='on',**package())
    response=client.post(f'/control/?editor=round&round={r.pk}',data,HTTP_X_ASR_EDITOR='1')
    assert response.status_code==200 and response.json()['redirect']=='/control/#rounds'
    r.refresh_from_db();assets=list(Asset.objects.filter(round=r));assert len(assets)==5
    assert not r.map_public and not r.map_general and list(r.map_targets.all())==[teams[0]]
    for user in [None,*users]:
        if user: client.force_login(user)
        else: client.logout()
        assert client.get(f'/fields/{r.pk}/').status_code==404
    Asset.objects.filter(round=r).update(scan_status='clean')
    client.force_login(users[0]);page=client.get(f'/fields/{r.pk}/');assert page.status_code==200
    assert b'https://example.org/field' not in page.content and b'controller.json' in page.content
    assert b'field.glb' not in page.content and b'<iframe' in page.content
    field_button=f'data-field="/fields/{r.pk}/?inline=1"'.encode()
    for url in ['/portal/','/portal/resources/','/portal/maps/','/maps/','/']:
        response=client.get(url);assert response.status_code==200 and field_button in response.content
        assert b'Private' in response.content
    inline=client.get(f'/fields/{r.pk}/?inline=1')
    assert b'field-inline' in inline.content and b'masthead' not in inline.content
    glb=next(a for a in assets if a.map_role=='glb')
    assert client.get(f'/field-media/{glb.pk}/')['Content-Type']=='model/gltf-binary'
    assert client.get(f'/field-viewer/{glb.pk}/').status_code==200
    client.force_login(users[1]);assert client.get(f'/field-viewer/{glb.pk}/').status_code==404
    for url in ['/portal/','/portal/resources/','/portal/maps/','/maps/','/']: assert field_button not in client.get(url).content
    client.logout();assert client.get(f'/files/{glb.pk}/').status_code==404
    for url in ['/maps/','/']: assert field_button not in client.get(url).content
    client.force_login(staff)
    response=client.post(f'/control/?editor=round&round={r.pk}',round_data(r,teams,completed='on',maps_released='on',public_visibility='on',map_json=Upload('updated.json',b'{"tiles":[1]}')),HTTP_X_ASR_EDITOR='1')
    assert response.json()['redirect']=='/control/#rounds'
    old=next(a for a in assets if a.map_role=='map_json');old.refresh_from_db();assert not old.current
    Asset.objects.filter(round=r).update(scan_status='clean')
    client.logout();assert client.get(f'/fields/{r.pk}/').status_code==200
    assert b'Field details' in client.get('/maps/').content
    assert field_button in client.get('/').content
    assert client.get(f'/files/{old.pk}/').status_code==404
    client.force_login(staff)
    before=list(Asset.objects.values_list('pk',flat=True))
    response=client.post(f'/control/?editor=round&round={r.pk}',round_data(r,teams,info_json=Upload('bad.json',b'invalid')))
    assert b'errorlist' in response.content and list(Asset.objects.values_list('pk',flat=True))==before


def test_upload_destination_and_team_selection_are_one_module_and_batch_owners_private(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    page=client.get('/control/?editor=managed-upload').content
    assert b'data-recipient-destination' in page and b'type="hidden" name="destination"' in page
    response=client.post('/control/?editor=managed-upload',{'form':'managed-upload','recipient_module':'1','destination':'team',
        'kind':'tdp','targets':[str(t.pk) for t in teams],'files':[Upload('doc.txt',b'private'),Upload('more.bin',b'data')]},HTTP_X_ASR_EDITOR='1')
    assert response.status_code==200 and response.json()['redirect']=='/control/#quarantines'
    assert Asset.objects.count()==4
    for team,user in zip(teams,users):
        client.force_login(user)
        for asset in Asset.objects.all(): assert client.get(f'/files/{asset.pk}/').status_code==(200 if asset.team_id==team.pk else 404)


def test_malformed_field_metadata_cannot_be_published_and_form_errors_stay_in_dialog(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    for payload in [b'{"value":NaN}',b'{"value":Infinity}',b'null']:
        response=client.post(f'/control/?editor=round&round={r.pk}',round_data(r,teams,info_json=Upload('field-info.json',payload)))
        assert b'errorlist' in response.content and b'<html' not in response.content
        assert not Asset.objects.exists()
    response=client.post('/control/?editor=team&team='+str(teams[0].pk),{'form':'team','record_id':teams[0].pk,'name':''},HTTP_X_ASR_EDITOR='1')
    assert response.status_code==200 and b'errorlist' in response.content and b'<html' not in response.content
    client.logout();assert client.get('/control/?editor=competition').status_code==302


def test_dialog_service_error_keeps_a_clear_error_response(client,event):
    from unittest.mock import patch
    from django.core.exceptions import ValidationError
    client.force_login(event[-1])
    with patch('arena.views.save_quarantine',side_effect=ValidationError('The selected team changed. Reopen the request.')):
        response=client.post('/control/?editor=quarantine',{'form':'quarantine','name':'Request','deadline':stamp(event[1].starts_at),'recipient_module':'1','targets':[str(event[2][0].pk)]},HTTP_X_ASR_EDITOR='1')
    assert response.status_code==400 and response.json()['error']=='The selected team changed. Reopen the request.'


def test_whole_field_folder_detects_five_roles_and_preserves_private_files(client,event):
    c,r,teams,users,staff=event;client.force_login(staff)
    files=package();paths=['Round 1/'+file.name for file in files.values()]
    response=client.post(f'/control/?editor=round&round={r.pk}',round_data(r,teams,field_files=list(files.values()),field_paths=json.dumps(paths)),HTTP_X_ASR_EDITOR='1')
    assert response.status_code==200 and response.json()['redirect']=='/control/#rounds'
    assets=list(Asset.objects.filter(round=r));assert {a.map_role for a in assets}==set(files)
    assert next(a for a in assets if a.map_role=='info_json').field_info['website']=='https://example.org/field'
    client.logout();assert client.get(f'/fields/{r.pk}/').status_code==404
    client.force_login(staff)
    before=list(Asset.objects.values_list('pk',flat=True))
    files=package();files['extra']=Upload('second.wbt',b'#VRML_SIM R2023b utf8')
    response=client.post(f'/control/?editor=round&round={r.pk}',round_data(r,teams,field_files=list(files.values())))
    assert b'errorlist' in response.content and list(Asset.objects.values_list('pk',flat=True))==before


def test_folder_json_content_detection_selection_and_path_validation():
    from arena.fields import detect_package
    from django.core.exceptions import ValidationError
    files=package();files['map_json'].name='a.json';files['info_json'].name='b.json'
    assert detect_package(list(files.values()))['info_json'].name=='b.json'
    files['extra']=Upload('alternate.wbt',b'#VRML_SIM R2023b utf8')
    assert detect_package(list(files.values()),choices={'wbt':'field.wbt'})['wbt'].name=='field.wbt'
    with pytest.raises(ValidationError): detect_package(list(files.values()),['../'+f.name for f in files.values()])
    with pytest.raises(ValidationError): detect_package(list(files.values()),choices={'wbt':'missing.wbt'})


def test_folder_detects_thumbnail_among_textures_and_unnamed_map_array():
    from arena.fields import detect_package
    files=package();files['map_json']=Upload('a.json',b'[[0,1],[1,0]]');files['info_json'].name='b.json';files['jpeg'].name='preview.jpg'
    files['texture']=Upload('texture.jpg',b'\xff\xd8\xfftexture\xff\xd9')
    selected=detect_package(list(files.values()))
    assert selected['map_json'].name=='a.json' and selected['info_json'].name=='b.json' and selected['jpeg'].name=='preview.jpg'


def test_field_summary_is_curated_and_preserves_uploaded_statistics():
    from arena.fields import metadata_rows
    info={'envelope_tiles':[5,5],'active_floor_tiles':18,'victims':{'H':1,'S':1,'U':2},
          'obstacles':0,'swamps':1,'checkpoints':1,'black_holes':0,
          'cognitive_targets':{'F':1,'P':0,'C':1,'O':0},
          'maximum_score':508.2,'exit_bonus':21.0,'maximum_mapping_bonus_with_exit':277.2,
          'story':'Internal notes','website':'https://example.org/private-notes',
          'competition_card':{'size':'5x5','tiles':18}}
    rows=metadata_rows(info)
    assert [(row['label'],row['value']) for row in rows]==[
        ('Size','5x5'),('Tiles','18'),('CognitiveTargets','F: 1 · P: 0 · C: 1 · O: 0'),
        ('Victims(H)','1'),('Victims(S)','1'),('Victims(U)','2'),('Obstacles','0'),
        ('Swamps','1'),('Checkpoints','1'),('Black Holes','0'),
        ('Maximum score','508.2'),('Exit bonus','21'),('Maximum mapping bonus','277.2')]
    assert 'Internal notes' not in str(rows) and 'example.org' not in str(rows)
    assert metadata_rows({'envelope_tiles':[10,10]})[0]['value']=='10×10'
    missing=metadata_rows({})
    assert len(missing)==13 and all(row['value']=='—' for row in missing)
    assert metadata_rows(None)==[]


def test_early_finished_round_releases_maps_to_selected_teams_or_public(client,event):
    c,r,teams,users,staff=event
    client.force_login(staff)
    r.starts_at=timezone.now()-timedelta(minutes=5);r.ends_at=timezone.now()+timedelta(minutes=25);r.save()
    url=f'/control/?editor=round&round={r.pk}'
    response=client.post(url,round_data(r,teams,maps_released='on'),HTTP_X_ASR_EDITOR='1')
    assert b'Mark Round completed' in response.content
    r.refresh_from_db();assert not r.completed and not r.maps_released
    response=client.post(url,round_data(r,teams,completed='on',maps_released='on',**package()),HTTP_X_ASR_EDITOR='1')
    assert response.json()['redirect']=='/control/#rounds'
    r.refresh_from_db();assert r.ends_at>timezone.now() and r.maps_open
    assets=Asset.objects.filter(round=r)
    client.force_login(users[0]);assert client.get(f'/fields/{r.pk}/').status_code==404
    assets.update(scan_status='clean')
    assert client.get(f'/fields/{r.pk}/').status_code==200
    client.force_login(users[1]);assert client.get(f'/fields/{r.pk}/').status_code==404
    client.logout();assert client.get(f'/fields/{r.pk}/').status_code==404
    client.force_login(staff)
    response=client.post(url,round_data(r,teams,completed='on',maps_released='on',public_visibility='on'),HTTP_X_ASR_EDITOR='1')
    assert response.json()['redirect']=='/control/#rounds'
    client.logout();assert client.get(f'/fields/{r.pk}/').status_code==200
    assert f'data-field="/fields/{r.pk}/?inline=1"'.encode() in client.get('/').content
    wbt=assets.get(map_role='wbt');assert client.get(f'/files/{wbt.pk}/').status_code==200
    client.force_login(staff)
    r.refresh_from_db()
    assert client.post(url,round_data(r,teams,completed='on'),HTTP_X_ASR_EDITOR='1').json()['redirect']=='/control/#rounds'
    client.logout();assert client.get(f'/fields/{r.pk}/').status_code==404
    assert client.get(f'/files/{wbt.pk}/').status_code==404


def test_map_downloads_only_offer_world_and_map_json_but_keep_preview_and_admin_access(client,event):
    c,r,teams,users,staff=event
    r.starts_at=timezone.now()-timedelta(minutes=5);r.save()
    client.force_login(staff)
    url=f'/control/?editor=round&round={r.pk}'
    assert client.post(url,round_data(r,teams,completed='on',maps_released='on',**package()),HTTP_X_ASR_EDITOR='1').json()['redirect']=='/control/#rounds'
    Asset.objects.filter(round=r).update(scan_status='clean')
    assets=list(Asset.objects.filter(round=r))
    for asset in assets: assert client.get(f'/files/{asset.pk}/').status_code==200
    for path in ['/maps/','/',f'/fields/{r.pk}/']:
        html=client.get(path).content
        for asset in assets:
            assert (f'href="/files/{asset.pk}/"'.encode() in html)==(asset.map_role in ['wbt','map_json'])
    # Full map files remain available in the organizer's round editor.
    html=client.get(url).content
    for asset in assets: assert asset.original_name.encode() in html
    for public in [False,True]:
        if public:
            r.refresh_from_db();client.force_login(staff)
            assert client.post(url,round_data(r,teams,completed='on',maps_released='on',public_visibility='on'),HTTP_X_ASR_EDITOR='1').json()['redirect']=='/control/#rounds'
        for user in [users[0],None]:
            if user: client.force_login(user)
            else: client.logout()
            if not public and user is None:
                for asset in assets: assert client.get(f'/files/{asset.pk}/').status_code==404
                continue
            for path in [f'/fields/{r.pk}/','/maps/','/']+(['/portal/maps/'] if user else []):
                html=client.get(path).content
                for asset in assets:
                    downloadable=asset.map_role in ['wbt','map_json']
                    assert (f'href="/files/{asset.pk}/"'.encode() in html)==downloadable
                    if not downloadable: assert asset.original_name.encode() not in html
            for asset in assets:
                assert client.get(f'/files/{asset.pk}/').status_code==(200 if asset.map_role in ['wbt','map_json'] else 404)
            model=next(a for a in assets if a.map_role=='glb');preview=next(a for a in assets if a.map_role=='jpeg')
            assert client.get(f'/field-viewer/{model.pk}/').status_code==200
            assert client.get(f'/field-media/{model.pk}/').status_code==200
            assert client.get(f'/field-media/{preview.pk}/').status_code==200
