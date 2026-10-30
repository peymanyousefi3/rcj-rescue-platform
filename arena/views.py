import csv
import hashlib
from functools import wraps
from django.conf import settings

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.debug import sensitive_post_parameters

from .access import can_download, can_download_file, public_asset, team_assets, team_for, superteams_for
from .forms import (prepare_dialog_form, AdminQuarantineUploadForm, AdminUploadForm, AnnouncementForm, EmailConfigurationForm, InviteForm,
                    ResourceForm, UploadForm, PlaybackForm, QuarantineDeadlineForm,
                    QuarantineForm, QuarantineUploadForm, SubmissionUploadForm)
from .models import (Asset, AuditEvent, Challenge, Competition, EmailConfiguration, EmailDelivery, Notification,
                     Programme, Quarantine, Round, Score, Team, Complaint, FileShare)
from .policy import PACKAGE_KINDS, ROUND_KINDS, best_rounds, challenge_total
from .programme import programme_context
from .mail import email_ready, mail_connection
from .services import (announce, audit, delete_submission, invite_team, resend_invitation,
                       save_quarantine, set_quarantine_deadline, upload_asset, upload_files, upload_quarantine_files)

def current_competition():
    return get_object_or_404(Competition, slug='asr26')

def team_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        membership = team_for(request.user)
        if not membership:
            if request.user.is_staff:
                return redirect('control')
            raise PermissionDenied('This account is not assigned to an active team.')
        request.team = membership.team
        superteam_id=kwargs.pop('superteam_id',None)
        if superteam_id:
            request.team=get_object_or_404(superteams_for(membership.team),pk=superteam_id)
        return view(request,*args,**kwargs)
    return wrapped

staff_required = user_passes_test(lambda u: u.is_authenticated and u.is_active and u.is_staff, login_url='/account/login/')

def public_events(competition):
    return Programme.objects.filter(competition=competition,archived_at=None).filter(
        Q(round=None)|Q(round__archived_at=None)).filter(Q(round__challenge=None)|Q(round__challenge__archived_at=None)).filter(Q(team=None)|Q(team__active=True))

def standings(competition, challenge=None):
    queryset=Round.objects.filter(competition=competition,archived_at=None).filter(Q(challenge=None)|Q(challenge__archived_at=None)).select_related('challenge')
    if challenge is not None: queryset=queryset.filter(challenge=challenge)
    else:
        primary=competition.challenge_set.filter(primary=True,archived_at=None).first()
        queryset=queryset.filter(challenge=primary)
        challenge=primary
    rounds = list(queryset)
    from .fields import attach_maximum_scores
    attach_maximum_scores(rounds)
    scores = {(s.team_id,s.round_id):s for s in Score.objects.filter(team__competition=competition)}
    teams=list(Team.objects.participants(challenge).filter(competition=competition, active=True).order_by('name'))
    rows = []
    if challenge and challenge.calculation=='trimmed_mean':
        from .scoring import field_standings
        rows=field_standings(rounds,teams,scores,challenge)
    for team in ([] if challenge and challenge.calculation=='trimmed_mean' else teams):
        cells = [scores.get((team.pk,r.pk)) for r in rounds]
        total, dropped = (challenge_total([getattr(s,challenge.score_source) if s else None for s in cells],challenge.calculation,challenge.top_count,challenge.expected_rounds)
            if challenge else best_rounds([s.normalized if s else None for s in cells],competition.counted_rounds))
        for index,cell in enumerate(cells):
            if cell: cell.discarded=index+1 in dropped
        rows.append({'team':team,'cells':cells,'total':total,'dropped':dropped,'rank':None})
    from .scoring import rank_standings
    rank_standings(rows,released=bool(challenge and challenge.rankings_released))
    for row in rows:
        row['round_scores']=[{'round':round_,'score':score} for round_,score in zip(rounds,row['cells'])]
        times=[scores[(row['team'].pk,round_.pk)].elapsed_seconds for round_ in rounds
            if (row['team'].pk,round_.pk) in scores and scores[(row['team'].pk,round_.pk)].elapsed_seconds is not None]
        row['total_time_seconds']=sum(times) if times else None
    return rounds, rows

