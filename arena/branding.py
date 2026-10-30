"""Public branding images are decoded and re-encoded; private uploads are never exposed."""
import io,re,uuid,warnings
from PIL import Image,ImageOps
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import FileResponse,Http404
from django.shortcuts import get_object_or_404
from django.utils.cache import patch_cache_control
from django.views.decorators.http import require_GET
from .models import Competition

SLOTS={'logo':'logo_key','partner':'partner_logo_key','banner':'banner_key'}

def normalize_image(upload):
    if upload.size>10*1024*1024:raise ValidationError('Choose an image smaller than 10 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(upload) as source:
                image=ImageOps.exif_transpose(source);image.thumbnail((2048,2048))
                output=io.BytesIO();image.convert('RGBA').save(output,'PNG')
                return output.getvalue()
    except (OSError,ValueError,SyntaxError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise ValidationError('Choose a valid PNG, JPEG, WebP, GIF or other supported raster image. SVG and HTML are not accepted.')
    finally:upload.seek(0)


def store_image(competition,data):
    return default_storage.save(f'branding/{competition.pk}/{uuid.uuid4().hex}.png',ContentFile(data))


@require_GET
def image(request,competition_id,slot):
    field=SLOTS.get(slot)
    if not field:raise Http404()
    competition=get_object_or_404(Competition,pk=competition_id)
    key=getattr(competition,field)
    if not re.fullmatch(r'branding/'+str(competition.pk)+r'/[a-f0-9]{32}\.png',key):raise Http404()
    try:stream=default_storage.open(key,'rb')
    except (OSError,ValueError):raise Http404()
    response=FileResponse(stream,content_type='image/png')
    response['Content-Security-Policy']="default-src 'none'; sandbox"
    response['X-Content-Type-Options']='nosniff'
    response['ETag']='"'+key.rsplit('/',1)[-1]+'"'
    patch_cache_control(response,no_cache=True,must_revalidate=True)
    return response
