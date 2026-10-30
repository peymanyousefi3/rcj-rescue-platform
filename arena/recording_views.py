"""Isolated, lazy Webots playback. Uploaded HTML never shares the dashboard origin."""
from copy import copy
from decimal import Decimal,ROUND_HALF_UP
from types import SimpleNamespace
import mimetypes
import re
import zipfile
from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.http import FileResponse,Http404,HttpResponse,JsonResponse
from django.shortcuts import get_object_or_404,redirect,render
from django.templatetags.static import static
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_GET,require_POST,require_http_methods
from django.utils.crypto import salted_hmac,constant_time_compare
from .access import owns_team
from .models import Challenge,Round,RunRecording,Score,Team
from .recordings import ResultForm,RoundScoresForm,save_round_scores,round_scores_response,save_result,safe_path,recording_key,public_recording_path
from .views import staff_required,current_competition


def allowed(request,recording):
    if recording.public_open: return True
    if not request.user.is_authenticated or not request.user.is_active: return False
    if request.user.is_staff: return True
    return bool(owns_team(request.user,recording.team) and recording.current
        and not recording.round.archived_at and not (recording.round.challenge_id and recording.round.challenge.archived_at))


def visible_recordings(request,competition):
    items=RunRecording.objects.filter(round__competition=competition,current=True).select_related('round__challenge','team')
    return [item for item in items if allowed(request,item)]


def replay_session(request):
    return salted_hmac('webots-session',request.session.session_key or '',algorithm='sha256').hexdigest()


def score_rounds(competition,challenge=None):
    rounds=Round.objects.filter(competition=competition,archived_at=None,challenge__archived_at=None).select_related('challenge')
    challenge=challenge or competition.challenge_set.filter(archived_at=None).first()
    return list(rounds.filter(challenge=challenge))

def score_challenge(competition,value):
    if value and not str(value).isdigit(): raise Http404()
    return get_object_or_404(Challenge,pk=value,competition=competition,archived_at=None) if value else competition.challenge_set.filter(archived_at=None).first()


def matrix_forms(competition,data):
    rounds=score_rounds(competition,score_challenge(competition,data.get('score_challenge')))
    forms=[RoundScoresForm(data,round_=round_,matrix=True,prefix=f'r{round_.pk}') for round_ in rounds]
    errors={};stale=data.get('round_ids')!=','.join(str(round_.pk) for round_ in rounds)
    if stale: errors['__all__']=[{'message':'The round list changed. Reload before saving; your entries remain here for comparison.'}]
    for form in forms:
        form.is_valid()
        if data.get(form.add_prefix('revision'))!=form.initial['revision']:
            stale=True;form.add_error(None,f'{form.round}: scores, teams or settings changed. Reload before saving; your entries remain here for comparison.')
        errors.update({form.add_prefix(name):messages for name,messages in form.errors.get_json_data().items()})
    return forms,errors,stale


