"""Regression coverage for private/public boundaries and bounded resources."""
import json,io,uuid
from pathlib import Path
from unittest.mock import patch,MagicMock
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError,RequestDataTooBig
from django.http import HttpResponse
from django.test import RequestFactory
from django.core.files.storage import default_storage
from arena.models import RunRecording,Asset,EmailDelivery
from arena.recordings import recording_key,recording_result_data,match_result
from arena.services import upload_asset,announce
from arena.uploads import BoundedUploadHandler
from arena.middleware import ProxyAddressMiddleware
from tests.test_results_recordings import export_zip,post_result
pytestmark=pytest.mark.django_db

@pytest.mark.parametrize('name',['controller.py','private-controller.json','team-tdp.pdf','.env','controller.js','service-account.json'])
def test_replay_rejects_unrelated_private_files_without_replacing_scores(client,event,name):
    client.force_login(event[4]);assert post_result(client,event,export_zip()).status_code==302
    before=RunRecording.objects.get()
    result=post_result(client,event,export_zip(**{'run/'+name:b'private-test-marker'}))
    assert result.status_code==200 and b'Unexpected private or unrelated file' in result.content
    assert RunRecording.objects.get().pk==before.pk


@pytest.mark.django_db(transaction=True)
def test_replay_animation_and_result_json_are_explicitly_public(client,event):
    client.force_login(event[4]);event[1].completed=True;event[1].save()
    result=json.dumps({'final_score':123.45,'events':[]}).encode()
    assert post_result(client,event,export_zip(**{'run/match-result.json':result}),published='on').status_code==302
    rec=RunRecording.objects.get();client.logout()
    url=client.get(f'/recordings/{rec.pk}/player/').json()['url'].split('#')[0]
    for path in ['run/replay.json','run/match-result.json','run/replay.x3d']:
        response=client.get(url.replace(rec.entry_path,path));assert response.status_code==200;response.close()


def test_provider_generated_keys_support_replay_and_metadata(client,event):
    client.force_login(event[4]);save=default_storage.save
    def provider_save(key,file):return save('provider/'+uuid.uuid4().hex,file)
    metadata=b'{"final_score":123.45,"elapsed_seconds":90}'
    with patch('arena.recordings.default_storage.save',side_effect=provider_save):
        assert post_result(client,event,export_zip(**{'run/match-result.json':metadata})).status_code==302
    rec=RunRecording.objects.get()
    assert all(item['storage_key'].startswith('provider/') for item in rec.manifest.values())
    assert match_result(rec)['scores']['final_score']=='123.45'
    player=client.get(f'/recordings/{rec.pk}/player/').json()
    response=client.get(player['url']);assert response.status_code==200
    preview=client.get(f'/recordings/{rec.pk}/preview/');assert preview.status_code==200;preview.close()
    # Legacy local manifests remain readable without a migration.
    assert recording_key(type('Legacy',(),{'pk':rec.pk,'manifest':{'old.json':{'size':1}}})(),'old.json')==f'recordings/{rec.pk}/old.json'


def test_xml_entities_are_rejected(client,event):
    client.force_login(event[4])
    scene=b'<!DOCTYPE X3D [<!ENTITY test "AUDIT-ONLY">]><X3D><Scene><Transform id="n1" DEF="&test;"/></Scene></X3D>'
    response=post_result(client,event,export_zip(**{'run/replay.x3d':scene}))
    assert response.status_code==200 and b'not valid XML' in response.content and not RunRecording.objects.exists()


def test_upload_handler_limits_actual_bytes_and_never_saves_a_partial_batch(settings):
    settings.UPLOAD_MAX_FILE_BYTES=4;settings.UPLOAD_MAX_BATCH_BYTES=8
    handler=BoundedUploadHandler();handler.new_file('file','test.bin','application/octet-stream',None)
    assert handler.receive_data_chunk(b'abcd',0)==b'abcd'
    with pytest.raises(RequestDataTooBig):handler.receive_data_chunk(b'e',4)


