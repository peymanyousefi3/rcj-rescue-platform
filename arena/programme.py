"""Public programme grouping; submission and release rules remain server-owned."""
import hashlib
import json

from django.utils import timezone
from django.db.models import Q
from types import SimpleNamespace
from .models import Round


def programme_context(events, competition, *, selected_date=None, recordings=()):
    replays={(item.round_id,item.team_id):item for item in recordings}
    events=list(events)
    # Every active round is one calendar block, even before its lineup is filled.
    for round_ in Round.objects.filter(competition=competition,archived_at=None).filter(Q(challenge=None)|Q(challenge__archived_at=None)).select_related('challenge'):
        events.append(SimpleNamespace(pk=f'round-{round_.pk}',title=str(round_),starts_at=round_.starts_at,
            ends_at=round_.ends_at,confirmed=True,field='',team_id=None,round_id=round_.pk,round=round_))
    events.sort(key=lambda e:(e.starts_at,0 if str(e.pk).startswith('round-') else 1,str(e.pk)))
    from .fields import attach_maximum_scores
    attach_maximum_scores([event.round for event in events if event.round_id])
    days = []
    groups = {}
    cutoffs = {event.round.quarantine_at for event in events if event.round_id}
    revision = []
    today = timezone.localdate()
    for event in events:
        event.recording=replays.get((event.round_id,event.team_id))
        day = timezone.localtime(event.starts_at).date()
        revision.append([
            event.pk, event.title, event.starts_at.isoformat(), event.ends_at.isoformat(),
            event.confirmed, event.field, str(event.recording.pk) if event.recording else None,
            [event.team.code, event.team.name] if event.team_id else None,
            [event.round_id, event.round.number, str(event.round), event.round.name, event.round.submissions_enabled, event.round.quarantine_at.isoformat(),
             event.round.starts_at.isoformat(), event.round.ends_at.isoformat(),str(event.round.maximum_score)] if event.round_id else None,
        ])
        if not days or days[-1]['date'] != day:
            days.append({'date': day, 'key': day.isoformat(), 'blocks': []})
        # A round's visible deadline already represents this exact marker. Keep
        # any unmatched deadline rather than silently discarding organizer data.
        if (not event.round_id and event.title.casefold() == 'quarantine due'
                and event.starts_at in cutoffs):
            continue
        if event.round_id:
            key = (day, event.round_id)
            if key not in groups:
                group = {'kind': 'round', 'round': event.round, 'runs': [],
                         'field': event.field}
                groups[key] = group
                days[-1]['blocks'].append(group)
            if event.team_id: groups[key]['runs'].append(event)
            if event.field: groups[key]['field']=event.field
        else:
            title = event.title.casefold()
            category = ('practice' if any(word in title for word in ('practice','setup','set up','testing'))
                else 'break' if any(word in title for word in ('lunch','break'))
                else 'deadline' if 'quarantine' in title else 'session')
            days[-1]['blocks'].append({'kind': 'event', 'event': event, 'category': category})
    keys = {day['key'] for day in days}
    selection = (selected_date if selected_date in keys else today.isoformat()
                 if today.isoformat() in keys else days[0]['key'] if days else '')
    for day in days:
        day['selected'] = day['key'] == selection
    announcements = list(competition.announcement_set.filter(public=True,archived_at=None)[:5])
    version = hashlib.sha256(json.dumps([
        revision, competition.workbook_enabled, competition.workbook_last_synced.isoformat()
        if competition.workbook_last_synced else None,
        [[str(item.pk), item.title, item.body, item.created_at.isoformat()] for item in announcements],
    ], ensure_ascii=True).encode()).hexdigest()
    return {'programme_days': days, 'programme_version': version, 'public_announcements': announcements}