def score_preview(competition,forms):
    """Read-only draft calculation. Incomplete rounds never establish final ratios."""
    from .scoring import field_round_state,field_standings,rank_standings
    from .policy import challenge_total,best_rounds
    primary=forms[0].round.challenge if forms and forms[0].round.challenge_id else competition.challenge_set.filter(archived_at=None).first()
    selected=[form for form in forms if form.round.challenge_id==(primary.pk if primary else None)]
    teams=forms[0].teams if forms else []
    percentage=bool(primary and primary.calculation=='trimmed_mean')
    complete=[];scores={};excluded=[];issues=[]
    for form in selected:
        highest=max((form.cleaned_data[f'raw_{team.pk}'] for team in teams if form.cleaned_data[f'raw_{team.pk}'] is not None),default=Decimal(0))
        for team in teams:
            raw=form.cleaned_data[f'raw_{team.pk}'];manual=form.cleaned_data.get(f'override_{team.pk}',False)
            normalized=form.cleaned_data.get(f'normalized_{team.pk}') if manual else (raw/highest if highest else Decimal(0)).quantize(Decimal('.0001'),rounding=ROUND_HALF_UP) if raw is not None else None
            scores[(team.pk,form.round.pk)]=SimpleNamespace(raw=raw,normalized=normalized)
        state=field_round_state(form.round,scores,[team.pk for team in teams]) if percentage else None
        if state and state['excluded']: excluded.append(str(form.round.pk))
        if state and state['issue'] and 'Awaiting' not in state['issue']: issues.append(f'{form.round}: {state["issue"]}')
        if teams and all(form.cleaned_data[f'raw_{team.pk}'] is not None for team in teams) and (not state or not state['issue']): complete.append(form.round)
    expected=max(len(selected),primary.expected_rounds if primary else len(selected))
    provisional=len(complete)<expected
    if percentage:
        challenge=copy(primary);challenge.expected_rounds=len(complete)
        rows=field_standings(complete,teams,scores,challenge)
    else:
        rows=[]
        for team in teams:
            values=[getattr(scores[(team.pk,r.pk)],primary.score_source if primary else 'normalized') for r in complete]
            total,dropped=challenge_total(values,primary.calculation,primary.top_count,len(complete)) if primary else best_rounds(values,competition.counted_rounds)
            rows.append({'team':team,'total':total,'rank':None,'cells':[SimpleNamespace(discarded=i+1 in dropped) for i in range(len(complete))]})
    rank_standings(rows,released=bool(primary and primary.rankings_released))
    usable=len(complete)-len(excluded)
    message=f'{len(complete)} of {expected} rounds complete. '
    if issues: message+=' '.join(issues)+' '
    if percentage and usable<=primary.discard_count:
        message+=f'Complete at least {primary.discard_count+1} usable rounds to preview the percentage and rank.'
    else: message+=('Provisional preview' if provisional else 'Final calculation')+' · '+('each team’s lowest normalized scores are discarded.' if percentage else 'configured challenge scoring.')
    if not primary or not primary.rankings_released: message+=' Rankings are not released. Scores remain visible.'
    return {'percentage':percentage,'provisional':provisional,'rankings_released':bool(primary and primary.rankings_released),'message':message,'rows':{
        str(row['team'].pk):{'total':format(row['total'],'.2f') if row['total'] is not None else None,'rank':row['rank'],'tie':row['tie'],
            'discarded':[str(round_.pk) for round_,cell in zip(complete,row['cells']) if cell.discarded],'excluded':excluded}
        for row in rows}}


@require_POST
@staff_required
def preview_scores(request):
    competition=current_competition()
    forms,errors,stale=matrix_forms(competition,request.POST)
    if errors: return JsonResponse({'errors':errors},status=409 if stale else 400)
    return JsonResponse(score_preview(competition,forms))


def recording_update(round_,team):
    recording=RunRecording.objects.filter(round=round_,team=team,current=True).first()
    return {'round':str(round_.pk),'team':str(team.pk),'present':bool(recording),'player':f'/recordings/{recording.pk}/player/' if recording else None,
        'scores':round_scores_response(RoundScoresForm(round_=round_))}