def test_oversized_request_is_rejected_before_form_side_effects(client,event,settings):
    client.force_login(event[3][0]);settings.UPLOAD_MAX_BATCH_BYTES=20
    response=client.post(f'/submit/round_file/{event[1].pk}/',{'files':SimpleUploadedFile('x',b'x'*30),'attested':'on'})
    assert response.status_code==413 and not Asset.objects.exists()


def test_storage_allowance_and_stream_limit_clean_up_rejected_file(event,settings):
    settings.UPLOAD_MAX_FILE_BYTES=3
    with pytest.raises(ValidationError):upload_asset(user=event[3][0],team=event[2][0],round_=event[1],kind='round_file',file=SimpleUploadedFile('a',b'abcd'),attested=True)
    settings.UPLOAD_MAX_FILE_BYTES=10;settings.UPLOAD_TEAM_MAX_BYTES=2
    with pytest.raises(ValidationError):upload_asset(user=event[3][0],team=event[2][0],round_=event[1],kind='round_file',file=SimpleUploadedFile('a',b'abc'),attested=True)
    assert not Asset.objects.exists()


def test_zip_and_folder_extraction_share_a_fixed_budget(client,event,settings):
    client.force_login(event[4]);settings.RECORDING_MAX_EXTRACTED_BYTES=20
    response=post_result(client,event,export_zip())
    assert response.status_code==200 and not RunRecording.objects.exists()


def test_proxy_header_requires_matching_ingress_secret(settings):
    settings.TRUST_PROXY_CLIENT_IP=True;settings.PROXY_SHARED_SECRET='test-ingress-secret'
    factory=RequestFactory();middleware=ProxyAddressMiddleware(lambda r:r.META['REMOTE_ADDR'])
    for token in ['', 'wrong']:
        assert middleware(factory.get('/',REMOTE_ADDR='192.0.2.1',HTTP_X_ASR_CLIENT_IP='203.0.113.99',HTTP_X_ASR_PROXY_TOKEN=token))=='192.0.2.1'
    assert middleware(factory.get('/',REMOTE_ADDR='192.0.2.1',HTTP_X_ASR_CLIENT_IP='203.0.113.99',HTTP_X_ASR_PROXY_TOKEN='test-ingress-secret'))=='203.0.113.99'


def test_rate_limit_is_shared_across_download_ids(client,event):
    from arena.models import RequestQuota
    client.force_login(event[3][0])
    assert client.get('/files/'+str(uuid.uuid4())+'/').status_code==404
    RequestQuota.objects.update(count=180)
    assert client.get('/files/'+str(uuid.uuid4())+'/').status_code==429


def test_mail_backpressure_preserves_generic_reset_and_notice_atomicity(client,event,settings):
    settings.MAIL_MAX_PENDING=0
    event[3][0].email='mentor@example.test';event[3][0].save()
    response=client.post('/accounts/reset/',{'email':event[3][0].email})
    assert response.status_code==302 and not EmailDelivery.objects.exists()
    with pytest.raises(ValidationError):announce(user=event[4],competition=event[0],title='Queue full',body='Test',general=True,public=False,target_ids=[])
    assert not event[0].announcement_set.exists()


def test_drive_size_uses_provider_metadata():
    from arena.drive_storage import PrivateDriveStorage
    provider=MagicMock();provider.files.return_value.get.return_value.execute.return_value={'size':'123'}
    with patch.object(PrivateDriveStorage,'service',return_value=provider):assert PrivateDriveStorage().size('provider-id')==123


def test_readiness_is_no_store_and_does_not_depend_on_mail(client,event,settings,tmp_path):
    settings.PRIVATE_ROOT=tmp_path
    response=client.get('/ready/');assert response.status_code==200 and response.json()=={'status':'ok'}
    assert 'no-store' in response['Cache-Control']
    settings.UPLOAD_MIN_FREE_BYTES=10**30
    response=client.get('/ready/');assert response.status_code==503 and response.json()=={'status':'unavailable'}


