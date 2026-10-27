from datetime import timedelta
import hashlib
import uuid
from pathlib import PurePath

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.urls import reverse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .access import team_for
from .models import (Announcement, Asset, AuditEvent, Competition, EmailDelivery,
                     Membership, Notification, Quarantine, QuarantineTeam, Round, Team)
from .policy import PACKAGE_KINDS, ROUND_KINDS, submission_open

def audit(user, action, asset=None, team=None, detail=None, object_id=''):
    return AuditEvent.objects.create(actor=user if user and user.is_authenticated else None,
        team=team or (asset.team if asset else None), action=action,
        object_id=str(asset.pk) if asset else str(object_id), sha256=asset.sha256 if asset else '',
        detail=detail or {})

def check_window(round_, competition):
    if not round_.submissions_enabled or (round_.challenge_id and round_.challenge.archived_at) or round_.archived_at is not None or not submission_open(now=timezone.now(), opens_at=round_.opens_at,
            quarantine_at=round_.quarantine_at, completed=round_.completed,
            finished=competition.phase == 'finished'):
        raise PermissionDenied('This round is locked. Uploads, replacements and deletions close at quarantine.')

def check_quarantine_window(quarantine, team):
    deadline = quarantine.deadline_for(team)
    if deadline is None or not team.active:
        raise PermissionDenied('This quarantine is not assigned to your team.')
    if timezone.now() >= deadline:
        raise PermissionDenied('This quarantine is locked. Files remain available for private download.')
    if quarantine.opens_at and timezone.now() < quarantine.opens_at:
        raise PermissionDenied('Uploads for this request have not opened yet.')

@transaction.atomic
def save_quarantine(*, user, competition, name, instructions, deadline, all_teams,
                    targets, round=None, quarantine_id=None, opens_at=None, challenge=None):
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        raise PermissionDenied()
    quarantine = (Quarantine.objects.select_for_update(of=('self',)).get(pk=quarantine_id,competition=competition)
        if quarantine_id else Quarantine(competition=competition))
    before = {'deadline':quarantine.deadline.isoformat(),'all_teams':quarantine.all_teams} if quarantine_id else None
    target_ids = [team.pk for team in targets]
    if not all_teams and not target_ids:
        raise ValidationError('Choose at least one team.')
    if Team.objects.participants(challenge).filter(pk__in=target_ids,competition=competition,active=True).count() != len(set(target_ids)):
        raise ValidationError('Choose active teams in this competition.')
    if challenge and (challenge.category!='superteam' or challenge.competition_id!=competition.pk or challenge.archived_at):
        raise ValidationError('Choose an active SuperTeam challenge in this competition.')
    quarantine.challenge=challenge
    quarantine.name=name; quarantine.instructions=instructions; quarantine.deadline=deadline
    quarantine.all_teams=all_teams; quarantine.round=round;quarantine.opens_at=opens_at
    quarantine.full_clean(); quarantine.save()
    # Keep individual overrides when switching to All teams. For a selected group,
    # removing a recipient withdraws its access to this request, not its stored files.
    if not all_teams:
        quarantine.team_deadlines.exclude(team_id__in=target_ids).delete()
        for team_id in target_ids:
            QuarantineTeam.objects.get_or_create(quarantine=quarantine,team_id=team_id)
    audit(user,'quarantine.updated' if quarantine_id else 'quarantine.created',object_id=quarantine.pk,
        detail={'name':name,'before':before,'deadline':deadline.isoformat(),'all_teams':all_teams,
                'targets':[str(pk) for pk in target_ids]})
    return quarantine

@transaction.atomic
def set_quarantine_deadline(*, user, quarantine_id, team, deadline):
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        raise PermissionDenied()
    quarantine = Quarantine.objects.select_for_update(of=('self',)).get(pk=quarantine_id,competition=team.competition)
    if quarantine.deadline_for(team) is None:
        raise ValidationError('This team is not assigned to this quarantine.')
    target, _ = QuarantineTeam.objects.get_or_create(quarantine=quarantine,team=team)
    previous=target.deadline
    target.deadline=deadline; target.full_clean(); target.save(update_fields=['deadline'])
    audit(user,'quarantine.team_deadline_updated',team=team,object_id=quarantine.pk,
        detail={'before':previous.isoformat() if previous else None,
                'deadline':deadline.isoformat() if deadline else None})