def results_context(competition,selected=None):
    selected=score_challenge(competition,selected)
    matrix_id='score-matrix' if not selected or selected.primary else f'score-matrix-{selected.pk}'
    preview_id='score-preview-data' if not selected or selected.primary else f'score-preview-data-{selected.pk}'
    scores={(s.round_id,s.team_id):s for s in Score.objects.filter(round__competition=competition)}
    recordings={(r.round_id,r.team_id):r for r in RunRecording.objects.filter(round__competition=competition,current=True).select_related('round','team')}
    teams=list(Team.objects.participants(selected).filter(competition=competition,active=True).order_by('name'))
    entries=[{'round':round_,'teams':[{'team':team,'score':scores.get((round_.pk,team.pk)),
        'recording':recordings.get((round_.pk,team.pk))} for team in teams]}
        for round_ in score_rounds(competition,selected)]
    from .fields import attach_maximum_scores
    attach_maximum_scores([item['round'] for item in entries])
    from .scoring import field_round_state,display_value
    for item in entries:
        form=RoundScoresForm(round_=item['round'],matrix=True,matrix_id=matrix_id,prefix=f"r{item['round'].pk}",teams=teams,
            scores=[score for (round_id,_),score in scores.items() if round_id==item['round'].pk])
        item['score_form']=form
        for row in item['teams']:
            row['raw_field']=form[f"raw_{row['team'].pk}"];row['round']=item['round'];row['field_scoring']=form.field_scoring
            row['remaining_field']=form[f"remaining_{row['team'].pk}"]
            if form.overrides:
                row['normalized_field']=form[f"normalized_{row['team'].pk}"];row['override_field']=form[f"override_{row['team'].pk}"]
        if item['round'].challenge_id and item['round'].challenge.calculation=='trimmed_mean':
            state=field_round_state(item['round'],{(team_id,round_id):score for (round_id,team_id),score in scores.items()},[team.pk for team in teams])
            item['scoring_issue']=state['issue'];item['scoring_excluded']=state['excluded']
            for row in item['teams']:
                if row['score']: row['score'].normalized=display_value(state['values'][row['team'].pk])
    preview_forms=[]
    for item in entries:
        original=item['score_form']
        data={original.add_prefix(name):'' if value is None else value for name,value in original.initial.items() if value is not False}
        form=RoundScoresForm(data,round_=item['round'],matrix=True,prefix=original.prefix,teams=teams,scores=original.scores.values())
        form.is_valid();preview_forms.append(form)
    preview=score_preview(competition,preview_forms)
    return {'matrix_id':matrix_id,'preview_id':preview_id,'result_entries':entries,'score_rows':[{'team':team,'cells':[item['teams'][i] for item in entries]} for i,team in enumerate(teams)],
        'score_round_ids':','.join(str(item['round'].pk) for item in entries),'score_preview':preview,'score_challenge':selected,
        'score_challenges':competition.challenge_set.filter(archived_at=None),
        'ranking_challenges':competition.challenge_set.filter(archived_at=None).filter(pk=selected.pk) if selected else competition.challenge_set.filter(archived_at=None).exclude(category='superteam')}


@never_cache
@require_POST
@staff_required
@transaction.atomic
def ranking_release(request,challenge_id):
    from .models import Competition
    from .services import audit
    from .views import standings
    competition=current_competition()
    Competition.objects.select_for_update(no_key=True).get(pk=competition.pk)
    challenge=get_object_or_404(Challenge.objects.select_for_update(),pk=challenge_id,competition=competition,archived_at=None)
    value=request.POST.get('released')
    previous=request.POST.get('previous_state')
    if value not in ['0','1'] or previous not in ['0','1']:
        return HttpResponse('Invalid ranking release request.',status=400)
    if challenge.rankings_released!=(previous=='1'):
        messages.error(request,'Ranking release changed in another window. Review the current setting before saving again.')
    elif value=='1' and (not (rows:=standings(competition,challenge)[1]) or any(row['total'] is None for row in rows)):
        messages.error(request,'Complete all planned round scores and resolve scoring issues before releasing rankings. Scores remain visible.')
    else:
        released=value=='1'
        if challenge.rankings_released!=released:
            challenge.rankings_released=released
            challenge.save(update_fields=['rankings_released'])
            audit(request.user,'rankings.released' if released else 'rankings.withdrawn',object_id=challenge.pk)
        messages.success(request,'Rankings released. Scores remain visible.' if released else 'Rankings hidden. Scores remain visible.')
    target='/control/'
    target+='?score_challenge='+str(challenge.pk)
    return redirect(target+'#results-recordings')