@require_GET
def public_page(request, section='overview'):
    if section not in ['overview','schedule','results','teams','maps','playbacks','resources']:
        raise Http404()
    competition = current_competition()
    challenges=list(competition.challenge_set.filter(archived_at=None))
    result_groups=[]
    for challenge in challenges:
        group_rounds,group_rows=standings(competition,challenge)
        result_groups.append({'challenge':challenge,'rounds':group_rounds,'rows':group_rows})
    primary=next((item for item in challenges if item.primary),None)
    main_rounds,rows=standings(competition,primary)
    rounds=list(Round.objects.filter(competition=competition,archived_at=None).filter(Q(challenge=None)|Q(challenge__archived_at=None)).select_related('challenge'))
    events = list(public_events(competition).select_related('round__challenge','team'))
    days = []
    for event in events:
        day = timezone.localtime(event.starts_at).date()
        if not days or days[-1]['date'] != day:
            days.append({'date':day,'events':[]})
        days[-1]['events'].append(event)
    visible = [a for a in Asset.objects.filter(competition=competition, current=True, deleted_at=None,
        scan_status='clean', public_approved=True).select_related('competition','round','team') if public_asset(a)]
    archive = []
    for row in rows:
        team = row['team']
        archive.append({'team':team,'files':[{ 'kind':kind, 'assets':[a for a in visible if a.team_id==team.pk and a.kind==kind], 'asset':next((a for a in visible if a.team_id==team.pk and a.kind==kind),None)}
            for kind in ['tdp','video','code','bom','poster']]})
    live = [e for e in events if e.live]
    next_event = next((e for e in events if e.starts_at > timezone.now()),None)
    context = {'section':section,'rounds':rounds,'standings':rows,'result_groups':result_groups,'days':days,
        'live_events':live,'next_event':next_event,'archive':archive,
        'maps':[a for a in visible if a.kind=='map'],
        'resources':[a for a in visible if a.kind=='resource' and not a.share_id],
        'public_announcements':competition.announcement_set.filter(public=True,archived_at=None)[:5],
        'team_count':len(rows),'now':timezone.now(),
        'next_quarantine':next((r for r in rounds if r.quarantine_at > timezone.now()),None)}
    from .fields import field_packages
    from .workspaces import shared_resources
    context['resource_shares']=shared_resources(competition,request.user,public=True)
    context['field_packages']=field_packages(rounds,request.user)
    if section in ('overview','schedule','results','playbacks'):
        from .recording_views import visible_recordings
        context['recordings']=visible_recordings(request,competition)
        replays={(item.round_id,item.team_id):item for item in context['recordings']}
        for group in [*result_groups,{'rows':rows}]:
            for row in group['rows']:
                for item in row['round_scores']:
                    item['recording']=replays.get((item['round'].pk,row['team'].pk))
    if section in ('overview', 'schedule'):
        context.update(programme_context(events, competition, selected_date=request.GET.get('day'), recordings=context.get('recordings',())))
    return render(request,'arena/public.html',context)

@require_GET
@never_cache
def programme_fragment(request):
    competition = current_competition()
    events = list(public_events(competition).select_related('round__challenge', 'team'))
    from .recording_views import visible_recordings
    context = programme_context(events, competition, selected_date=request.GET.get('day'),
        recordings=visible_recordings(request,competition))
    context['competition'] = competition
    response = render(request, 'arena/_programme.html', context)
    response['Cache-Control'] = 'no-cache'
    return response

@require_GET
def live_data(request):
    c = current_competition()
    now = timezone.now()
    events = public_events(c).filter(confirmed=True, starts_at__lte=now, ends_at__gt=now).select_related('team')
    response = JsonResponse({'server_time':now.isoformat(),'events':[{'title':e.title,'team':e.team.name if e.team else None,
        'end':e.ends_at.isoformat()} for e in events], 'last_synced':c.workbook_last_synced.isoformat() if c.workbook_last_synced else None})
    response['Cache-Control'] = 'public, max-age=10'
    return response

def team_notices(team, compact=False):
    notices=list(Notification.objects.filter(Q(team=team)|Q(team__in=superteams_for(team)),announcement__archived_at=None).select_related('announcement').order_by('-announcement__created_at','-pk'))
    # A team may receive the same announcement directly and through its SuperTeam.
    # Those receipts still refer to one announcement in the dashboard.
    notices=list({notice.announcement_id:notice for notice in reversed(notices)}.values())[::-1]
    version=hashlib.sha256(repr([(n.pk,n.read_at,n.announcement.title,n.announcement.body,
        n.announcement.general,n.announcement.created_at) for n in notices]).encode()).hexdigest()
    return {'notices':notices[:3] if compact else notices,'notices_compact':compact,
        'notices_version':version,'unread_count':sum(n.read_at is None for n in notices)}

@require_GET
@never_cache
@team_required
def notices_fragment(request):
    context=team_notices(request.team,request.GET.get('compact')=='1')
    return JsonResponse({'unread':context['unread_count'],'version':context['notices_version'],
        'html':render_to_string('arena/_team_notices.html',context,request=request)})

