"""Round field packages share the existing private storage and malware scan gates."""
import io, json, struct, warnings
from pathlib import PurePath
from django import forms
from django.core.cache import cache
from django.conf import settings
from .media_validation import bounded_read
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET
from .access import can_download, public_asset, MAP_DOWNLOAD_ROLES
from .models import Asset, Round
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

register_heif_opener()
Image.MAX_IMAGE_PIXELS=settings.IMAGE_MAX_PIXELS
IMAGE_SUFFIXES=set(Image.registered_extensions()) | {'.svg'}


def thumbnail_preview(file,name=None):
    """Keep the original upload; decode a browser-compatible, non-scriptable preview."""
    try:
        data=bounded_read(file)
        if PurePath(name or file.name).suffix.lower()=='.svg' or data.lstrip().startswith(b'<'):
            root=ElementTree.fromstring(data)
            if root.tag!='{http://www.w3.org/2000/svg}svg': raise ValueError()
            for node in root.iter():
                if node.tag.rsplit('}',1)[-1] in ['script','foreignObject']: raise ValueError()
                for key,value in node.attrib.items():
                    if key.lower().startswith('on') or key.rsplit('}',1)[-1]=='href' and not value.startswith(('#','data:image/')): raise ValueError()
            return data,'image/svg+xml'
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                preview=ImageOps.exif_transpose(source)
                preview.thumbnail((1600,1600))
                output=io.BytesIO();preview.convert('RGBA').save(output,format='PNG')
                return output.getvalue(),'image/png'
    except (OSError,ValueError,SyntaxError,EOFError,RuntimeError,DefusedXmlException,Image.DecompressionBombError,Image.DecompressionBombWarning) as exc:
        raise ValidationError('Choose a valid image file. This image could not be decoded safely.') from exc
    finally: file.seek(0)

def reject_constant(value):
    raise ValueError('Non-finite JSON number')


ROLES={'wbt':('Webots world · WBT','.wbt'),'map_json':('Controller / map JSON','.json'),
    'info_json':('Field information · JSON','.json'),'glb':('3D field model · GLB','.glb'),'jpeg':('Field thumbnail · Image','.jpg')}


def validate_field(file,role):
    suffix=PurePath(file.name).suffix.lower()
    if role!='jpeg' and suffix!=ROLES[role][1]: raise ValidationError('Choose the file type shown in this field.')
    info={}
    try:
        if role in ['map_json','info_json']:
            data=json.loads(bounded_read(file),parse_constant=reject_constant)
            if not isinstance(data,(dict,list)): raise ValueError()
            if role=='info_json': info=data
        elif role=='wbt':
            if not file.read(100).startswith(b'#VRML_SIM'): raise ValueError()
        elif role=='jpeg':
            thumbnail_preview(file)
        elif role=='glb':
            header=file.read(12)
            if len(header)!=12 or struct.unpack('<4sII',header)!=(b'glTF',2,file.size): raise ValueError()
            chunk=file.read(8)
            length,kind=struct.unpack('<II',chunk)
            if kind!=0x4E4F534A or length>min(file.size-20,settings.VALIDATION_MAX_BYTES): raise ValueError()
            data=json.loads(file.read(length),parse_constant=reject_constant)
            if not isinstance(data,dict) or not data.get('scenes'): raise ValueError()
            # A field GLB must be self-contained; no surprise cross-origin requests.
            for item in data.get('buffers',[])+data.get('images',[]):
                uri=item.get('uri','')
                if uri and not uri.startswith('data:'): raise ValidationError('Export a self-contained GLB with embedded textures and meshes.')
    except (ValueError,TypeError,KeyError,UnicodeError,OSError,struct.error,OverflowError):
        raise ValidationError('This file is not a valid '+ROLES[role][0]+'.')
    finally: file.seek(0)
    return info