@require_POST
@staff_required
def round_scores(request,round_id):
    from .models import Competition
    competition=current_competition()
    with transaction.atomic():
        Competition.objects.select_for_update(no_key=True).get(pk=competition.pk)
        round_=get_object_or_404(Round.objects.select_related('challenge'),pk=round_id,competition=competition,archived_at=None)
        if round_.challenge_id and round_.challenge.archived_at: raise Http404()
        form=RoundScoresForm(request.POST,round_=round_)
        valid=form.is_valid()
        stale=request.POST.get('revision')!=form.initial['revision']
        if stale: form.add_error(None,'Scores or teams changed in another window. Reload this page before saving; your entries have been kept here for comparison.')
        if valid and not stale:
            try:
                with transaction.atomic():
                    save_round_scores(form,request.user)
            except ValidationError as exc: form.add_error(None,exc)
            else:
                if request.headers.get('X-ASR-Scores')=='1': return JsonResponse(round_scores_response(form))
                messages.success(request,f'{round_} scores saved.')
                return redirect('/control/#results-recordings')
    if request.headers.get('X-ASR-Scores')=='1': return JsonResponse({'errors':form.errors.get_json_data()},status=409 if stale else 400)
    messages.error(request,' '.join(error for errors in form.errors.values() for error in errors))
    return redirect('/control/#results-recordings')


@require_http_methods(['GET','POST'])
@staff_required
def score_matrix(request):
    from .models import Competition
    if request.method=='GET':
        from django.middleware.csrf import get_token
        return JsonResponse({'csrf':get_token(request)})
    competition=current_competition()
    with transaction.atomic():
        competition=Competition.objects.select_for_update(no_key=True).get(pk=competition.pk)
        forms,errors,stale=matrix_forms(competition,request.POST)
        if not errors:
            try:
                with transaction.atomic():
                    for form in forms: save_round_scores(form,request.user)
            except ValidationError as exc:
                errors['__all__']=[{'message':message} for message in exc.messages]
            else:
                if request.headers.get('X-ASR-Scores')=='1':
                    return JsonResponse({'rounds':{str(form.round.pk):round_scores_response(form) for form in forms}})
                messages.success(request,'All round scores saved.')
                return redirect('/control/#results-recordings')
    if request.headers.get('X-ASR-Scores')=='1': return JsonResponse({'errors':errors},status=409 if stale else 400)
    messages.error(request,' '.join(item['message'] for entries in errors.values() for item in entries))
    return redirect('/control/#results-recordings')


@never_cache
@staff_required
def result_editor(request,round_id,team_id):
    competition=current_competition()
    round_=get_object_or_404(Round,pk=round_id,competition=competition,archived_at=None)
    team=get_object_or_404(Team.objects.participants(round_.challenge),pk=team_id,competition=competition)
    form=ResultForm(request.POST if request.method=='POST' else None,request.FILES if request.method=='POST' else None,round_=round_,team=team,recording_only=request.GET.get('recording')=='1',auto_id='result_%s')
    if request.method=='POST' and form.is_valid():
        try: save_result(form,request.user)
        except (ValidationError,OSError,ValueError,zipfile.BadZipFile,NotImplementedError,RuntimeError) as exc:
            form.add_error(None,' '.join(exc.messages) if isinstance(exc,ValidationError) else 'The export could not be saved. Check the folder and try again; previous results are unchanged.')
        else:
            if form.recording_only and request.GET.get('inline')=='1' and request.headers.get('X-ASR-Editor')=='1':
                return JsonResponse({'recording_update':recording_update(round_,team)})
            messages.success(request,'Recording settings saved.' if form.recording_only else 'Results and recording settings saved.')
            return JsonResponse({'redirect':'/control/#results-recordings'}) if request.headers.get('X-ASR-Editor')=='1' else redirect('/control/#results-recordings')
    from .forms import prepare_dialog_form
    return render(request,'arena/_result_editor.html',{'form':prepare_dialog_form(form),'round':round_,'team':team,'recording':form.recording,'recording_history':RunRecording.objects.filter(round=round_,team=team,current=False)})


@require_POST
@staff_required
@transaction.atomic
def remove_recording(request,recording_id):
    from .services import audit
    from .models import Competition
    Competition.objects.select_for_update(no_key=True).get(pk=current_competition().pk)
    recording=get_object_or_404(RunRecording,pk=recording_id,round__competition=current_competition(),current=True)
    recording.current=False;recording.published=False;recording.save(update_fields=['current','published'])
    audit(request.user,'recording.removed',team=recording.team,object_id=recording.pk)
    if request.headers.get('X-ASR-Recording')=='1': return JsonResponse({'recording_update':recording_update(recording.round,recording.team)})
    messages.success(request,'Recording removed from Results. Its original files are retained privately in history.')
    return redirect('/control/#results-recordings')