@require_GET
@never_cache
@team_required
def portal(request, section='overview'):
    if section in ['quarantines','activity']:
        return redirect('/portal/submissions/' if section=='quarantines' else '/portal/')
    if section not in ['overview','submissions','documents','resources','announcements','results','maps','schedule']:
        raise Http404()
    team = request.team
    assets = list(team_assets(team))
    from .fields import field_packages
    from .recording_views import visible_recordings
    maps=field_packages(Round.objects.filter(competition=team.competition,archived_at=None).filter(Q(challenge=None)|Q(challenge__archived_at=None)).select_related('challenge'),request.user)
    slots = []
    scope=Q(challenge_id=team.superteam_challenge_id) if team.is_superteam else (Q(challenge=None)|~Q(challenge__category='superteam'))
    for r in Round.objects.filter(scope,competition=team.competition,archived_at=None).filter(Q(challenge=None)|Q(challenge__archived_at=None)).select_related('competition','challenge'):
        slots.append({'round':r,'files':[a for a in assets if a.round_id==r.pk and a.kind in ROUND_KINDS]})
    notice_context=team_notices(team,section=='overview')
    quarantines=[]
    unassigned_quarantine_files=[]
    if section == 'submissions':
        assigned=Quarantine.objects.filter(competition=team.competition,archived_at=None,challenge_id=team.superteam_challenge_id).filter(
            Q(all_teams=True)|Q(team_deadlines__team=team)).distinct().select_related('competition','round').prefetch_related('team_deadlines')
        history=list(Asset.objects.filter(team=team,kind='quarantine_file',deleted_at=None))
        for quarantine in assigned:
            deadline=quarantine.deadline_for(team)
            quarantines.append({'quarantine':quarantine,'deadline':deadline,
                'editable':bool(deadline and timezone.now()<deadline and (not quarantine.opens_at or timezone.now()>=quarantine.opens_at)),
                'files':[a for a in history if a.quarantine_id==quarantine.pk and a.current],
                'history':[a for a in history if a.quarantine_id==quarantine.pk and not a.current]})
        assigned_ids={item['quarantine'].pk for item in quarantines}
        unassigned_quarantine_files=[a for a in history if a.quarantine_id not in assigned_ids]
    from .workspaces import base_url, shared_resources
    groups=[]
    if section=='results':
        recordings={(r.round_id,r.team_id):r for r in visible_recordings(request,team.competition)}
        challenges=[team.superteam_challenge] if team.is_superteam else list(team.competition.challenge_set.filter(archived_at=None).exclude(category='superteam'))
        if not challenges: challenges=[None]
        for challenge in challenges:
            group_rounds,group_rows=standings(team.competition,challenge)
            if not team.is_superteam: group_rows=[row for row in group_rows if row['team'].pk==team.pk]
            for row in group_rows:
                for item in row['round_scores']: item['recording']=recordings.get((item['round'].pk,row['team'].pk))
            groups.append({'challenge':challenge,'rounds':group_rounds,'rows':group_rows})
    return render(request,'arena/portal.html',{'section':section, 'team':team,'slots':slots,
        'portal_base':base_url(team),'superteams':superteams_for(team) if not team.is_superteam else [],'portal_result_groups':groups,
        'superteam_events':public_events(team.competition).filter(round__challenge_id=team.superteam_challenge_id).select_related('team','round') if team.is_superteam else [],
        'quarantines':quarantines,'unassigned_quarantine_files':unassigned_quarantine_files,
        'previous_files':Asset.objects.filter(team=team,deleted_at=None,public_copy=False,quarantine=None).filter(Q(current=False)|Q(round__archived_at__isnull=False)|Q(round__challenge__archived_at__isnull=False))[:50],
        'packages':[{'kind':k,'files':[a for a in assets if a.kind==k]} for k in ['tdp','video','code','bom','poster']],
        'team_resources':[a for a in assets if a.kind=='resource' and not a.share_id and a.scan_status=='clean' and can_download(request.user,a)],
        'resource_shares':shared_resources(team.competition,request.user,team=team),
        'field_packages':maps,'recordings':[item for item in visible_recordings(request,team.competition) if item.team_id==team.pk], **notice_context,
        'events':public_events(team.competition).filter(team=team, ends_at__gt=timezone.now()).select_related('round')[:5],
        'upload_form':SubmissionUploadForm()})

@require_POST
@team_required
def quarantine_upload(request, quarantine_id):
    quarantine=get_object_or_404(Quarantine.objects.select_related('competition','round'),
        pk=quarantine_id,competition=request.team.competition)
    if quarantine.deadline_for(request.team) is None:
        raise Http404()
    form=QuarantineUploadForm(request.POST,request.FILES)
    if form.is_valid():
        try:
            assets=upload_quarantine_files(user=request.user,quarantine=quarantine,team=request.team,
                files=form.cleaned_data['files'],replacement_id=form.cleaned_data['replacement'])
            messages.success(request,f'{len(assets)} file(s) received privately for {quarantine.name}. Each file has a SHA-256 receipt.')
        except ValidationError as exc:
            messages.error(request,' '.join(exc.messages))
        except PermissionDenied as exc:
            messages.error(request,str(exc))
    else:
        messages.error(request,' '.join(error for errors in form.errors.values() for error in errors))
    from .workspaces import base_url
    return redirect(base_url(request.team)+'/submissions/#quarantine-'+str(quarantine.pk))