def upload_asset(*, user, file, kind, team=None, round_=None, title='', general=False,
                 target_ids=(), attested=False, public_copy=False, quarantine=None, replacement_id=None, append=False, complaint=None, share=None):
    staff = user.is_authenticated and user.is_active and user.is_staff
    if public_copy and (not staff or kind not in PACKAGE_KINDS | {'resource'}):
        raise PermissionDenied()
    if not staff:
        from .access import owns_team
        if not owns_team(user,team):
            raise PermissionDenied()
        if kind not in ROUND_KINDS | PACKAGE_KINDS | {'quarantine_file','complaint_file'}:
            raise PermissionDenied()
        if kind in ROUND_KINDS and not attested:
            raise ValidationError('Confirm that these are the files used for your run.')
    if kind=='complaint_file' and (not complaint or complaint.team_id!=(team.pk if team else None)):
        raise PermissionDenied()
    if kind not in dict(Asset.KINDS):
        raise ValidationError('Unknown file slot.')
    if kind == 'quarantine_file':
        if not quarantine or not team:
            raise ValidationError('Choose a quarantine and a team.')
        check_quarantine_window(quarantine, team)
        round_ = quarantine.round
    elif quarantine or (replacement_id and (public_copy or kind not in ROUND_KINDS | PACKAGE_KINDS)):
        raise ValidationError('Choose a private submission file to replace.')
    if file.size <= 0:
        raise ValidationError('File is empty.')
    competition = team.competition if team else round_.competition if round_ else Competition.objects.first()
    if not competition:
        raise ValidationError('Competition has not been configured.')
    if round_ and round_.competition_id != competition.pk:
        raise PermissionDenied()
    if round_ and team and team.superteam_challenge_id != (round_.challenge_id if round_.challenge_id and round_.challenge.category=='superteam' else None):
        raise PermissionDenied('Choose a round for this team’s challenge.')
    if kind in ROUND_KINDS:
        if not round_ or not team:
            raise ValidationError('Choose a round and a team.')
        check_window(round_, competition)
    if kind in PACKAGE_KINDS and not team:
        raise ValidationError('Choose a team.')
    digest = hashlib.sha256()
    measured = 0
    for chunk in file.chunks():
        measured += len(chunk)
        digest.update(chunk)
    file.seek(0)
    # Storage keys never contain team identities, original filenames or executable extensions.
    key = default_storage.save(f'objects/{uuid.uuid4().hex}', file)
    try:
        with transaction.atomic():
            # Every named-quarantine change locks quarantine, then round/team/assets.
            if quarantine:
                quarantine = Quarantine.objects.select_for_update(of=('self',)).select_related('competition').get(pk=quarantine.pk)
            if round_:
                round_ = Round.objects.select_for_update(of=('self',)).select_related('competition').get(pk=round_.pk)
                competition = round_.competition
            if team:
                team = Team.objects.select_for_update().get(pk=team.pk)
                if not staff:
                    from .access import owns_team
                    if not owns_team(user,team): raise PermissionDenied()
            if kind in ROUND_KINDS:
                # Recheck after the complete transfer. Starting before quarantine is insufficient.
                check_window(round_, competition)
            if quarantine:
                # Do not reuse prefetched targets: an admin may have changed a team deadline during transfer.
                check_quarantine_window(quarantine, team)
            if replacement_id:
                previous=Asset.objects.select_for_update().filter(pk=replacement_id,
                    quarantine=quarantine,team=team,round=round_,public_copy=False,
                    kind__in=ROUND_KINDS if kind=='round_file' else [kind],current=True,deleted_at=None).first()
                if previous is None:
                    raise PermissionDenied('That file is unavailable for replacement.')
                previous.current=False; previous.save(update_fields=['current'])
                audit(user,'file.superseded',previous)
            elif not append and kind in (ROUND_KINDS - {'round_file'}) | PACKAGE_KINDS:
                old = Asset.objects.filter(team=team, round=round_, kind=kind, current=True, deleted_at=None, public_copy=public_copy)
                for previous in old:
                    audit(user, 'file.superseded', previous)
                old.update(current=False)
            filename = PurePath(file.name.replace('\\', '/')).name
            filename = ''.join(ch for ch in filename if ch.isprintable() and ch not in '\r\n')[:180] or 'download'
            asset = Asset(competition=competition, team=team, round=round_, kind=kind,
                blob_key=key, original_name=filename, size=measured, sha256=digest.hexdigest(),
                uploader=user, title=title[:180], general=general, public_copy=public_copy,quarantine=quarantine,complaint=complaint,share=share)
            asset.full_clean(exclude=['targets'])
            asset.save()
            if staff and kind == 'resource':
                targets = Team.objects.filter(pk__in=target_ids, competition=competition, active=True)
                asset.targets.set(targets)
            audit(user, 'file.uploaded', asset, detail={'bytes': measured, 'kind': kind, 'attested': bool(attested), 'public_copy': public_copy})
            return asset
    except Exception:
        # Never publish an object whose metadata transaction was rejected.
        default_storage.delete(key)
        raise