@require_POST
@staff_required
@transaction.atomic
def restore_recording(request,recording_id):
    from .services import audit
    from .models import Competition
    Competition.objects.select_for_update(no_key=True).get(pk=current_competition().pk)
    recording=get_object_or_404(RunRecording,pk=recording_id,round__competition=current_competition())
    RunRecording.objects.filter(round=recording.round,team=recording.team,current=True).update(current=False,published=False)
    recording.current=True;recording.published=False;recording.save(update_fields=['current','published'])
    audit(request.user,'recording.restored',team=recording.team,object_id=recording.pk)
    if request.headers.get('X-ASR-Recording')=='1': return JsonResponse({'recording_update':recording_update(recording.round,recording.team)})
    messages.success(request,'Recording restored privately. Review it before publishing again.')
    return redirect('/control/#results-recordings')


@require_GET
@never_cache
def player(request,recording_id):
    import secrets
    recording=get_object_or_404(RunRecording.objects.select_related('round__challenge','team'),pk=recording_id)
    if not allowed(request,recording): raise Http404()
    from .recordings import match_result
    result=match_result(recording)
    if recording.video_key:
        from django.urls import reverse
        return JsonResponse({'kind':'video','url':reverse('recording-video',args=[recording.pk]),'title':f'{recording.team.name} · {recording.round}','result':result})
    token=signing.dumps({'id':str(recording.pk),'public':recording.public_open,'history':not recording.current,
        'session':None if recording.public_open else replay_session(request)},salt='webots-replay')
    from django.urls import reverse
    url=reverse('replay-asset',kwargs={'token':token,'path':recording.entry_path})
    response=JsonResponse({'url':url+'#'+secrets.token_urlsafe(24),'title':f'{recording.team.name} · {recording.round}',
        'version':recording.player_version,'frames':recording.frame_count,'duration_ms':recording.duration_ms,'result':result})
    if not recording.public_open:
        # Only replay requests may use this short-lived, HttpOnly session cookie.
        # The opaque sandbox cannot use the dashboard's SameSite=Lax cookie.
        response.set_cookie('asr_replay_session',request.session.session_key,
            max_age=None if request.session.get_expire_at_browser_close() else min(600,request.session.get_expiry_age()),
            path='/replay-view/',secure=True,httponly=True,samesite='None')
    return response


@require_GET
@never_cache
def preview(request,recording_id):
    recording=get_object_or_404(RunRecording.objects.select_related('round__challenge','team'),pk=recording_id)
    if not allowed(request,recording): raise Http404()
    try: stream=default_storage.open(recording_key(recording,recording.preview_path),'rb')
    except OSError: raise Http404('Preview temporarily unavailable.')
    response=FileResponse(stream,content_type=mimetypes.guess_type(recording.preview_path)[0] or 'image/jpeg')
    response['Content-Security-Policy']="sandbox; default-src 'none'";response['X-Content-Type-Options']='nosniff'
    return response