@require_POST
@team_required
def submit(request, kind, round_id=None):
    if kind not in ROUND_KINDS | PACKAGE_KINDS:
        raise Http404()
    if (kind in ROUND_KINDS) != bool(round_id):
        raise Http404()
    round_ = get_object_or_404(Round,pk=round_id,competition=request.team.competition) if round_id else None
    data=request.FILES.copy()
    if 'files' not in data and 'file' in data:
        data.setlist('files',data.getlist('file'))
    form = SubmissionUploadForm(request.POST,data)
    if form.is_valid():
        try:
            assets = upload_files(user=request.user, files=form.cleaned_data['files'],kind=kind,team=request.team,
                round_=round_,attested=form.cleaned_data['attested'],replacement_id=form.cleaned_data['replacement'])
            messages.success(request,f'{len(assets)} file(s) received privately. Each file has a SHA-256 receipt.')
        except ValidationError as exc:
            messages.error(request,' '.join(exc.messages))
        except PermissionDenied as exc:
            messages.error(request,str(exc))
    else:
        messages.error(request,'Upload not accepted. Select a non-empty file and check the form.')
    from .workspaces import base_url
    return redirect(base_url(request.team)+('/submissions/' if kind in ROUND_KINDS else '/documents/'))

@require_POST
@team_required
def remove_file(request, asset_id):
    asset=get_object_or_404(Asset,pk=asset_id)
    try:
        delete_submission(user=request.user,asset_id=asset_id)
    except Asset.DoesNotExist:
        raise Http404()
    messages.success(request,'File removed from the submission slot. An audit record is retained.')
    from .workspaces import base_url
    return redirect(base_url(asset.team)+('/documents/' if asset.kind in PACKAGE_KINDS else '/submissions/'))

@require_GET
@never_cache
def download(request, asset_id):
    asset = get_object_or_404(Asset.objects.select_related('competition','round','team'), pk=asset_id)
    if not can_download_file(request.user,asset):
        # Same response for unknown IDs and inaccessible files.
        raise Http404()
    audit(request.user,'file.downloaded',asset)
    try:
        stream = default_storage.open(asset.blob_key,'rb')
    except (OSError,FileNotFoundError):
        raise Http404('File temporarily unavailable.')
    response = FileResponse(stream,as_attachment=True,filename=asset.original_name,content_type='application/octet-stream')
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "sandbox; default-src 'none'"
    response['Cache-Control'] = 'private, no-store'
    response['X-File-SHA256'] = asset.sha256
    response['Content-Length'] = str(asset.size)
    return response

@require_POST
@team_required
def read_notice(request, notice_id):
    from .access import accessible_team_ids
    notice = get_object_or_404(Notification,pk=notice_id,team_id__in=accessible_team_ids(request.user))
    if not notice.read_at:
        Notification.objects.filter(announcement=notice.announcement,team_id__in=accessible_team_ids(request.user),read_at=None).update(read_at=timezone.now())
        audit(request.user,'announcement.read',team=request.team,object_id=notice.announcement_id)
    from .workspaces import base_url
    return redirect(base_url(request.team)+'/announcements/')