def upload_quarantine_files(*, user, quarantine, team, files, replacement_id=None):
    if not files or (replacement_id and len(files)!=1):
        raise ValidationError('Choose one or more files, or exactly one replacement file.')
    uploaded=[]
    try:
        with transaction.atomic():
            # ponytail: one quarantine lock serializes batches; use per-team locks if event throughput requires it.
            quarantine=Quarantine.objects.select_for_update(of=('self',)).select_related('competition','round').get(pk=quarantine.pk)
            check_quarantine_window(quarantine,team)
            for file in files:
                uploaded.append(upload_asset(user=user,file=file,kind='quarantine_file',
                    team=team,quarantine=quarantine,replacement_id=replacement_id))
            # The complete batch must finish before the cutoff; no partially accepted batch.
            check_quarantine_window(quarantine,team)
        return uploaded
    except Exception:
        for asset in uploaded:
            default_storage.delete(asset.blob_key)
        raise

def upload_files(*, user, team, kind, files, round_=None, attested=False, replacement_id=None):
    if not files or (replacement_id and len(files)!=1):
        raise ValidationError('Choose one or more files, or exactly one replacement file.')
    uploaded=[]
    if kind in ROUND_KINDS:
        kind='round_file'
    try:
        with transaction.atomic():
            if round_:
                round_=Round.objects.select_for_update(of=('self',)).select_related('competition').get(pk=round_.pk)
                check_window(round_,team.competition)
            Team.objects.select_for_update().get(pk=team.pk)
            for file in files:
                uploaded.append(upload_asset(user=user,team=team,kind=kind,file=file,
                    round_=round_,attested=attested,replacement_id=replacement_id,append=True))
            if round_:
                check_window(round_,team.competition)
        return uploaded
    except Exception:
        for asset in uploaded:
            default_storage.delete(asset.blob_key)
        raise

def delete_submission(*, user, asset_id):
    with transaction.atomic():
        asset = Asset.objects.select_related('round__competition','team__competition','quarantine__competition').get(pk=asset_id)
        from .access import owns_team
        if not owns_team(user,asset.team) or asset.public_copy or asset.kind not in ROUND_KINDS | PACKAGE_KINDS | {'quarantine_file'}:
            raise PermissionDenied()
        if asset.quarantine_id:
            quarantine=Quarantine.objects.select_for_update(of=('self',)).select_related('competition').get(pk=asset.quarantine_id)
            check_quarantine_window(quarantine,asset.team)
        elif asset.round_id:
            round_ = Round.objects.select_for_update(of=('self',)).select_related('competition').get(pk=asset.round_id)
            check_window(round_, round_.competition)
        Team.objects.select_for_update().get(pk=asset.team_id)
        asset = Asset.objects.select_for_update().get(pk=asset_id, current=True, deleted_at=None)
        asset.deleted_at = timezone.now()
        asset.current = False
        asset.save(update_fields=['deleted_at','current'])
        audit(user, 'file.deleted', asset)

@transaction.atomic
def announce(*, user, competition, title, body, general, public, target_ids, queue_email=True,email_recipients=''):
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        raise PermissionDenied()
    from .mail import announcement_recipients
    extra=announcement_recipients(email_recipients)
    targets = Team.objects.filter(competition=competition, active=True)
    if not general:
        targets = targets.filter(pk__in=target_ids)
        if not targets.exists() and not public and not extra:
            raise ValidationError('Choose at least one recipient team.')
    targets = list(targets)
    notice = Announcement.objects.create(competition=competition, title=title, body=body,
        general=general, public=public, author=user,email_recipients=email_recipients)
    notice.targets.set(targets)
    for team in targets:
        Notification.objects.create(team=team, announcement=notice)
    if queue_email: queue_announcement_copy(notice,targets)
    audit(user, 'announcement.created', object_id=notice.pk, detail={'teams': [t.code for t in targets], 'public': public,'additional_emails':len(extra)})
    return notice


