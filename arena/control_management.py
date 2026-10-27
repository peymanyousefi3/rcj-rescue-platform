"""Complete organizer record management, shared by the existing control page."""
import uuid
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.core.files.base import File
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from .control_forms import (ChallengeForm, CompetitionForm, FileForm, FileShareForm, ManagedUploadForm, ManageAnnouncementForm,
    ProgrammeForm, RoundForm, RoundWindowForm, TeamForm)
from .models import Announcement, Asset, Challenge, Competition, EmailDelivery, FileShare, Programme, Quarantine, Round, Team
from .services import announce, audit, invite_team, upload_asset, upload_quarantine_files, queue_announcement_copy
from .scheduling import LineupForm, calendar_entries, revision
from .workspaces import SuperTeamForm


def pause_workbook(competition):
    if competition.workbook_enabled:
        competition.workbook_enabled=False
        competition.save(update_fields=['workbook_enabled'])


def editing(request, model, competition, key, form_kind):
    pk=request.POST.get('record_id') if request.method=='POST' and request.POST.get('form')==form_kind else request.GET.get(key)
    try:
        return get_object_or_404(model,pk=pk,competition=competition) if pk else None
    except (ValueError,ValidationError):
        raise Http404()


def manage(request, competition):
    if not request.user.is_active or not request.user.is_staff: raise PermissionDenied()
    kind=request.POST.get('form') if request.method=='POST' else None
    specs=[('team',Team,TeamForm,'accounts'),('superteam',Team,SuperTeamForm,'accounts'),('round',Round,RoundForm,'rounds'),
        ('event',Programme,ProgrammeForm,'programme'),('file',Asset,FileForm,'files'),('share',FileShare,FileShareForm,'files'),
        ('challenge',Challenge,ChallengeForm,'competition-settings'),('window',Round,RoundWindowForm,'quarantines'),
        ('notice',Announcement,ManageAnnouncementForm,'announce')]
    context={};records={};forms={}
    for key,model,form_class,section in specs:
        record=editing(request,model,competition,key,'lineup' if kind=='lineup' and key=='round' else key)
        if record and key in ['team','superteam'] and record.is_superteam!=(key=='superteam'): raise Http404()
        if kind in ['file','window','share'] and key==kind and record is None: raise Http404()
        records[key]=record
        kwargs={'competition':competition,'auto_id':key+'_%s'}
        if key=='notice': kwargs['notice']=record
        else: kwargs['instance']=record
        if request.GET.get('editor')==key and key in ['round','event'] and (not record or key=='round'):
            from django.forms import DateTimeField
            for name in ['starts_at','ends_at']:
                try: value=DateTimeField(required=False).clean(request.GET.get(name,''))
                except ValidationError: value=None
                if value: kwargs.setdefault('initial',{})[name]=value
            if key=='event' and kwargs.get('initial',{}).get('starts_at') and kwargs['initial'].get('ends_at'):
                kwargs['initial']['duration_minutes']=int((kwargs['initial']['ends_at']-kwargs['initial']['starts_at']).total_seconds()/60)
        if key=='round' and request.GET.get('editor')=='round' and not record:
            selected=request.GET.get('round_challenge','')
            if selected.isdigit():
                challenge=Challenge.objects.filter(pk=selected,competition=competition,archived_at=None).first()
                if challenge:
                    initial=kwargs.setdefault('initial',{});initial['challenge']=challenge.pk
                    initial['number']=(Round.objects.filter(challenge=challenge).order_by('-number').values_list('number',flat=True).first() or 0)+1
        form=form_class(request.POST if kind==key else None,request.FILES if kind==key else None,**kwargs)
        context[key+'_form']=forms[key]=form
        context['editing_'+key]=record
    if records['event'] and records['event'].round_id:
        return context,redirect(f"/control/?editor=round&round={records['event'].round_id}")
    context['lineup_form']=forms['round'].lineup_form
    if kind=='lineup' and records['round']:
        forms['lineup']=context['lineup_form']=LineupForm(request.POST,round_=records['round'])
        forms['round'].lineup_form=forms['lineup']
    context['lineup_teams']=[{'id':str(t.pk),'name':t.name,'code':t.code,'challenge':str(t.superteam_challenge_id or '')} for t in Team.objects.filter(competition=competition,active=True).order_by('name')]
    context['superteam_challenge_ids']=list(Challenge.objects.filter(competition=competition,category='superteam',archived_at=None).values_list('pk',flat=True))
    context['superteams']=Team.objects.filter(competition=competition,superteam_challenge__isnull=False).select_related('superteam_challenge').prefetch_related('members')
    forms['competition']=context['competition_form']=CompetitionForm(
        request.POST if kind=='competition' else None,instance=competition,auto_id='competition_%s')
    replacement=None
    if request.GET.get('replace'):
        try: replacement=get_object_or_404(Asset,pk=request.GET['replace'],competition=competition,current=True,deleted_at=None)
        except (ValueError,ValidationError): raise Http404()
    context['replacement_file']=replacement
    initial={}
    if replacement:
        destination=('quarantine' if replacement.quarantine_id else 'organizer' if replacement.kind=='resource' else 'public' if replacement.public_copy and replacement.team_id
            else 'resource' if replacement.public_copy else 'map' if replacement.kind=='map' else 'team' if replacement.team_id else 'organizer')
        initial={'replacement':replacement.pk,'destination':destination,'team':replacement.team_id,'kind':replacement.kind,
            'round':replacement.round_id,'quarantine':replacement.quarantine_id,'title':replacement.title,
            'general':replacement.general,'targets':list(replacement.targets.values_list('pk',flat=True)),
            'audience':('public_all' if replacement.general else 'public_selected' if replacement.targets.exists() else 'public') if replacement.public_copy else 'all' if replacement.general else 'selected'}
    if request.GET.get('editor')=='managed-upload' and not replacement:
        if request.GET.get('upload_quarantine'):
            selected=get_object_or_404(Quarantine,pk=request.GET['upload_quarantine'],competition=competition,archived_at=None)
            initial.update(destination='quarantine',quarantine=selected.pk)
        elif request.GET.get('upload_round'):
            selected=get_object_or_404(Round,pk=request.GET['upload_round'],competition=competition,archived_at=None)
            initial.update(destination='team',kind='round_file',round=selected.pk)
    forms['managed-upload']=context['managed_upload_form']=ManagedUploadForm(
        request.POST if kind=='managed-upload' else None,request.FILES if kind=='managed-upload' else None,
        competition=competition,initial=initial,auto_id='managed_upload_%s')
    valid=kind in forms and forms[kind].is_valid()
    map_uploads=[]
    if valid:
        form=forms[kind]
        try:
            with transaction.atomic():
                if kind in ['team','superteam','round','event','competition','challenge','window','lineup']:
                    Competition.objects.select_for_update(no_key=True).get(pk=competition.pk)
                if kind=='superteam':
                    team=form.save()
                    pause_workbook(competition)
                    audit(request.user,'superteam.updated' if records[kind] else 'superteam.created',team=team,
                        detail={'members':[str(t.pk) for t in form.cleaned_data['members']],'fields':form.changed_data})
                elif kind=='team':
                    team=form.save(commit=False)
                    old=Team.objects.select_for_update().filter(pk=team.pk).first()
                    team.save()
                    for membership in team.membership_set.select_related('user'):
                        account=membership.user
                        if account.email!=team.leader_email:
                            EmailDelivery.objects.filter(team=team,sent_at=None).exclude(recipient=team.leader_email).update(expires_at=timezone.now())
                        account.email=team.leader_email;account.is_active=team.active
                        if form.cleaned_data['username']: account.username=form.cleaned_data['username']
                        account.full_clean(exclude=['password']);account.save(update_fields=['email','is_active','username'])
                    if form.cleaned_data.get('create_account'):
                        desired=form.cleaned_data.get('username') or f'team-{team.code.lower()}'
                        if get_user_model().objects.filter(username=desired).exists():
                            raise ValidationError('Choose an unused account username.')
                        account=invite_team(user=request.user,team=team,email=team.leader_email,username=desired)
                        if desired!=account.username:
                            account.username=desired;account.save(update_fields=['username'])
                    if not old or any(getattr(old,k)!=getattr(team,k) for k in ['name','code','country','school','active']):
                        pause_workbook(competition)
                    if old and old.active!=team.active:
                        from .scoring import normalize_round
                        for score_round in Round.objects.filter(competition=competition,score__isnull=False).distinct(): normalize_round(score_round)
                    audit(request.user,'team.updated' if old else 'team.created',team=team,detail={'fields':form.changed_data})
                elif kind=='lineup':
                    form.save(request.user);pause_workbook(competition)
                    messages.success(request,'Team order and run times saved. The calendar and public schedule now use this lineup.')
                    return context,redirect(f'/control/?round={records["round"].pk}#lineup-editor')
                elif kind=='competition':
                    resumed='workbook_enabled' in form.changed_data and form.cleaned_data['workbook_enabled']
                    if resumed: form.instance.workbook_digest=''
                    if form.instance.archive_released and (form.instance.ends_at>timezone.now() or form.instance.phase!='finished'):
                        form.instance.archive_released=False
                    form.save();audit(request.user,'competition.updated',object_id=competition.pk,detail={'fields':form.changed_data})
                elif kind in ['round','event','challenge','window']:
                    item=form.save(commit=False)
                    old=type(item).objects.get(pk=item.pk) if item.pk and kind in ['round','event'] else None
                    if old and form.cleaned_data.get('revision') and form.cleaned_data['revision']!=revision(old):
                        raise ValidationError('This entry changed in another window. Reload it before saving.')
                    if kind=='round' and old and form.lineup_form.cleaned_data.get('revision') and form.lineup_form.cleaned_data['revision']!=revision(old):
                        raise ValidationError('The lineup changed in another window. Reload it before saving.')
                    if kind=='event' and not item.source_key: item.source_key='manual:'+uuid.uuid4().hex
                    item.save()
                    if kind=='round':
                        form.lineup_form.save(request.user,round_=item,verify=False)
                        if 'recipient_module' in request.POST: item.map_targets.set(form.cleaned_data['targets'])
                        from .fields import save_maps
                        map_uploads=save_maps(form,request.user)
                    pause_workbook(competition)
                    audit(request.user,kind+'.updated' if records[kind] else kind+'.created',object_id=item.pk,detail={'fields':form.changed_data})
                elif kind in ['file','share']:
                    item=form.save()
                    audit(request.user,'file.details_updated' if kind=='file' else 'fileshare.updated',item if kind=='file' else None,object_id=item.pk,detail={'fields':form.changed_data})
                elif kind=='notice':
                    d=form.cleaned_data;notice=records['notice']
                    if notice:
                        notice=Announcement.objects.select_for_update().get(pk=notice.pk,competition=competition)
                        for field in ['title','body','general','public','email_recipients']: setattr(notice,field,d[field])
                        notice.full_clean(exclude=['targets']);notice.save()
                        targets=Team.objects.filter(competition=competition,active=True)
                        if not d['general']: targets=targets.filter(pk__in=[t.pk for t in d['targets']])
                        notice.targets.set(targets)
                        notice.notification_set.exclude(team__in=targets).delete()
                        for team in targets:
                            notice.notification_set.update_or_create(team=team,defaults={'read_at':None})
                        EmailDelivery.objects.filter(dedupe_key__startswith=f'announcement:{notice.pk}:',sent_at=None).update(expires_at=timezone.now())
                        if d['send_email'] and not notice.archived_at: queue_announcement_copy(notice,targets,resend=True)
                        audit(request.user,'announcement.updated',object_id=notice.pk,detail={'email_requested':d['send_email']})
                    else:
                        announce(user=request.user,competition=competition,title=d['title'],body=d['body'],general=d['general'],
                            public=d['public'],target_ids=[t.pk for t in d['targets']],queue_email=d['send_email'],email_recipients=d['email_recipients'])
                elif kind=='managed-upload':
                    upload_batch(request.user,competition,form.cleaned_data)
                messages.success(request,'Changes saved.'+(' Workbook updates are paused so your edits are preserved.' if kind in ['team','round','event'] and not competition.workbook_enabled else ''))
                section=next((s for k,m,f,s in specs if k==kind),'competition-settings' if kind=='competition' else 'files')
                if kind=='file' and form.instance.team_id and not form.instance.public_copy: section='quarantines'
                if kind=='managed-upload' and form.cleaned_data['destination'] in ['team','quarantine']: section='quarantines'
                if kind in ['challenge','round'] and request.POST.get('_return')=='results-recordings':
                    selected=item.pk if kind=='challenge' else item.challenge_id
                    target='/control/?score_challenge='+str(selected)+'#results-recordings'
                    return context,JsonResponse({'redirect':target}) if request.headers.get('X-ASR-Editor')=='1' else redirect(target)
                if request.headers.get('X-ASR-Editor')=='1':
                    return context,JsonResponse({'redirect':'/control/#'+(request.POST.get('_return') or section)})
                if request.POST.get('_return')=='programme':
                    return context,JsonResponse({'redirect':'/control/#programme'}) if request.headers.get('X-ASR-Editor')=='1' else redirect('/control/#programme')
                if kind=='round':
                    return context,redirect('/control/#rounds')
                return context,redirect('/control/#'+section)
        except (ValidationError,PermissionDenied,IntegrityError) as exc:
            for asset in map_uploads: default_storage.delete(asset.blob_key)
            form.add_error(None,' '.join(exc.messages) if isinstance(exc,ValidationError) else 'Another record already uses this value. Check the team code, username or round number.' if isinstance(exc,IntegrityError) else str(exc))
    editor=request.GET.get('editor')
    if editor in forms:
        section=next((s for k,m,f,s in specs if k==editor),'competition-settings' if editor=='competition' else 'files')
        return context,render(request,'arena/_calendar_editor.html' if editor in ['round','event'] else 'arena/_record_editor.html',{
            'editor_modal':True,'form_kind':editor,'form':forms[editor],'record':records.get(editor),
            'upload':editor=='managed-upload','round_choices':Round.objects.filter(competition=competition,archived_at=None),
            'cancel_section':request.GET.get('return',section),'save_label':'Save changes'})
    from datetime import timedelta
    context['calendar_first_day']=timezone.localtime(competition.starts_at).date().isoformat()
    local_end=timezone.localtime(competition.ends_at)
    context['calendar_end_day']=(local_end-timedelta(microseconds=1)).date()+timedelta(days=1) if local_end.hour==0 and local_end.minute==0 else local_end.date()+timedelta(days=1)
    context['calendar_end_day']=context['calendar_end_day'].isoformat()
    context['all_announcements']=Announcement.objects.filter(competition=competition).prefetch_related('targets')
    context['calendar_entries']=calendar_entries(competition)
    context['removed_programme_entries']=Programme.objects.filter(competition=competition,round=None,archived_at__isnull=False)
    from .recording_views import results_context
    context.update(results_context(competition,request.GET.get('score_challenge')))
    context['score_tables']=[results_context(competition,challenge.pk) for challenge in competition.challenge_set.filter(archived_at=None)]
    if not context['score_tables']: context['score_tables']=[results_context(competition)]
    context['challenges']=Challenge.objects.filter(competition=competition)
    return context,None