@staff_required
@sensitive_post_parameters('password')
def control(request):
    c = current_competition()
    from .control_management import manage
    management_context, management_response=manage(request,c)
    if management_response is not None: return management_response
    form_kind = request.POST.get('form') if request.method=='POST' else None
    email_config=EmailConfiguration.objects.filter(pk=1).first() or EmailConfiguration(
        sender_email=settings.DEFAULT_FROM_EMAIL if settings.EMAIL_HOST else '',
        host=settings.EMAIL_HOST,port=settings.EMAIL_PORT,username=settings.EMAIL_HOST_USER)
    email_form=EmailConfigurationForm(request.POST if form_kind=='email-settings' else None,
        instance=email_config,auto_id='email_%s')
    notice_form = AnnouncementForm(request.POST if form_kind=='announcement' else None,competition=c,auto_id='announcement_%s')
    resource_form = ResourceForm(request.POST if form_kind=='resource' else None,request.FILES if form_kind=='resource' else None,competition=c,auto_id='resource_%s')
    invite_form = InviteForm(request.POST if form_kind=='invite' else None,competition=c,auto_id='invite_%s')
    playback_form = PlaybackForm(request.POST if form_kind=='playback' else None,competition=c,auto_id='playback_%s')
    private_form = AdminUploadForm(request.POST if form_kind=='private-upload' else None,
        request.FILES if form_kind=='private-upload' else None,competition=c,auto_id='private_%s')
    public_form = AdminUploadForm(request.POST if form_kind=='public-upload' else None,
        request.FILES if form_kind=='public-upload' else None,competition=c,public_copy=True,auto_id='public_%s')
    quarantine_id=((request.POST.get('quarantine_id') or request.POST.get('record_id')) if form_kind=='quarantine' else request.GET.get('quarantine'))
    try:
        editing=get_object_or_404(Quarantine,pk=quarantine_id,competition=c) if quarantine_id else None
    except (ValidationError,ValueError):
        raise Http404()
    quarantine_form=QuarantineForm(request.POST if form_kind=='quarantine' else None,
        instance=editing,competition=c,auto_id='quarantine_%s')
    quarantine_upload_form=AdminQuarantineUploadForm(request.POST if form_kind=='quarantine-upload' else None,
        request.FILES if form_kind=='quarantine-upload' else None,competition=c,auto_id='qupload_%s')
    if request.method=='POST':
        try:
            if form_kind=='email-check':
                connection=None
                try:
                    if not email_config.password_encrypted:
                        raise ValidationError('Save your connection credential first.')
                    connection,_=mail_connection(allow_paused=True)
                    connection.open()
                except Exception:
                    audit(request.user,'email.connection_checked',object_id=1,detail={'success':False})
                    messages.error(request,'Connection failed. Check the saved email address and app password, and your provider’s connection settings. No email was sent.')
                else:
                    audit(request.user,'email.connection_checked',object_id=1,detail={'success':True})
                    messages.success(request,'The saved email connection authenticated successfully. No email was sent.')
                finally:
                    if connection:
                        try:
                            connection.close()
                        except Exception:
                            connection=None  # Failed cleanup must not turn a successful check into an error.
                return redirect('/control/#email-settings')
            if form_kind=='email-settings' and email_form.is_valid():
                config=email_form.save()
                audit(request.user,'email.settings_updated',object_id=1,
                    detail={'enabled':config.enabled,'fields':email_form.changed_data})
                messages.success(request,'Email settings saved. Automatic delivery is enabled for queued messages.' if config.enabled else
                    'Email settings saved. Delivery is paused; queued messages are retained.')
                return JsonResponse({'redirect':'/control/#email-settings'}) if request.headers.get('X-ASR-Editor')=='1' else redirect('/control/#email-settings')
            if form_kind=='quarantine' and quarantine_form.is_valid():
                quarantine=save_quarantine(user=request.user,competition=c,quarantine_id=quarantine_id,
                    round=editing.round if editing else None,**quarantine_form.cleaned_data)
                messages.success(request,'Named quarantine saved. Individual team deadlines can be set below.')
                return JsonResponse({'redirect':'/control/#quarantine-'+str(quarantine.pk)}) if request.headers.get('X-ASR-Editor')=='1' else redirect('/control/#quarantine-'+str(quarantine.pk))
            if form_kind=='quarantine-deadline':
                form=QuarantineDeadlineForm(request.POST)
                quarantine=get_object_or_404(Quarantine,competition=c,pk=request.POST.get('quarantine_id'))
                team=get_object_or_404(Team,competition=c,active=True,pk=request.POST.get('team_id'))
                if form.is_valid():
                    set_quarantine_deadline(user=request.user,quarantine_id=quarantine.pk,
                        team=team,deadline=form.cleaned_data['deadline'])
                    messages.success(request,'Team deadline saved. Clearing an individual deadline restores the default.')
                    return JsonResponse({'redirect':'/control/#quarantine-'+str(quarantine.pk)}) if request.headers.get('X-ASR-Editor')=='1' else redirect('/control/#quarantine-'+str(quarantine.pk))
                raise ValidationError('Enter a valid Toronto date and time, or leave blank to use the default.')
            if form_kind=='quarantine-upload' and quarantine_upload_form.is_valid():
                d=quarantine_upload_form.cleaned_data
                assets=upload_quarantine_files(user=request.user,quarantine=d['quarantine'],team=d['team'],
                    files=d['files'],replacement_id=d['replacement'])
                messages.success(request,f'{len(assets)} file(s) uploaded privately to the selected team quarantine.')
                return redirect('/control/#quarantines')
            if form_kind in ('private-upload','public-upload'):
                form = public_form if form_kind=='public-upload' else private_form
                if form.is_valid():
                    d = form.cleaned_data
                    upload_asset(user=request.user,file=d['file'],kind=d['kind'],team=d['team'],
                        round_=d.get('round'),title=d['title'],attested=d.get('attested',False),
                        public_copy=form.public_copy,general=form.public_copy and d['kind']=='resource',
                        replacement_id=d['replacement'].pk if d.get('replacement') else None,append=not form.public_copy)
                    messages.success(request,'Separate public copy uploaded; scanning and approval are required.' if form.public_copy else 'Team file uploaded privately. Only this team and administrators have access.')
                    return redirect('/control/#files')
            if form_kind=='playback' and playback_form.is_valid():
                d = playback_form.cleaned_data
                with transaction.atomic():
                    r = Round.objects.select_for_update().get(pk=d['round'].pk,competition=c)
                    if d['released'] and not r.release_ready:
                        raise ValidationError('Complete the round before publishing its playback.')
                    r.playback_url=d['playback_url']; r.playback_released=d['released']
                    r.save(update_fields=['playback_url','playback_released'])
                    audit(request.user,'round.playback_updated',object_id=r.pk,detail={'released':r.playback_released})
                messages.success(request,'Webots playback saved.' if not r.playback_open else 'Webots playback published.')
                return redirect('/control/#rounds')
            if form_kind=='announcement' and notice_form.is_valid():
                d = notice_form.cleaned_data
                notice=announce(user=request.user,competition=c,title=d['title'],body=d['body'],general=d['general'],
                    public=d['public'],target_ids=[t.pk for t in d['targets']],email_recipients=d['email_recipients'])
                count=notice.targets.count()
                queued=EmailDelivery.objects.filter(dedupe_key__startswith=f'announcement:{notice.pk}:').count()
                messages.success(request,f'Announcement published to {count} team dashboard(s); {queued} personalized email(s) queued.' + (' It also appears on the public homepage.' if d['public'] else ''))
                if not email_ready():
                    messages.warning(request,'Email delivery is not configured. Teams can read this announcement in their dashboard; queued emails have not been sent.')
                if notice.targets.filter(leader_email='').exists():
                    messages.warning(request,'Teams without a leader email receive dashboard notifications only.')
                return redirect('control')
            if form_kind=='resource' and resource_form.is_valid():
                d = resource_form.cleaned_data
                from .control_management import upload_batch
                upload_batch(request.user,c,dict(destination='map' if d['kind']=='map' else 'organizer',files=d['file'],round=d['round'],title=d['title'],
                    general=d['general'],targets=list(d['targets'])))
                messages.success(request,'Document uploaded privately and queued for scanning.')
                return redirect('control')
            if form_kind=='invite' and invite_form.is_valid():
                invite_team(user=request.user,**invite_form.cleaned_data)
                messages.success(request,'Account created. A password setup email is queued for the leader.')
                return redirect('control')
        except (ValidationError,PermissionDenied) as exc:
            error=' '.join(exc.messages) if isinstance(exc,ValidationError) else str(exc)
            if request.headers.get('X-ASR-Editor')=='1':
                return JsonResponse({'error':error},status=400)
            messages.error(request,error)
    editor=request.GET.get('editor')
    if editor in ['quarantine','email-settings']:
        return render(request,'arena/_email_editor.html' if editor=='email-settings' else 'arena/_record_editor.html',{'editor_modal':True,'form':prepare_dialog_form(email_form if editor=='email-settings' else quarantine_form), 'form_kind':editor,'record':editing if editor=='quarantine' else None,'cancel_section':'quarantines' if editor=='quarantine' else 'email-settings','email_password_saved':bool(email_config.password_encrypted)})
    from .workspaces import admin_shares
    teams=list(Team.objects.regular().filter(competition=c).prefetch_related('membership_set__user').order_by('name'))
    quarantine_rows=[]
    for quarantine in Quarantine.objects.filter(competition=c).select_related('round','competition').prefetch_related('team_deadlines'):
        targets=list(quarantine.team_deadlines.all())
        rows=[]
        for team in Team.objects.participants(quarantine.challenge).filter(competition=c,active=True):
            deadline=quarantine.deadline_for(team)
            if deadline:
                target=next((row for row in targets if row.team_id==team.pk),None)
                rows.append({'team':team,'deadline':deadline,
                    'override':timezone.localtime(target.deadline).strftime('%Y-%m-%dT%H:%M') if target and target.deadline else '',
                    'locked':timezone.now()>=deadline})
        quarantine_rows.append({'quarantine':quarantine,'teams':rows,'files':Asset.objects.filter(competition=c,quarantine=quarantine).select_related('team','round__challenge','uploader')})
    round_windows=[{'round':r,'files':Asset.objects.filter(competition=c,round=r,quarantine=None,public_copy=False,kind__in=ROUND_KINDS).select_related('team','round__challenge','uploader')} for r in Round.objects.filter(competition=c).select_related('challenge')]
    return render(request,'arena/control.html',{'section':'control','notice_form':notice_form,
        'resource_form':resource_form,'invite_form':invite_form,'playback_form':playback_form,
        'private_form':private_form,'public_form':public_form,'email_configured':email_ready(),
        'email_form':email_form,'email_password_saved':bool(email_config.password_encrypted),
        'quarantine_form':quarantine_form,'quarantine_upload_form':quarantine_upload_form,
        'editing_quarantine':editing,'quarantine_rows':quarantine_rows,'round_windows':round_windows,
        'complaints':Complaint.objects.filter(competition=c).select_related('team','author').prefetch_related('attachments'),
        'participant_documents':Asset.objects.filter(competition=c,team__isnull=False,public_copy=False,quarantine=None,round=None,kind__in=PACKAGE_KINDS).select_related('team','uploader'),'teams':teams,**management_context,
        'rounds':Round.objects.filter(competition=c).select_related('competition','challenge'),
        'files':Paginator(Asset.objects.filter(competition=c,quarantine=None,share=None).filter(Q(team=None)|Q(public_copy=True)|Q(kind='map')).select_related('team','round','uploader','quarantine').prefetch_related('targets'),100).get_page(request.GET.get('files_page')),
        'file_shares':admin_shares(c),
        'audit_events':AuditEvent.objects.select_related('actor','team')[:100],
        'email_pending':EmailDelivery.objects.filter(sent_at=None).filter(Q(team=None)|Q(team__active=True)).filter(Q(expires_at=None) | Q(expires_at__gt=timezone.now())).count(),
        'email_failed':EmailDelivery.objects.filter(sent_at=None,attempts__gt=0).filter(Q(team=None)|Q(team__active=True)).filter(Q(expires_at=None) | Q(expires_at__gt=timezone.now())).count()})

