"""Validate complete Webots exports; retain immutable files and their original paths."""
import hashlib
import ipaddress
import json
import math
import posixpath
import re
import stat
import tempfile
import zipfile
import uuid
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django import forms
from django.conf import settings
from defusedxml import ElementTree as SafeXML
from defusedxml.common import DefusedXmlException
from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.files.storage import default_storage
from django.db import transaction
from .forms import MultipleFileField, MultipleFileInput
from .media_validation import bounded_read
from .models import RunRecording, Score, Team
from .timing import RemainingTimeField, RUN_ALLOWANCE_SECONDS


def round_scores_revision(round_,teams,scores=None):
    if scores is None: scores=Score.objects.filter(round=round_)
    values={'teams':sorted(str(team.pk) for team in teams),
        'round':[round_.challenge_id,round_.zero_score_policy,str(round_.archived_at),
            round_.challenge.calculation if round_.challenge_id else None],
        'scores':[{name:getattr(score,name) for name in ['team_id','raw','normalized','normalized_override','elapsed_seconds']}
            for score in sorted(scores,key=lambda score:str(score.team_id))]}
    return hashlib.sha256(json.dumps(values,default=str,sort_keys=True).encode()).hexdigest()


class RoundScoresForm(forms.Form):
    revision=forms.CharField(widget=forms.HiddenInput)
    def __init__(self,*args,round_,matrix=False,teams=None,scores=None,matrix_id=None,**kwargs):
        self.round=round_
        self.teams=list(teams) if teams is not None else list(Team.objects.participants(round_.challenge).filter(competition=round_.competition,active=True).order_by('name'))
        self.scores={score.team_id:score for score in (scores if scores is not None else Score.objects.filter(round=round_))}
        self.field_scoring=bool(round_.challenge_id and round_.challenge.calculation=='trimmed_mean')
        self.overrides=matrix and not self.field_scoring
        super().__init__(*args,auto_id=f'round_{round_.pk}_%s',**kwargs)
        self.initial['revision']=round_scores_revision(round_,self.teams,self.scores.values())
        form_id=(matrix_id or 'score-matrix') if matrix else f'round-scores-{round_.pk}'
        for team in self.teams:
            name=f'raw_{team.pk}';score=self.scores.get(team.pk)
            self.fields[name]=forms.DecimalField(max_digits=14,decimal_places=4,required=False,
                min_value=0 if self.field_scoring else None,label=f'Raw score for {team.name}',
                widget=forms.NumberInput(attrs={'form':form_id,'class':'score-input',
                    'step':'0.0001','inputmode':'decimal','data-raw-score':str(team.pk),
                    'aria-label':f'Raw score for {team.name} in {round_}'}))
            self.initial[name]=format(score.raw.normalize(),'f') if score and score.raw is not None else None
            time_name=f'remaining_{team.pk}'
            self.fields[time_name]=RemainingTimeField()
            self.fields[time_name].widget.attrs.update({'form':form_id,'class':'score-time-input',
                'aria-label':f'Remaining time for {team.name} in {round_}, out of 8 minutes'})
            self.initial[time_name]=score.remaining_seconds if score else None
            if self.overrides:
                self.fields[f'normalized_{team.pk}']=forms.DecimalField(max_digits=14,decimal_places=4,required=False,
                    widget=forms.NumberInput(attrs={'form':form_id,'step':'0.0001','class':'score-input','data-score-manual':'',
                        'aria-label':f'Normalized override for {team.name} in {round_}'}))
                self.fields[f'override_{team.pk}']=forms.BooleanField(required=False,widget=forms.CheckboxInput(attrs={
                    'form':form_id,'data-score-override':'','aria-label':f'Use normalized override for {team.name} in {round_}'}))
                self.initial[f'normalized_{team.pk}']=score.normalized if score else None
                self.initial[f'override_{team.pk}']=score.normalized_override if score else False
    def clean(self):
        data=super().clean()
        if any(self.add_prefix(f'raw_{team.pk}') not in self.data for team in self.teams):
            raise ValidationError('Some team entries are missing. Reload this round before saving; no scores were changed.')
        if self.overrides:
            for team in self.teams:
                name=f'normalized_{team.pk}'
                if not data.get(f'override_{team.pk}'):
                    self._errors.pop(name,None);data[name]=None
                elif data.get(f'raw_{team.pk}') is None or data.get(name) is None:
                    self.add_error(name,'Enter raw and normalized scores to use an override.')
        return data