def detect_package(files, paths=None, choices=None):
    """Identify one complete package; ambiguous roles require explicit selection."""
    from .recordings import safe_path
    import re
    paths=paths if paths is not None else [file.name for file in files]
    if not isinstance(paths,list) or len(paths)!=len(files): raise ValidationError('Select the field folder again.')
    entries={};seen=set()
    for file,path in zip(files,paths):
        path=safe_path(path)
        if path.casefold() in seen: raise ValidationError('The folder contains duplicate paths.')
        seen.add(path.casefold())
        if not PurePath(path).name.startswith('.') and '__MACOSX' not in PurePath(path).parts: entries[path]=file
    choices=choices or {}
    if not isinstance(choices,dict) or set(choices)-set(ROLES): raise ValidationError('Choose valid field file roles.')
    selected={};used=set()
    for role in ROLES:
        suffixes=IMAGE_SUFFIXES if role=='jpeg' else [ROLES[role][1]]
        candidates=[path for path in entries if (PurePath(path).suffix.lower() in suffixes or role=='jpeg' and getattr(entries[path],'content_type','').startswith('image/')) and path not in used]
        if choices.get(role): candidates=[path for path in candidates if path==choices[role]]
        elif role in ['info_json','map_json']:
            info=[path for path in candidates if re.search(r'(?:field[ _.-]*)?info(?:rmation)?|metadata',PurePath(path).stem,re.I)]
            maps=[path for path in candidates if path not in info]
            if role=='info_json' and len(info)==1: candidates=info
            elif role=='map_json' and len(maps)==1: candidates=maps
            else:
                # Distinguish metadata from map geometry without depending on a fixed schema.
                metadata=[];geometry=[]
                for path in candidates:
                    stream=entries[path]
                    try: data=json.loads(bounded_read(stream),parse_constant=reject_constant)
                    except (ValueError,UnicodeError): continue
                    finally: stream.seek(0)
                    if isinstance(data,dict):
                        keys={str(key).lower().replace('_','') for key in data}
                        if keys & {'tiles','grid','rooms','cells','map','walls'}: geometry.append(path)
                        elif keys & {'website','author','description','dimensions','fieldname','name'}: metadata.append(path)
                preferred=metadata if role=='info_json' else geometry or [path for path in candidates if path not in metadata]
                if len(preferred)==1: candidates=preferred
        elif len(candidates)>1 and role!='wbt':
            worlds=[path for path in entries if PurePath(path).suffix.lower()=='.wbt']
            matching=[path for path in candidates if any(PurePath(path).with_suffix('')==PurePath(world).with_suffix('') for world in worlds)]
            if len(matching)==1: candidates=matching
            elif role=='jpeg':
                previews=[path for path in candidates if re.search(r'preview|thumbnail|thumb',PurePath(path).stem,re.I)]
                if len(previews)==1: candidates=previews
        if len(candidates)!=1 or candidates[0] in used:
            raise ValidationError('Choose one '+ROLES[role][0]+' in the folder’s detected file list.' if candidates else 'The folder is missing '+ROLES[role][0]+'.')
        path=candidates[0];used.add(path);selected[role]=entries[path]
    return selected


def save_maps(form,user):
    from .services import upload_asset
    created=[]
    try:
        for role in ROLES:
            file=form.cleaned_data.get(role)
            if not file: continue
            asset=upload_asset(user=user,file=file,kind='map',round_=form.instance,title=form.instance.name or str(form.instance),append=True)
            created.append(asset)
            Asset.objects.filter(round=form.instance,kind='map',map_role=role,current=True).exclude(pk=asset.pk).update(current=False,public_approved=False)
            asset.map_role=role;asset.field_info=form.map_metadata.get(role,{})
            asset.public_approved=True # Explicit organizer upload; still requires clean scan + round release.
            asset.save(update_fields=['map_role','field_info','public_approved'])
        return created
    except Exception:
        for asset in created: default_storage.delete(asset.blob_key)
        raise


def field_assets(round_,user):
    return [a for a in Asset.objects.filter(round=round_,kind='map',current=True,deleted_at=None).select_related('round__challenge','competition') if can_download(user,a)]


def field_packages(rounds,user):
    packages=[]
    for round_ in rounds:
        files=field_assets(round_,user)
        if files:
            packages.append({'round':round_,'preview':next((a for a in files if a.map_role=='jpeg'),None),
                'files':files,'downloads':[a for a in files if a.map_role in MAP_DOWNLOAD_ROLES],'public':any(public_asset(a) for a in files)})
    return packages