@require_POST
@staff_required
@transaction.atomic
def control_action(request):
    action = request.POST.get('action')
    c = Competition.objects.select_for_update(no_key=True).get(pk=current_competition().pk)
    try:
        from .control_management import action as management_action, pause_workbook
        section=management_action(request,c)
        if section:
            messages.success(request,'Change saved. Removed records and their history can be restored here.')
            return redirect('/control/#'+section)
        if action == 'approve-file':
            asset = get_object_or_404(Asset,pk=request.POST.get('id'),competition=c,current=True,deleted_at=None)
            if asset.scan_status!='clean' or (not asset.public_copy and asset.kind!='map') or asset.kind in ROUND_KINDS:
                raise ValidationError('Private team files cannot be published. Upload a separate public copy first.')
            if asset.share_id:
                share=asset.share
                if share.archived_at or not share.public or share.files.filter(current=True,deleted_at=None).exclude(scan_status='clean').exists():
                    raise ValidationError('Every file in this shared delivery must pass scanning before public approval.')
                share.public_approved=True;share.save(update_fields=['public_approved'])
                from .control_forms import sync_share_files
                sync_share_files(share)
            asset.public_approved = True
            asset.save(update_fields=['public_approved'])
            audit(request.user,'file.publication_approved',asset)
        elif action in ['complete-round','release-maps']:
            r = get_object_or_404(Round.objects.select_for_update(),pk=request.POST.get('id'),competition=c)
            if action=='complete-round':
                r.completed=True
            elif not r.completed:
                raise ValidationError('Mark the round completed before releasing its maps.')
            else:
                r.maps_released=True
            r.save(update_fields=['completed','maps_released'])
            audit(request.user,f'round.{action}',object_id=r.pk)
        elif action=='release-archive':
            if timezone.now() < c.ends_at:
                raise ValidationError('The competition has not ended. Team packages remain private.')
            c.phase='finished'
            c.archive_released=True
            c.save(update_fields=['phase','archive_released'])
            audit(request.user,'competition.archive_released',object_id=c.pk)
        elif action=='revoke-archive':
            c.archive_released=False
            c.save(update_fields=['archive_released'])
            audit(request.user,'competition.archive_revoked',object_id=c.pk)
        elif action in ('suspend-team','reactivate-team'):
            team = get_object_or_404(Team,competition=c,pk=request.POST.get('id'))
            team.active=action=='reactivate-team'
            team.save(update_fields=['active'])
            pause_workbook(c)
            for m in team.membership_set.select_related('user'):
                m.user.is_active=team.active
                m.user.save(update_fields=['is_active'])
            audit(request.user,'account.reactivated' if team.active else 'account.suspended',team=team)
        elif action=='setup-link':
            team=get_object_or_404(Team,competition=c,pk=request.POST.get('id'),active=True)
            if not team.membership_set.exists():
                raise ValidationError('Create this team’s account first.')
            account, link=resend_invitation(user=request.user,team=team,queue_email=False)
            response=render(request,'arena/account_access.html',{'team':team,'account':account,'setup_link':link})
            response['Referrer-Policy']='no-referrer'
            return response
        elif action=='resend-invitation':
            team=get_object_or_404(Team,competition=c,pk=request.POST.get('id'),active=True)
            resend_invitation(user=request.user,team=team)
        else:
            raise ValidationError('Unknown action.')
        messages.success(request,'Change saved and recorded in the audit log.')
    except ValidationError as exc:
        messages.error(request,' '.join(exc.messages))
    return redirect('control')