def save_round_scores(form,user):
    """Called inside the competition lock and the caller's transaction."""
    from .control_management import pause_workbook
    from .services import audit
    from .scoring import normalize_round
    changed=[]
    for team in form.teams:
        raw=form.cleaned_data[f'raw_{team.pk}'];old=form.scores.get(team.pk)
        remaining_name=f'remaining_{team.pk}'
        remaining=form.cleaned_data[remaining_name]
        elapsed=(None if remaining is None else RUN_ALLOWANCE_SECONDS-remaining) if form.add_prefix(remaining_name) in form.data else old.elapsed_seconds if old else None
        override=form.cleaned_data.get(f'override_{team.pk}',False) if form.overrides else bool(old and old.normalized_override and old.raw==raw and not form.field_scoring)
        normalized=form.cleaned_data.get(f'normalized_{team.pk}') if form.overrides else old.normalized if override else None
        if (old.raw if old else None)==raw and bool(old and old.normalized_override)==override and (not override or old and old.normalized==normalized) and (old.elapsed_seconds if old else None)==elapsed: continue
        Score.objects.update_or_create(round=form.round,team=team,defaults={'raw':raw,'normalized':normalized if override else None,'normalized_override':override,'elapsed_seconds':elapsed})
        changed.append(str(team.pk))
    normalize_round(form.round)
    if changed:
        pause_workbook(form.round.competition)
        audit(user,'scores.updated',object_id=form.round.pk,detail={'teams':changed})


def round_scores_response(form):
    scores=list(Score.objects.filter(round=form.round))
    return {'raw':{str(score.team_id):format(score.raw.normalize(),'f') if score.raw is not None else None for score in scores},
        'normalized':{str(score.team_id):str(score.normalized) if score.normalized is not None else None for score in scores},
        'overrides':{str(score.team_id):score.normalized_override for score in scores},
        'elapsed_seconds':{str(score.team_id):score.elapsed_seconds for score in scores},
        'revision':round_scores_revision(form.round,form.teams,scores)}


def safe_path(value):
    if not isinstance(value,str) or not value or len(value)>1000 or '\\' in value or any(ord(ch)<32 for ch in value):
        raise ValidationError('The export contains an invalid filename.')
    path=PurePosixPath(value)
    if path.is_absolute() or any(part in ['.','..',''] for part in value.split('/')) or ':' in value or '%' in value:
        raise ValidationError('Keep the export inside one folder, without parent paths or encoded filenames.')
    return str(path)


class ExportHTML(HTMLParser):
    def __init__(self):
        super().__init__();self.viewer=None;self.versions=[];self.references=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='webots-view':
            if self.viewer is not None: raise ValidationError('Choose an HTML page containing exactly one Webots recording.')
            self.viewer=attrs
        for key in ['src','href']:
            if attrs.get(key): self.references.append(attrs[key])
        if tag=='script' and attrs.get('src'):
            match=re.search(r'/wwi/(R\d{4}[ab](?:-rev\d+)?)/WebotsView\.js$',attrs['src'])
            if match and urlsplit(attrs['src']).scheme=='https' and urlsplit(attrs['src']).hostname in ['cyberbotics.com','www.cyberbotics.com']: self.versions.append(match.group(1))


def local_reference(entry,reference,files):
    parsed=urlsplit(reference or '')
    if parsed.scheme or parsed.netloc or not parsed.path: raise ValidationError('The scene, animation and preview must be local files in this export.')
    result=posixpath.normpath(posixpath.join(posixpath.dirname(entry),unquote(parsed.path)))
    if result.startswith('../') or result not in files: raise ValidationError(f'Missing export file: {result}')
    return safe_path(result)


def validate_reference(entry,reference,files):
    parsed=urlsplit(reference)
    hostname=(parsed.hostname or '').lower()
    try: loopback=ipaddress.ip_address(hostname).is_loopback
    except ValueError: loopback=False
    if parsed.scheme=='file' or re.match(r'^[a-zA-Z]:[\\/]',reference) or hostname=='localhost' or hostname.endswith('.localhost') or loopback:
        raise ValidationError(f'Computer-local reference: {reference}. Include the file in the recording and use its relative path.')
    if not parsed.scheme and not reference.startswith(('#','//')): local_reference(entry,reference,files)


