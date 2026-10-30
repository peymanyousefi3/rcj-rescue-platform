from .models import Competition, Notification
from .access import team_for, accessible_team_ids

def site_context(request):
    membership = team_for(request.user)
    from .branding import branding_urls
    competition=Competition.objects.first()
    branding=branding_urls(competition)
    return {'competition': competition,'branding':branding, 'membership': membership,
        'unread_count': Notification.objects.filter(team_id__in=accessible_team_ids(request.user), read_at=None, announcement__archived_at=None).values('announcement_id').distinct().count() if membership else 0}