@require_GET
@staff_required
def audit_export(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition']='attachment; filename="asr26-audit.csv"'
    response['Cache-Control']='private, no-store'
    writer=csv.writer(response)
    writer.writerow(['UTC time','Actor','Team','Action','Object','SHA-256'])
    for e in AuditEvent.objects.select_related('actor','team').iterator(chunk_size=500):
        cells=[e.occurred_at.isoformat(),e.actor.username if e.actor else '',e.team.code if e.team else '',e.action,e.object_id,e.sha256]
        writer.writerow([("'"+v) if v.startswith(('=','+','-','@','\t','\r')) else v for v in cells])
    audit(request.user,'audit.exported')
    return response

@require_GET
def health(request):
    from django.db import connection, DatabaseError
    try:
        with connection.cursor() as cursor: cursor.execute('SELECT 1')
    except DatabaseError:
        response=JsonResponse({'status':'unavailable'},status=503)
    else:
        response=JsonResponse({'status':'ok'})
    response['Cache-Control']='no-store'
    return response

@require_GET
def readiness(request):
    import shutil
    from django.conf import settings
    result=health(request)
    if result.status_code!=200: return result
    try:
        ready=shutil.disk_usage(settings.PRIVATE_ROOT).free>=settings.UPLOAD_MIN_FREE_BYTES
    except (OSError,ValueError,KeyError): ready=False
    response=JsonResponse({'status':'ok' if ready else 'unavailable'},status=200 if ready else 503)
    response['Cache-Control']='no-store'
    return response

@never_cache
@require_POST
@staff_required
@transaction.atomic
def calendar_move(request):
    """Persist a drag/resize, including all child runs, or leave everything unchanged."""
    from django import forms
    from .scheduling import revision,move_round_runs,lineup_data
    from .control_management import pause_workbook
    class MoveForm(forms.Form):
        kind=forms.ChoiceField(choices=[('round','Round'),('event','Activity')])
        id=forms.IntegerField(min_value=1)
        revision=forms.CharField(max_length=64)
        starts_at=forms.DateTimeField()
        ends_at=forms.DateTimeField()
    form=MoveForm(request.POST)
    if not form.is_valid(): return JsonResponse({'error':'Choose valid dates and times.'},status=400)
    data=form.cleaned_data
    c=Competition.objects.select_for_update(no_key=True).get(pk=current_competition().pk)
    model=Round if data['kind']=='round' else Programme
    item=get_object_or_404(model.objects.select_for_update(),competition=c,pk=data['id'],archived_at=None)
    if isinstance(item,Programme) and item.round_id: return JsonResponse({'error':'Move the round that owns this team run.'},status=400)
    if isinstance(item,Round) and item.challenge_id and item.challenge.archived_at:
        return JsonResponse({'error':'Restore this challenge before changing its calendar.'},status=400)
    if data['revision']!=revision(item): return JsonResponse({'error':'This entry changed in another window. Reload the calendar before moving it.'},status=409)
    start,end=data['starts_at'],data['ends_at']
    if isinstance(item,Round):
        if abs(((end-start)-(item.ends_at-item.starts_at)).total_seconds())>1:
            return JsonResponse({'error':'Round finish times come from the team lineup. Edit the team run times instead.'},status=400)
        from datetime import timedelta
        rows=lineup_data(item)
        end=start+timedelta(minutes=sum(row['duration']+row['gap'] for row in rows)) if rows else start+(item.ends_at-item.starts_at)
    if (end-start).total_seconds()<60 or (end-start).total_seconds()>604800:
        return JsonResponse({'error':'Use a duration between one minute and seven days.'},status=400)
    if isinstance(item,Round) and (item.completed or item.maps_released or item.playback_released) and end>timezone.now():
        return JsonResponse({'error':'Reopen the round and withdraw its releases before moving it to a future time.'},status=400)
    old_start=item.starts_at;item.starts_at=start;item.ends_at=end
    try:
        if isinstance(item,Round): move_round_runs(item,old_start)
        item.full_clean();item.save();pause_workbook(c)
    except ValidationError as exc:
        transaction.set_rollback(True)
        return JsonResponse({'error':' '.join(exc.messages)},status=400)
    audit(request.user,'calendar.moved',object_id=item.pk,detail={'kind':data['kind'],'start':start.isoformat(),'end':end.isoformat()})
    return JsonResponse({'revision':revision(item),'end':timezone.localtime(item.ends_at).strftime('%Y-%m-%dT%H:%M:%S'),'message':'Schedule saved. Team run times moved with the round.' if isinstance(item,Round) else 'Schedule saved.'})