def recording_key(recording, path):
    """Provider IDs are private storage keys; browser paths remain unchanged.

    Existing local/S3 manifests without storage_key remain readable.
    """
    item = recording.manifest.get(path)
    if not isinstance(item, dict): raise OSError('Unknown recording asset.')
    return item.get('storage_key') or f'recordings/{recording.pk}/{path}'


def recording_result_data(recording):
    if not recording: return {}
    path=posixpath.join(posixpath.dirname(recording.entry_path),'match-result.json')
    if path not in recording.manifest: return {}
    try:
        with default_storage.open(recording_key(recording,path),'rb') as stream:
            content=stream.read(1024*1024+1)
        if len(content)>1024*1024: return {}
        data=json.loads(content.decode('utf-8-sig'),parse_float=Decimal)
        return data if isinstance(data,dict) else {}
    except (OSError,UnicodeError,ValueError,InvalidOperation): return {}


def result_number(value):
    if isinstance(value,bool) or not isinstance(value,(int,float,Decimal,str)): return None
    try: value=Decimal(str(value))
    except InvalidOperation: return None
    return value if value.is_finite() and value.copy_abs()<=Decimal('1e18') else None


def match_result(recording):
    """Format this export's final results without inventing missing values."""
    result={'available':False,'scores':{},'times':{},'event_history_available':False}
    data=recording_result_data(recording)
    if not data: return result
    for name in ['final_score','field_score','exit_bonus','map_bonus']:
        value=result_number(data.get(name))
        result['scores'][name]=str(value.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if value is not None else None
    for name in ['elapsed_seconds','max_seconds','remaining_seconds']:
        value=result_number(data.get(name))
        seconds=int(value) if value is not None and value>=0 else None
        result['times'][name]=f'{seconds//60:02d}:{seconds%60:02d}' if seconds is not None else None
    events=data.get('events')
    # Timeline events are displayed by the original export, never by its static last_event.
    result['event_history_available']=isinstance(events,list) and all(
        isinstance(event,dict) and isinstance(event.get('timestamp'),str) and isinstance(event.get('text'),str)
        and bool(re.fullmatch(r'\d+:[0-5]\d',event['timestamp'])) and bool(event['text'].strip())
        and (playback_time:=result_number(event.get('playback_time_ms'))) is not None and playback_time>=0
        for event in events)
    result['available']=result['scores']['final_score'] is not None
    return result


def validate_export(files,entry='',preview=''):
    candidates=[]
    for name,path in files.items():
        if name.lower().endswith(('.html','.htm')):
            parser=ExportHTML()
            try:
                with path.open('rb') as source: parser.feed(bounded_read(source).decode('utf-8-sig'))
            except (UnicodeError,ValueError): raise ValidationError('The replay HTML must use UTF-8 text.')
            if parser.viewer: candidates.append((name,parser))
    if entry:
        candidates=[candidate for candidate in candidates if candidate[0]==entry]
    else:
        named=[candidate for candidate in candidates if PurePosixPath(candidate[0]).name.casefold()=='replay.html']
        if named: candidates=named
    if len(candidates)!=1: raise ValidationError('Choose the replay HTML page. Upload one complete recording per team/run.')
    entry,parser=candidates[0];attrs=parser.viewer
    for attribute,label in [('data-scene','scene'),('data-animation','animation')]:
        if not attrs.get(attribute): raise ValidationError(f'The replay HTML is missing its {label} reference ({attribute}).')
    scene=local_reference(entry,attrs.get('data-scene'),files)
    animation=local_reference(entry,attrs.get('data-animation'),files)
    preview=safe_path(preview) if preview else local_reference(entry,attrs.get('data-thumbnail'),files)
    if preview not in files or not preview.lower().endswith(('.jpg','.jpeg','.png','.webp')): raise ValidationError('Include and choose the recording preview image.')
    with files[preview].open('rb') as image: signature=image.read(16)
    if not (signature.startswith(b'\xff\xd8\xff') or signature.startswith(b'\x89PNG\r\n\x1a\n') or signature.startswith(b'RIFF') and signature[8:12]==b'WEBP'):
        raise ValidationError('The preview is not a supported image.')
    if not scene.lower().endswith(('.x3d','.w3d')) or not animation.lower().endswith('.json'): raise ValidationError('Use a matching exported Webots scene and JSON animation.')
    try:
        with files[animation].open('rb') as stream: data=json.loads(bounded_read(stream))
    except (ValueError,UnicodeError): raise ValidationError('The animation JSON is not valid.')
    frames=data.get('frames') if isinstance(data,dict) else None
    if not isinstance(frames,list) or len(frames)<2: raise ValidationError('The animation must contain at least two recorded frames.')
    last=-1
    for frame in frames:
        value=frame.get('time') if isinstance(frame,dict) else None
        if not isinstance(value,(float,int)) or isinstance(value,bool) or not math.isfinite(value) or value<last or value<0:
            raise ValidationError('Animation frames must have ordered, finite times.')
        last=value
    if last<=0: raise ValidationError('The recording must have a positive duration.')
    if not any(frame.get('updates') or frame.get('poses') for frame in frames): raise ValidationError('No recorded movement frames were found in this animation.')
    if len(set(parser.versions))!=1: raise ValidationError('Keep the versioned WebotsView.js script from the original Webots export.')
    # Check local HTML dependencies and scene texture/mesh references before publishing.
    for reference in parser.references:
        validate_reference(entry,reference,files)
    try:
        with files[scene].open('rb') as stream: scene_root=SafeXML.fromstring(bounded_read(stream))
    except (SafeXML.ParseError,DefusedXmlException,UnicodeError): raise ValidationError('The exported scene is not valid XML.')
    ids={node.get('id') for node in scene_root.iter() if node.get('id')}
    animated_ids={f"n{update['id']}" for frame in frames for update in frame.get('updates',[]) if isinstance(update,dict) and 'id' in update}
    if not animated_ids or not animated_ids.issubset(ids): raise ValidationError('The scene and animation do not match. Upload the files from one export together.')
    for node in scene_root.iter():
        for key,values in node.attrib.items():
            if key.lower().endswith('url') and key.lower()!='docurl':
                for reference in re.findall(r'"([^"]+)"',values) or [values]:
                    if reference: validate_reference(scene,reference,files)
    scene_version=next((node.get('content') for node in scene_root.iter('meta') if node.get('name')=='version'),None)
    if scene_version and scene_version!=parser.versions[0]: raise ValidationError('The scene and Webots player versions differ. Keep the original export files together.')
    validate_recording_files(files, entry, animation, parser)
    return dict(entry_path=entry,preview_path=preview,scene_path=scene,animation_path=animation,
        player_version=parser.versions[0],frame_count=len(frames),duration_ms=round(last))


REPLAY_VISUAL_SUFFIXES = {'.html','.htm','.css','.x3d','.w3d','.jpg','.jpeg','.png','.webp','.gif','.svg',
              '.hdr','.exr','.stl','.obj','.mtl','.dae','.bin','.glb','.gltf','.woff','.woff2','.ttf','.ico'}


def public_recording_path(recording,path):
    """Apply privacy filtering to legacy manifests too, without changing stored files."""
    if any(part.startswith('.') for part in PurePosixPath(path).parts): return False
    if path in [recording.entry_path,recording.scene_path,recording.animation_path,recording.preview_path,
                posixpath.join(posixpath.dirname(recording.entry_path),'match-result.json')]: return True
    suffix=PurePosixPath(path).suffix.lower()
    return suffix in REPLAY_VISUAL_SUFFIXES or (suffix in ('.js','.mjs') and recording.manifest.get(path,{}).get('public_asset') is True)


def validate_recording_files(files, entry, animation, parser):
    """Only visual replay assets belong in a publishable recording package."""
    result_path = posixpath.join(posixpath.dirname(entry), 'match-result.json')
    script_paths = set()
    for reference in parser.references:
        parsed = urlsplit(reference)
        if not parsed.scheme and not parsed.netloc and parsed.path:
            script_paths.add(posixpath.normpath(posixpath.join(posixpath.dirname(entry), unquote(parsed.path))))
    # Follow local module imports; allow exported helper scripts without accepting stray controller code.
    pending = [path for path in script_paths if path.endswith(('.js', '.mjs'))]
    while pending:
        path = pending.pop()
        if path not in files: continue
        with files[path].open('rb') as stream: source = bounded_read(stream).decode('utf-8-sig')
        for reference in re.findall(r"(?:from\s*|import\s*\(?\s*)['\"]([^'\"]+)['\"]", source):
            if urlsplit(reference).scheme or not reference.startswith('.'): continue
            child = local_reference(path, reference, files)
            if child not in script_paths:
                script_paths.add(child); pending.append(child)
    for path in files:
        suffix = PurePosixPath(path).suffix.lower()
        hidden = any(part.startswith('.') for part in PurePosixPath(path).parts)
        if hidden or not (suffix in REPLAY_VISUAL_SUFFIXES or path in (animation, result_path) or
                          suffix in ('.js','.mjs') and path in script_paths):
            raise ValidationError(f'Unexpected private or unrelated file in recording: {path}. Upload only the replay export; team code, submission JSON and documents belong in private submissions.')


class ResultForm(forms.Form):
    revision=forms.CharField(required=False,widget=forms.HiddenInput)
    raw=forms.DecimalField(max_digits=14,decimal_places=4,required=False,label='Raw score')
    normalized=forms.DecimalField(max_digits=14,decimal_places=4,required=False,label='Normalized score')
    normalized_override=forms.BooleanField(required=False,label='Override the calculated score')
    remaining_time=RemainingTimeField()
    files=MultipleFileField(required=False,widget=MultipleFileInput,label='Webots export files')
    video=forms.FileField(required=False,label='Video recording',widget=forms.FileInput(attrs={'accept':'.mp4,.webm,.ogv','data-recording-video':'','aria-label':'Choose video recording'}),help_text='MP4, WebM or Ogg video. When present, this plays instead of the Webots export.')
    remove_video=forms.BooleanField(required=False,label='Remove video and use the Webots export')
    paths=forms.JSONField(required=False,widget=forms.HiddenInput)
    entry=forms.CharField(required=False,max_length=1000,label='Replay HTML file')
    preview=forms.CharField(required=False,max_length=1000,label='Preview image file')
    published=forms.BooleanField(required=False,label='Publish this recording in public Results')
    skip_score_import=forms.BooleanField(required=False,widget=forms.HiddenInput)
    skip_time_import=forms.BooleanField(required=False,widget=forms.HiddenInput)
    def __init__(self,*args,round_,team,recording_only=False,**kwargs):
        self.round=round_;self.team=team
        self.recording_only=recording_only
        self.score=Score.objects.filter(round=round_,team=team).first()
        self.recording=RunRecording.objects.filter(round=round_,team=team,current=True).first()
        kwargs.setdefault('initial',{}).update(raw=self.score.raw if self.score else None,normalized=self.score.normalized if self.score else None,
            published=self.recording.published if self.recording else False,normalized_override=self.score.normalized_override if self.score else False,revision=result_revision(round_,team))
        super().__init__(*args,**kwargs)
        self.initial['remaining_time']=self.score.remaining_seconds if self.score else None
        self.other_raw=list(Score.objects.filter(round=round_,team__active=True).exclude(team=team).exclude(raw=None).values_list('raw',flat=True))
        self.field_scoring=bool(round_.challenge_id and round_.challenge.calculation=='trimmed_mean')
        self.zero_policy=round_.zero_score_policy
        self.fields['normalized'].help_text='Raw score ÷ the highest raw score in this round. Rankings use the exact ratio, before display rounding.'
        if self.field_scoring:
            self.fields['raw'].min_value=0
            self.fields['normalized'].disabled=True
            self.fields['normalized_override'].disabled=True
            self.initial['normalized_override']=False
            self.fields['normalized'].help_text+=' All-zero rounds require the organizer decision in Round settings.'
        else: self.fields['normalized'].help_text+=' Enable override to enter a different value.'
        if recording_only:
            for name in ['raw','normalized','normalized_override','remaining_time']: self.fields[name].disabled=True
    def clean(self):
        d=super().clean()
        if self.field_scoring and d.get('raw') is not None and d['raw']<0: self.add_error('raw','Enter a non-negative field score.')
        if d.get('normalized_override') and (d.get('raw') is None or d.get('normalized') is None):
            self.add_error('normalized','Enter raw and normalized scores to use an override.')
        video=d.get('video')
        if video:
            header=video.read(32);video.seek(0)
            suffix=Path(video.name).suffix.lower()
            valid=(suffix=='.mp4' and header[4:8]==b'ftyp' or suffix=='.webm' and header.startswith(b'\x1aE\xdf\xa3') or suffix=='.ogv' and header.startswith(b'OggS'))
            if not valid: self.add_error('video','Choose an MP4, WebM or Ogg video file with matching file contents.')
            if len(video.name)>180: self.add_error('video','Use a filename of at most 180 characters.')
        if video and d.get('remove_video'): self.add_error('remove_video','Choose either a replacement video or removal, not both.')
        if d.get('remove_video') and not d.get('files') and self.recording and not self.recording.entry_path:
            self.add_error('remove_video','Upload a Webots export first, or remove the entire recording below.')
        if d.get('published') and not self.recording and not d.get('files') and not video: self.add_error('files','Upload a video or complete Webots recording before publishing.')
        if d.get('published') and not self.round.release_ready:
            self.add_error('published','Mark this round as completed before publishing recordings.')
        return d


def result_revision(round_,team):
    values=list(Score.objects.filter(round=round_,team=team).values('raw','normalized','normalized_override','elapsed_seconds'))
    values+=list(RunRecording.objects.filter(round=round_,team=team,current=True).values('id','published','video_key'))
    return hashlib.sha256(json.dumps(values,default=str,sort_keys=True).encode()).hexdigest()


def save_result(form,user):
    from .control_management import pause_workbook
    from .services import audit
    files=form.cleaned_data.get('files') or []
    video=form.cleaned_data.get('video')
    stored=[]
    try:
        with tempfile.TemporaryDirectory(prefix='asr-replay-') as directory:
            paths={};seen=set();extracted=0
            def add(name,stream):
                nonlocal extracted
                if len(paths) >= settings.UPLOAD_MAX_FILES: raise ValidationError('The recording contains too many files.')
                name=safe_path(name)
                if name.casefold() in seen: raise ValidationError('The export contains duplicate filenames.')
                seen.add(name.casefold())
                target=Path(directory)/name;target.parent.mkdir(parents=True,exist_ok=True)
                import shutil
                with target.open('wb') as output:
                    file_bytes=0
                    for chunk in iter(lambda:stream.read(65536),b''):
                        file_bytes+=len(chunk);extracted+=len(chunk)
                        if file_bytes>settings.UPLOAD_MAX_FILE_BYTES or extracted>settings.RECORDING_MAX_EXTRACTED_BYTES or shutil.disk_usage(directory).free < settings.UPLOAD_MIN_FREE_BYTES:
                            raise ValidationError('The recording exceeds the configured extraction/storage budget.')
                        output.write(chunk)
                paths[name]=target
            if len(files)==1 and zipfile.is_zipfile(files[0]):
                with zipfile.ZipFile(files[0]) as archive:
                    items=[i for i in archive.infolist() if not i.is_dir() and not i.filename.startswith('__MACOSX/')]
                    import shutil
                    if len(items)>settings.UPLOAD_MAX_FILES or sum(i.file_size for i in items)>min(settings.RECORDING_MAX_EXTRACTED_BYTES,max(0,shutil.disk_usage(directory).free-settings.UPLOAD_MIN_FREE_BYTES)):
                        raise ValidationError('This export exceeds the available safe extraction space. Upload a smaller recording or free server space.')
                    for item in items:
                        if stat.S_ISLNK(item.external_attr>>16) or item.flag_bits&1: raise ValidationError('Encrypted files and symbolic links are not supported.')
                        with archive.open(item) as stream: add(item.filename,stream)
            elif files:
                names=form.cleaned_data.get('paths')
                if names is None: names=[file.name for file in files]
                if not isinstance(names,list) or len(names)!=len(files): raise ValidationError('Select the complete export folder again.')
                for file,name in zip(files,names): add(name,file)
            details=validate_export(paths,form.cleaned_data.get('entry',''),form.cleaned_data.get('preview','')) if files else None
            with transaction.atomic():
                from .models import Competition
                Competition.objects.select_for_update(no_key=True).get(pk=form.round.competition_id)
                if form.cleaned_data.get('revision')!=result_revision(form.round,form.team): raise ValidationError('These results changed in another window. Reopen this team/run before saving.')
                # Publication is rechecked under the same lock used by calendar edits.
                form.round.refresh_from_db()
                if form.cleaned_data.get('published') and not form.round.release_ready:
                    raise ValidationError('This round must be completed and active before publishing recordings.')
                old=RunRecording.objects.filter(round=form.round,team=form.team,current=True).first()
                video_values={name:getattr(old,name) if old else '' for name in ['video_key','video_name','video_type']}
                if video:
                    key=f'recording-videos/{uuid.uuid4()}/{video.name}'
                    actual=default_storage.save(key,video);stored.append(actual)
                    video_values={'video_key':actual,'video_name':video.name,'video_type':{'.mp4':'video/mp4','.webm':'video/webm','.ogv':'video/ogg'}[Path(video.name).suffix.lower()]}
                elif form.cleaned_data.get('remove_video'):
                    video_values={name:'' for name in video_values}
                if details:
                    recording=RunRecording(round=form.round,team=form.team,uploaded_by=user,published=form.cleaned_data['published'],**details,**video_values)
                    manifest={}
                    for name,path in paths.items():
                        key=f'recordings/{recording.pk}/{name}'
                        with path.open('rb') as stream:
                            actual=default_storage.save(key,File(stream,name=PurePosixPath(name).name))
                        stored.append(actual)
                        digest=hashlib.sha256()
                        with path.open('rb') as stream:
                            for chunk in iter(lambda:stream.read(1024*1024),b''): digest.update(chunk)
                        manifest[name]={'size':path.stat().st_size,'sha256':digest.hexdigest(),'storage_key':actual,'public_asset':True}
                    if old: old.current=False;old.published=False;old.save(update_fields=['current','published'])
                    recording.manifest=manifest;recording.full_clean();recording.save()
                elif old:
                    recording=old
                    old.published=form.cleaned_data['published']
                    for name,value in video_values.items(): setattr(old,name,value)
                    old.save(update_fields=['published',*video_values])
                elif video:
                    recording=RunRecording.objects.create(round=form.round,team=form.team,uploaded_by=user,published=form.cleaned_data['published'],
                        entry_path='',preview_path='',scene_path='',animation_path='',frame_count=0,duration_ms=0,**video_values)
                else: recording=None
                timing_changed=not form.recording_only and form.add_prefix('remaining_time') in form.data and 'remaining_time' in form.changed_data
                changed=not form.recording_only and (timing_changed or any(key in form.changed_data for key in ['raw','normalized_override']) or (form.cleaned_data['normalized_override'] and 'normalized' in form.changed_data))
                remaining=form.cleaned_data['remaining_time']
                elapsed=(None if remaining is None else RUN_ALLOWANCE_SECONDS-remaining) if not form.recording_only and form.add_prefix('remaining_time') in form.data else form.score.elapsed_seconds if form.score else None
                raw=form.cleaned_data['raw']
                override=form.score.normalized_override if form.recording_only and form.score else form.cleaned_data['normalized_override']
                normalized=form.score.normalized if form.recording_only and form.score else form.cleaned_data['normalized']
                imported=[]
                if files or video:
                    metadata=recording_result_data(recording)
                    final=result_number(metadata.get('final_score'))
                    if raw is None and not form.cleaned_data['skip_score_import'] and final is not None and 0<=final<Decimal('9999999999.99995'):
                        raw=final.quantize(Decimal('.0001'),rounding=ROUND_HALF_UP);imported.append('score')
                    recorded_elapsed=result_number(metadata.get('elapsed_seconds'))
                    if recorded_elapsed is None:
                        maximum=result_number(metadata.get('max_seconds'));recorded_remaining=result_number(metadata.get('remaining_seconds'))
                        if maximum is not None and recorded_remaining is not None and 0<=recorded_remaining<=maximum:
                            recorded_elapsed=maximum-recorded_remaining
                    if elapsed is None and not form.cleaned_data['skip_time_import'] and recorded_elapsed is not None and 0<=recorded_elapsed<=RUN_ALLOWANCE_SECONDS:
                        elapsed=int(recorded_elapsed);imported.append('time')
                if changed or imported:
                    Score.objects.update_or_create(round=form.round,team=form.team,defaults={
                        'raw':raw,'normalized_override':override,
                        'elapsed_seconds':elapsed,
                        'normalized':normalized if override else None})
                    from .scoring import normalize_round
                    normalize_round(form.round)
                    pause_workbook(form.round.competition)
                audit(user,'result.updated',team=form.team,object_id=form.round.pk,detail={'recording_uploaded':bool(details),'video_uploaded':bool(video),'video_removed':bool(form.cleaned_data.get('remove_video')),'published':form.cleaned_data['published'],'imported':imported})
    except Exception:
        for key in stored: default_storage.delete(key)
        raise