def metadata_rows(info):
    """The public field summary uses an explicit, stable list of map statistics."""
    if not isinstance(info,dict): return []
    def keys(values):
        return {str(key).replace('_','').replace(' ','').casefold():value for key,value in values.items()}
    root=keys(info)
    card=root.get('competitioncard',{})
    values={**root,**(keys(card) if isinstance(card,dict) else {})}
    def value(*names):
        return next((values[name] for name in names if values.get(name) is not None),'—')
    def display(item):
        if isinstance(item,dict):
            return ' · '.join(f'{key}: {display(count)}' for key,count in item.items() if isinstance(count,(str,int,float))) or '—'
        if isinstance(item,(list,tuple)): return '×'.join(str(part) for part in item)
        if isinstance(item,float) and item.is_integer(): return str(int(item))
        return str(item) if isinstance(item,(str,int,float)) else '—'
    victims=values.get('victims',{})
    victims=keys(victims) if isinstance(victims,dict) else {}
    summary=[
        ('Size',value('size','envelopetiles')),
        ('Tiles',value('tiles','activefloortiles')),
        ('CognitiveTargets',value('cognitivetargets')),
        *[(f'Victims({kind})',values.get(f'victims{kind.lower()}',victims.get(kind.lower(),'—'))) for kind in ('H','S','U')],
        ('Obstacles',value('obstacles')),
        ('Swamps',value('swamps')),
        ('Checkpoints',value('checkpoints')),
        ('Black Holes',value('blackholes')),
        ('Maximum score',value('maximumscore','perfectmapplusexitscore')),
        ('Exit bonus',value('exitbonus')),
        ('Maximum mapping bonus',value('maximummappingbonuswithexit','maximummappingbonus')),
    ]
    return [{'label':label,'value':display(item)} for label,item in summary]


def attach_maximum_scores(rounds):
    """Expose only the map's stated maximum, never its unreleased files or geometry."""
    from decimal import Decimal, InvalidOperation
    maxima={}
    assets=Asset.objects.filter(round_id__in={r.pk for r in rounds},kind='map',map_role='info_json',current=True,deleted_at=None,scan_status='clean').order_by('-created_at')
    for asset in assets:
        if asset.round_id in maxima: continue
        value=next(row['value'] for row in metadata_rows(asset.field_info) if row['label']=='Maximum score')
        try: maximum=Decimal(value)
        except InvalidOperation: continue
        if maximum.is_finite() and maximum>=0: maxima[asset.round_id]=maximum
    for round_ in rounds: round_.maximum_score=maxima.get(round_.pk)

@require_GET
def detail(request,round_id):
    round_=get_object_or_404(Round.objects.select_related('competition','challenge'),pk=round_id)
    files=field_assets(round_,request.user)
    if not files: raise Http404()
    by_role={a.map_role:a for a in files if a.map_role}
    response=render(request,'arena/field.html',{'round':round_,'files':files,'downloads':[a for a in files if a.map_role in MAP_DOWNLOAD_ROLES],'preview':by_role.get('jpeg'),
        'model':by_role.get('glb'),'field_rows':metadata_rows(by_role['info_json'].field_info) if 'info_json' in by_role else [],
        'inline':request.GET.get('inline')=='1','field_base':'arena/field_shell.html' if request.GET.get('inline')=='1' else 'base.html'})
    response['X-Frame-Options']='SAMEORIGIN'
    response['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; frame-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
    response['Cache-Control']='private, no-store'
    return response


@require_GET
def media(request,asset_id):
    asset=get_object_or_404(Asset.objects.select_related('round__challenge','competition'),pk=asset_id,kind='map',map_role__in=['jpeg','glb'])
    if not can_download(request.user,asset): raise Http404()
    try: stream=default_storage.open(asset.blob_key,'rb')
    except OSError: raise Http404()
    if asset.map_role=='jpeg':
        # Authorization always runs before retrieving an in-process derivative.
        key=f'field-thumbnail:{asset.pk}:{asset.sha256}'
        try:
            derivative=cache.get(key)
            if derivative is None:
                derivative=thumbnail_preview(stream,asset.original_name);cache.set(key,derivative)
            data,mime=derivative
        except ValidationError: stream.close();raise Http404('Thumbnail temporarily unavailable.')
        stream.close();stream=io.BytesIO(data)
    else: mime='model/gltf-binary'
    response=FileResponse(stream,content_type=mime)
    response['Content-Security-Policy']="sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"
    response['Cache-Control']='private, no-store';response['X-Content-Type-Options']='nosniff'
    return response


@require_GET
def viewer(request,asset_id):
    asset=get_object_or_404(Asset.objects.select_related('round__challenge','competition'),pk=asset_id,kind='map',map_role='glb')
    if not can_download(request.user,asset): raise Http404()
    response=render(request,'arena/field_viewer.html',{'asset':asset})
    response['Content-Security-Policy']="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; worker-src blob:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
    response['X-Frame-Options']='SAMEORIGIN';response['Cache-Control']='private, no-store'
    return response
