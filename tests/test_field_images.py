import io
from datetime import timedelta
import pytest
from PIL import Image
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile as Upload
from django.core.files.storage import default_storage
from django.utils import timezone
from arena.fields import validate_field,detect_package
from arena.models import Asset
from tests.test_dialogs_fields_scores import package,round_data

pytestmark=pytest.mark.django_db


def picture(format_,suffix):
    if format_=='SVG': data=b'<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" fill="#4780ba"/></svg>'
    else:
        buffer=io.BytesIO();Image.new('RGB',(32,32),'#4780ba').save(buffer,format=format_);data=buffer.getvalue()
    return Upload('thumbnail.'+suffix,data),data


@pytest.mark.parametrize('format_,suffix',[('JPEG','jpg'),('PNG','png'),('WEBP','webp'),('GIF','gif'),('AVIF','avif'),('HEIF','heic'),('TIFF','tiff'),('BMP','bmp'),('ICO','ico'),('SVG','svg')])
def test_image_formats_preserve_original_and_render_only_to_allowed_team(client,event,format_,suffix):
    c,r,teams,users,staff=event;client.force_login(staff)
    r.starts_at=timezone.now()-timedelta(hours=2);r.ends_at=timezone.now()-timedelta(hours=1);r.save()
    upload,original=picture(format_,suffix)
    response=client.post(f'/control/?editor=round&round={r.pk}',round_data(r,teams,completed='on',maps_released='on',jpeg=upload),HTTP_X_ASR_EDITOR='1')
    assert response.status_code==200 and 'redirect' in response.json(),response.content
    asset=Asset.objects.get(round=r,map_role='jpeg')
    with default_storage.open(asset.blob_key) as file: assert file.read()==original
    client.logout();assert client.get(f'/field-media/{asset.pk}/').status_code==404
    Asset.objects.filter(pk=asset.pk).update(scan_status='clean')
    client.force_login(users[0]);response=client.get(f'/field-media/{asset.pk}/')
    assert response.status_code==200 and response['Content-Type']==('image/svg+xml' if format_=='SVG' else 'image/png')
    assert 'sandbox' in response['Content-Security-Policy'] and response['X-Content-Type-Options']=='nosniff'
    data=b''.join(response.streaming_content)
    if format_!='SVG': assert Image.open(io.BytesIO(data)).size==(32,32)
    client.force_login(users[1]);assert client.get(f'/field-media/{asset.pk}/').status_code==404


def test_folder_detection_accepts_non_jpeg_thumbnail_and_rejects_invalid_or_active_images():
    files=package();files['jpeg'],_=picture('PNG','png')
    assert detect_package(list(files.values()))['jpeg'].name=='thumbnail.png'
    # File content determines decoding, even if its filename has a different suffix.
    files['jpeg'].name='thumbnail.jpg';validate_field(files['jpeg'],'jpeg')
    for content in [b'not an image',b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
        b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>']:
        with pytest.raises(ValidationError): validate_field(Upload('image.svg',content),'jpeg')