@require_http_methods(['GET','HEAD'])
@never_cache
def video(request,recording_id):
    """Check ownership/publication on every range request, including seeking."""
    recording=get_object_or_404(RunRecording.objects.select_related('round__challenge','team'),pk=recording_id)
    if not allowed(request,recording) or not recording.video_key: raise Http404()
    try:
        size=default_storage.size(recording.video_key)
        stream=default_storage.open(recording.video_key,'rb')
    except OSError: raise Http404('Video temporarily unavailable.')
    start,end=0,size-1
    requested=request.headers.get('Range') if request.method=='GET' else None
    if requested:
        match=re.fullmatch(r'bytes=(\d*)-(\d*)',requested)
        if not match or not any(match.groups()) or len(requested)>80:
            stream.close();response=HttpResponse(status=416);response['Content-Range']=f'bytes */{size}';return response
        first,last=match.groups()
        if first: start=int(first);end=min(int(last),end) if last else end
        else: start=max(0,size-int(last))
        if start>end or start>=size:
            stream.close();response=HttpResponse(status=416);response['Content-Range']=f'bytes */{size}';return response
    stream.seek(start)
    response=FileResponse(stream,status=206 if requested else 200,content_type=recording.video_type)
    def chunks():
        remaining=end-start+1
        while remaining>0:
            block=stream.read(min(65536,remaining))
            if not block: break
            remaining-=len(block);yield block
    if requested: response.streaming_content=chunks()
    response['Content-Length']=str(end-start+1)
    response['Accept-Ranges']='bytes'
    response['X-Content-Type-Options']='nosniff'
    if requested: response['Content-Range']=f'bytes {start}-{end}/{size}'
    return response


@require_GET
@never_cache
@xframe_options_exempt
def replay_asset(request,token,path):
    try:
        capability=signing.loads(token,salt='webots-replay',max_age=600)
        recording=RunRecording.objects.select_related('round__challenge','team').get(pk=capability['id'])
        safe_path(path)
    except (signing.BadSignature,RunRecording.DoesNotExist,ValidationError,KeyError,ValueError): raise Http404()
    if not allowed(request,recording): raise Http404()
    if not capability.get('public') and (not request.user.is_authenticated or not constant_time_compare(capability.get('session') or '',replay_session(request))): raise Http404()
    if not recording.current and not capability.get('history'): raise Http404()
    if capability['public'] and not recording.public_open: raise Http404()
    if path not in recording.manifest or not public_recording_path(recording,path): raise Http404()
    try: stream=default_storage.open(recording_key(recording,path),'rb')
    except OSError: raise Http404('A required replay file is temporarily unavailable.')
    mime=mimetypes.guess_type(path)[0] or 'application/octet-stream'
    if path.lower().endswith(('.html','.htm')):
        with stream: html=stream.read().decode('utf-8-sig')
        # The stored export is unchanged. This response-only bridge reports player readiness.
        network=f'<script src="{static("arena/replay-network.js")}"></script>'
        html=re.sub(r'(<head\b[^>]*>)',lambda match:match[0]+network,html,count=1,flags=re.I) if re.search(r'<head\b',html,re.I) else network+html
        bridge=f'<script src="{static("arena/replay-bridge.js")}" defer></script>'
        html=html.replace('</head>',bridge+'</head>',1) if '</head>' in html else bridge+html
        response=HttpResponse(html,content_type='text/html; charset=utf-8')
    else: response=FileResponse(stream,content_type=mime)
    # The opaque sandbox needs explicit hosts, including the validated serving alias.
    origin=' '.join(dict.fromkeys([settings.PUBLIC_ORIGIN.rstrip('/'),request.build_absolute_uri('/').rstrip('/')]))
    response['Content-Security-Policy']=(
        "sandbox allow-scripts allow-pointer-lock; default-src 'none'; "
        f"script-src {origin} https://cyberbotics.com https://www.cyberbotics.com 'unsafe-inline' 'unsafe-eval'; "
        f"style-src {origin} https://cyberbotics.com https://www.cyberbotics.com 'unsafe-inline'; "
        f"connect-src {origin} https://cyberbotics.com https://www.cyberbotics.com https://raw.githubusercontent.com; "
        f"img-src {origin} https://cyberbotics.com https://www.cyberbotics.com https://raw.githubusercontent.com data: blob:; "
        "font-src https://cyberbotics.com https://www.cyberbotics.com data:; worker-src blob:; "
        "frame-src 'none'; frame-ancestors 'self'; object-src 'none'; base-uri 'none'; form-action 'none'")
    response['Access-Control-Allow-Origin']='null'
    response['Access-Control-Allow-Credentials']='true'
    response['Cross-Origin-Resource-Policy']='cross-origin'
    response['Referrer-Policy']='no-referrer'
    response['X-Content-Type-Options']='nosniff'
    return response
