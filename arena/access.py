from django.db.models import Q
from django.conf import settings
from django.utils import timezone
from two_factor.utils import default_device
from .models import Asset, Membership, Team
from .policy import visible_to_public

MAP_DOWNLOAD_ROLES = ('wbt','map_json')

def staff_otp_required(user):
    return user.is_authenticated and user.is_staff and (
        settings.REQUIRE_STAFF_OTP or default_device(user) is not None)

def team_for(user):
    if not user.is_authenticated or not user.is_active:
        return None
    return Membership.objects.select_related('team__competition').filter(user=user, team__active=True).first()

def superteams_for(team):
    return Team.objects.filter(competition=team.competition,active=True,members=team,
        superteam_challenge__category='superteam',superteam_challenge__archived_at=None).distinct()

def accessible_team_ids(user):
    membership=team_for(user)
    return [membership.team_id,*superteams_for(membership.team).values_list('pk',flat=True)] if membership else []

def owns_team(user, team):
    return bool(team and team.active and team.pk in accessible_team_ids(user))

def public_asset(asset):
    if asset.kind=='complaint_file': return False
    share=asset.share if asset.share_id else None
    if share and share.archived_at: return False
    c, r = asset.competition, asset.round
    if (r and (r.archived_at or r.challenge_id and r.challenge.archived_at)) or (asset.team_id and not asset.team.active):
        return False
    if asset.kind=='map' and r and not r.map_public: return False
    return visible_to_public(kind=asset.kind, current=asset.current,
        deleted=asset.deleted_at is not None, clean=asset.scan_status == 'clean',
        approved=share.public_approved if share else asset.public_approved, competition_finished=c.phase == 'finished',
        archive_released=c.archive_released, competition_ended=timezone.now() >= c.ends_at,
        round_completed=bool(r and r.completed), round_released=bool(r and r.maps_released),
        round_ended=bool(r and timezone.now() >= r.ends_at), general=share.general if share else asset.general, public_copy=share.public if share else asset.public_copy)

def can_download(user, asset):
    if public_asset(asset):
        return True
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_staff:
        return True
    share=asset.share if asset.share_id else None
    if share and share.archived_at: return False
    m = team_for(user)
    if not m or m.team.competition_id!=asset.competition_id or asset.deleted_at is not None or (asset.public_copy and asset.kind!='resource'):
        return False
    owned=accessible_team_ids(user)
    if asset.kind=='map':
        r=asset.round
        return bool(r and r.maps_open and asset.current and asset.scan_status=='clean' and asset.public_approved and (r.map_general or r.map_targets.filter(pk__in=owned).exists()))
    if asset.team_id in owned:
        return True
    return asset.current and asset.kind == 'resource' and asset.scan_status == 'clean' and (
        (share.general or share.targets.filter(pk__in=owned).exists()) if share else (asset.general or asset.targets.filter(pk__in=owned).exists()))


def can_download_file(user, asset):
    """Map viewers use supporting assets; participant downloads expose only competition files."""
    return can_download(user,asset) and (asset.kind!='map' or asset.map_role in MAP_DOWNLOAD_ROLES
        or user.is_authenticated and user.is_active and user.is_staff)

def team_assets(team):
    return Asset.objects.filter(competition=team.competition, current=True, deleted_at=None).filter(Q(public_copy=False)|Q(kind='resource')).filter(
        Q(team=team) | Q(kind='resource', general=True) | Q(kind='resource', targets=team) | Q(kind='resource',share__general=True) | Q(kind='resource',share__targets=team) | Q(kind='map',round__map_general=True) | Q(kind='map',round__map_targets=team)
    ).select_related('competition','round','uploader').distinct()