def upload_batch(user,competition,data):
    destination=data['destination']
    public_copy=destination in ['public','resource'] or destination=='organizer' and data.get('audience','').startswith('public')
    targets=list(data.get('targets') or [])
    if destination in ['team','quarantine','public'] and targets:
        if data.get('replacement') and len(targets)!=1: raise ValidationError('Replace a file for its original team only.')
        uploaded=[]
        try:
            with transaction.atomic():
                for team in targets:
                    batch=dict(data,targets=[],team=team)
                    batch['files']=[File(file.file,name=file.name) for file in data['files']]
                    for file in batch['files']: file.seek(0)
                    uploaded.extend(upload_batch(user,competition,batch))
            return uploaded
        except Exception:
            for asset in uploaded: default_storage.delete(asset.blob_key)
            raise
    replacement=None
    if data.get('replacement'):
        replacement=get_object_or_404(Asset.objects.select_for_update(),competition=competition,pk=data['replacement'],current=True,deleted_at=None)
    if destination=='quarantine':
        if replacement and replacement.quarantine_id!=data['quarantine'].pk: raise ValidationError('Choose the original quarantine when replacing a file.')
        return upload_quarantine_files(user=user,quarantine=data['quarantine'],team=data['team'],files=data['files'],replacement_id=replacement.pk if replacement else None)
    kind=data['kind'] if destination in ['team','public'] else 'map' if destination=='map' else 'resource'
    team=data['team'] if destination in ['team','public'] else None
    round_=data['round'] if destination=='map' or kind=='round_file' else None
    if replacement and (replacement.team_id!=(team.pk if team else None) or replacement.round_id!=(round_.pk if round_ else None)
            or replacement.public_copy!=public_copy or replacement.quarantine_id
            or replacement.kind!=kind and not(kind=='round_file' and replacement.kind in ['round_code','round_json'])):
        raise ValidationError('Replacement files must keep the original owner, category and round. Use a new upload to create a different record.')
    uploaded=[]
    try:
        with transaction.atomic():
            share=None
            if destination in ['organizer','resource']:
                share=replacement.share if replacement and replacement.share_id else FileShare(competition=competition,author=user)
                share.title=data.get('title') or (share.title if share.pk and not share._state.adding else data['files'][0].name[:180])
                share.public_approved=False
                share.general=destination=='resource' or bool(data.get('general'))
                share.public=public_copy;share.save()
                share.targets.set(targets)
            if replacement and destination!='team':
                replacement.current=False;replacement.public_approved=False
                replacement.save(update_fields=['current','public_approved'])
                audit(user,'file.superseded',replacement)
            for file in data['files']:
                uploaded.append(upload_asset(user=user,file=file,kind=kind,title=data['title'],
                    team=data['team'] if destination in ['team','public'] else None,
                    round_=data['round'] if destination=='map' or kind=='round_file' else None,
                    general=destination=='resource' or (destination=='organizer' and data['general']),
                    target_ids=[t.pk for t in data['targets']] if destination=='organizer' else [],
                    public_copy=public_copy,append=True,
                    replacement_id=replacement.pk if replacement and destination=='team' else None,share=share))
            if share:
                from .control_forms import sync_share_files
                sync_share_files(share)
                audit(user,'fileshare.uploaded',object_id=share.pk,detail={'files':[str(asset.pk) for asset in uploaded]})
        return uploaded
    except Exception:
        for item in uploaded: default_storage.delete(item.blob_key)
        raise