def queue_announcement_copy(notice,teams,*,resend=False):
    from .mail import announcement_recipients
    # A paired profile has no shared password or mailbox: notify its actual mentors.
    actual={}
    for team in teams:
        for recipient in team.members.filter(active=True) if team.is_superteam else [team]: actual[recipient.pk]=recipient
    teams=list(actual.values())
    recipients=[(team.leader_email,f'{team.name} Mentor',team,str(team.pk)) for team in teams if team.leader_email]
    selected={address.lower() for address,_,_,_ in recipients}
    for row in announcement_recipients(notice.email_recipients):
        if row['email'].lower() not in selected:
            key='email:'+hashlib.sha256(row['email'].lower().encode()).hexdigest()
            recipients.append((row['email'],row['name'] or 'Mentor',None,key))
    for address,name,team,key in recipients:
        context={'team':team,'notice':notice,'recipient_name':name,
            'dashboard_url':f'{settings.PUBLIC_ORIGIN}/portal/announcements/#announcement-{notice.pk}' if team else ''}
        EmailDelivery.objects.create(team=team,dedupe_key=f'announcement:{notice.pk}:{key}'+(':'+uuid.uuid4().hex if resend else ''),
            recipient=address,subject=('RoboCup ASR 2026 - Junior Rescue Simulation - '+' '.join(notice.title.splitlines()))[:200],
            body=render_to_string('arena/email/announcement.txt',context),
            html_body=render_to_string('arena/email/announcement.html',context))

@transaction.atomic
def invite_team(*, user, team, email, username=None):
    if not user.is_staff:
        raise PermissionDenied()
    team = Team.objects.select_for_update().get(pk=team.pk)
    if Membership.objects.filter(team=team).exists():
        raise ValidationError('This team already has an account. Use password reset or suspend the existing account.')
    account = get_user_model().objects.create_user(username=username or f'team-{team.code.lower()}', email=email)
    account.set_unusable_password()
    account.save(update_fields=['password'])
    Membership.objects.create(user=account, team=team)
    team.leader_email = email
    team.save(update_fields=['leader_email'])
    uid = urlsafe_base64_encode(force_bytes(account.pk))
    token = default_token_generator.make_token(account)
    link = settings.PUBLIC_ORIGIN + reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
    EmailDelivery.objects.create(team=team, dedupe_key=f'invite:{account.pk}:{uuid.uuid4()}',
        recipient=email, subject='Your ASR 26 team account',
        expires_at=timezone.now()+timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT),
        body=f'Your team account is ready.\n\nUsername: {account.username}\n\nSet your password within one hour:\n{link}\n\nOnly your team and authorized administrators can access your private submissions.')
    audit(user, 'account.invited', team=team, object_id=account.pk)
    return account

@transaction.atomic
def resend_invitation(*,user,team,queue_email=True):
    if not user.is_staff:
        raise PermissionDenied()
    team=Team.objects.select_for_update().get(pk=team.pk,active=True)
    membership=Membership.objects.select_related('user').get(team=team)
    account=membership.user
    if not account.is_active or (queue_email and not team.leader_email):
        raise ValidationError('An active account and leader email are required.')
    if not account.has_usable_password():
        # Renew the unusable marker so previously queued setup links are invalidated.
        account.set_unusable_password()
        account.save(update_fields=['password'])
    uid=urlsafe_base64_encode(force_bytes(account.pk))
    token=default_token_generator.make_token(account)
    link=settings.PUBLIC_ORIGIN+reverse('password_reset_confirm',kwargs={'uidb64':uid,'token':token})
    if queue_email:
        EmailDelivery.objects.create(team=team,dedupe_key=f'reinvite:{account.pk}:{uuid.uuid4()}',
            recipient=team.leader_email,subject='Your new ASR 26 account setup link',
            expires_at=timezone.now()+timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT),
            body=f'Username: {account.username}\n\nSet your password within one hour:\n{link}')
    audit(user,'account.invitation_renewed' if queue_email else 'account.setup_link_created',team=team,object_id=account.pk)
    return account, link