def test_legacy_recording_cannot_serve_private_extra_files(client,event):
    client.force_login(event[4]);event[1].completed=True;event[1].save()
    assert post_result(client,event,export_zip(),published='on').status_code==302
    rec=RunRecording.objects.get()
    key=default_storage.save(f'recordings/{rec.pk}/run/private.json',SimpleUploadedFile('private.json',b'private'))
    rec.manifest['run/private.json']={'size':7,'sha256':'legacy'};rec.save()
    client.logout();url=client.get(f'/recordings/{rec.pk}/player/').json()['url'].split('#')[0]
    assert client.get(url.replace(rec.entry_path,'run/private.json')).status_code==404


def test_authentication_body_has_its_own_small_budget(client,settings):
    settings.UPLOAD_MAX_BATCH_BYTES=2*1024**3
    assert client.post('/account/login/',{'junk':'x'*70000}).status_code==413


def test_unauthenticated_superteam_upload_is_denied_before_body_parsing(client,event):
    path=f'/portal/superteams/{event[2][0].pk}/submit/round_file/{event[1].pk}/'
    assert client.post(path,{'files':SimpleUploadedFile('a.bin',b'abc')}).status_code in [302,403]
    assert not Asset.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_cached_thumbnail_still_checks_current_recipient_access(client,event):
    from arena.models import Asset
    from tests.test_field_images import picture
    from tests.test_dialogs_fields_scores import round_data
    from arena.fields import thumbnail_preview
    client.force_login(event[4]);upload,_=picture('PNG','png')
    client.post(f'/control/?editor=round&round={event[1].pk}',round_data(event[1],event[2],completed='on',maps_released='on',jpeg=upload),HTTP_X_ASR_EDITOR='1')
    asset=Asset.objects.get(round=event[1],map_role='jpeg');asset.scan_status='clean';asset.save()
    client.force_login(event[3][0])
    with patch('arena.fields.thumbnail_preview',wraps=thumbnail_preview) as render:
        for _ in range(2):
            response=client.get(f'/field-media/{asset.pk}/');assert response.status_code==200;response.close()
        assert render.call_count==1
    client.force_login(event[3][1]);assert client.get(f'/field-media/{asset.pk}/').status_code==404


def test_private_files_are_owner_readable_only_on_disk(event):
    import stat
    item=upload_asset(user=event[3][0],team=event[2][0],round_=event[1],kind='round_file',file=SimpleUploadedFile('a',b'private'),attested=True)
    assert stat.S_IMODE(Path(default_storage.path(item.blob_key)).stat().st_mode)==0o600


def test_production_defaults_require_mfa_and_bounded_connections():
    import os,subprocess,sys
    env=dict(os.environ,DJANGO_DEBUG='0',DJANGO_SECRET_KEY='TEST-ONLY-NOT-A-PRODUCTION-KEY-123456789012345678901234567890',PUBLIC_ORIGIN='https://rescue.example.test',DATABASE_URL='postgres://audit:audit@127.0.0.1:65432/audit')
    for name in ['REQUIRE_STAFF_OTP','TRUST_PROXY_CLIENT_IP']:env.pop(name,None)
    check="from config import settings as s; assert s.REQUIRE_STAFF_OTP; assert s.DATABASES['default']['CONN_MAX_AGE']==0; assert s.DATABASES['default']['OPTIONS']['pool']['max_size']==4; assert s.SESSION_COOKIE_SECURE"
    subprocess.run([sys.executable,'-c',check],env=env,check=True)


def test_recovery_refuses_overlapping_operations(monkeypatch,tmp_path):
    import importlib.util
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('recovery_check',root/'scripts/recovery.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module.tempfile,'gettempdir',lambda:str(tmp_path))
    with module.operation_lock('rcj-restore-test'):
        with pytest.raises(ValueError,match='Another recovery'):
            with module.operation_lock('rcj-restore-test'):pass
    with module.operation_lock('rcj-restore-test'):pass


def test_image_decode_budget_rejects_pixel_bombs(monkeypatch):
    from PIL import Image
    from arena.fields import validate_field
    from tests.test_field_images import picture
    file,_=picture('PNG','png');monkeypatch.setattr(Image,'MAX_IMAGE_PIXELS',10)
    with pytest.raises(ValidationError):validate_field(file,'jpeg')
