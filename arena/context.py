from .models import Competition, Notification
from .access import team_for, accessible_team_ids

def site_context(request):
    membership = team_for(request.user)
    from django.urls import reverse
    from django.templatetags.static import static
    competition=Competition.objects.first()
    branding={'logo':static('arena/brand/platform.svg'),'partner':None,'banner':static('arena/brand/platform-hero.svg')}
    if competition:
        for slot,field in [('logo','logo_key'),('partner','partner_logo_key'),('banner','banner_key')]:
            if getattr(competition,field):branding[slot]=reverse('branding-image',args=[competition.pk,slot])
    return {'competition': competition,'branding':branding, 'membership': membership,
        'unread_count': Notification.objects.filter(team_id__in=accessible_team_ids(request.user), read_at=None, announcement__archived_at=None).values('announcement_id').distinct().count() if membership else 0}