def action(request,competition):
    operation=request.POST.get('action','')
    if operation in ['remove-share','restore-share','approve-share','withdraw-share']:
        from .control_forms import sync_share_files
        share=get_object_or_404(FileShare.objects.select_for_update(),pk=request.POST.get('id'),competition=competition)
        if operation=='approve-share':
            files=share.files.filter(current=True,deleted_at=None)
            if not share.public or share.archived_at or not files.exists() or files.exclude(scan_status='clean').exists():
                raise ValidationError('All files must pass scanning before approving a public delivery.')
            share.public_approved=True
        else:
            if operation in ['remove-share','restore-share']: share.archived_at=timezone.now() if operation=='remove-share' else None
            share.public_approved=False
        share.save();sync_share_files(share)
        audit(request.user,'fileshare.'+operation,object_id=share.pk)
        return 'files'
    choices={'round':(Round,'rounds'),'quarantine':(Quarantine,'quarantines'),
        'event':(Programme,'programme'),'announcement':(Announcement,'announce'),'challenge':(Challenge,'competition-settings')}
    for name,(model,section) in choices.items():
        if operation in ['remove-'+name,'restore-'+name]:
            item=get_object_or_404(model.objects.select_for_update(),pk=request.POST.get('id'),competition=competition)
            if name=='challenge':
                # Round uploads hold these same row locks through their final deadline check.
                list(Round.objects.select_for_update().filter(challenge=item).order_by('pk'))
            item.archived_at=timezone.now() if operation.startswith('remove-') else None
            item.save(update_fields=['archived_at'])
            if name in ['round','event','challenge']: pause_workbook(competition)
            if name=='announcement' and item.archived_at:
                EmailDelivery.objects.filter(dedupe_key__startswith=f'announcement:{item.pk}:',sent_at=None).update(expires_at=timezone.now())
            audit(request.user,name+'.removed' if item.archived_at else name+'.restored',object_id=item.pk)
            return section
    if operation in ['remove-admin-file','restore-admin-file','withdraw-file']:
        item=get_object_or_404(Asset.objects.select_for_update(),pk=request.POST.get('id'),competition=competition)
        if item.share_id:
            item.share.public_approved=False;item.share.save(update_fields=['public_approved'])
            if operation=='withdraw-file': item.share.files.update(public_approved=False)
        if operation=='remove-admin-file': item.deleted_at=timezone.now();item.current=False
        if operation=='restore-admin-file':
            item.deleted_at=None
            conflict=Asset.objects.filter(team=item.team,round=item.round,kind=item.kind,public_copy=item.public_copy,
                current=True,deleted_at=None).exclude(pk=item.pk).exists()
            item.current=not(conflict and item.kind in ['round_code','round_json'])
        item.public_approved=False
        item.save(update_fields=['deleted_at','current','public_approved'])
        audit(request.user,'file.'+operation,item)
        return 'files'
    return None
