"""Anonymous-only presentation data: never serialize accounts, uploads or recipient lists."""
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from .branding import branding_urls
from .views import current_competition, public_events, standings


def number(value, places=2):
    return format(value, f'.{places}f') if value is not None else None


def public_payload(competition):
    now=timezone.now()
    settings={key:getattr(competition,'slide_'+key) for key in ['intro','schedule','results','intro_seconds',
        'schedule_seconds','results_seconds','refresh_seconds','rows']}
    payload={'enabled':competition.slideshow_enabled,'generated_at':now.isoformat(),'settings':settings}
    if not competition.slideshow_enabled:
        return payload
    payload['competition']={'name':competition.name,'short_name':competition.short_name,
        'header_title':competition.header_title,'league_name':competition.league_name,
        'banner_title':competition.banner_title,'banner_subtitle':competition.banner_subtitle,
        'location':competition.location,'dates':f'{timezone.localtime(competition.starts_at):%d %B %Y} – {competition.display_end_date:%d %B %Y}',
        'branding':branding_urls(competition)}
    day=display_day(competition,now)
    from .slide_settings import TEXTS,COLORS,values,resolve,text_template,challenge_context
    context=values(competition,day,now);design=competition.slide_design or {}
    payload['design']={'texts':{key:resolve(text_template(design,key),context) for key,(_,default) in TEXTS.items()},
        'colors':{key:design.get('colors',{}).get(key,default) for key,(_,default) in COLORS.items()},
        'images':slide_images(competition)}
    payload['schedule_date']=day.isoformat()
    events=list(public_events(competition).filter(confirmed=True,starts_at__date=day).select_related('team','round__challenge'))
    payload['schedule']=[]
    grouped={}
    if competition.slide_schedule:
        for event in events:
            if event.round_id:
                if event.round_id in grouped:
                    grouped[event.round_id]['end']=timezone.localtime(event.ends_at).strftime('%H:%M');continue
                row={'title':str(event.round),'start':timezone.localtime(event.starts_at).strftime('%H:%M'),
                    'end':timezone.localtime(event.ends_at).strftime('%H:%M'),
                    'note':payload['design']['texts']['quarantine_label']+' '+timezone.localtime(event.round.quarantine_at).strftime('%H:%M'),
                    'accent':not event.round.challenge_id or event.round.challenge.primary}
                grouped[event.round_id]=row
            else:
                row={'title':event.title,'start':timezone.localtime(event.starts_at).strftime('%H:%M'),
                    'end':timezone.localtime(event.ends_at).strftime('%H:%M'),'note':'','accent':True}
            payload['schedule'].append(row)
    payload['results']=[]
    if competition.slide_results:
        for challenge in competition.challenge_set.filter(archived_at=None):
            rounds,rows=standings(competition,challenge)
            payload['results'].append({'name':challenge.name,'id':challenge.pk,
                'method':challenge_context(challenge,len(rounds))['method'],'round_count':len(rounds),
                'rankings_released':challenge.rankings_released,'percentage':challenge.calculation=='trimmed_mean',
                'rounds':[{'id':r.pk,'label':f'R{r.number}','name':r.name,'maximum':number(r.maximum_score) if r.maps_open and r.map_public else None} for r in rounds],
                'rows':[{'name':row['team'].name,'code':row['team'].code,'country':row['team'].country,
                    'rank':row['rank'] if challenge.rankings_released else None,
                    'tie':bool(row.get('tie')) if challenge.rankings_released else False,
                    'total':number(row['total']),'time':row['total_time_seconds'],
                    'scores':[{'raw':number(cell.raw) if cell else None,
                        'normalized':number(cell.normalized,4) if cell else None,
                        'discarded':bool(getattr(cell,'discarded',False)),
                        'excluded':bool(getattr(cell,'excluded',False))} for cell in row['cells']]} for row in rows]})
    return payload


@require_GET
@never_cache
def display(request):
    competition=current_competition()
    return render(request,'arena/slideshow.html',{'competition':competition,'branding':branding_urls(competition)})


@require_GET
@never_cache
def data(request):
    return JsonResponse(public_payload(current_competition()))


def display_day(competition,now):
    today=timezone.localdate(now);first=timezone.localtime(competition.starts_at).date();last=competition.display_end_date
    days=[timezone.localtime(value).date() for value in public_events(competition).filter(confirmed=True).values_list('starts_at',flat=True)]
    days=[day for day in days if first<=day<=last]
    if today<first:return min(days,default=first)
    if today>=last:return last
    return today


def slide_images(competition):
    from django.templatetags.static import static
    from django.urls import reverse
    from .slide_settings import IMAGE_SLOTS
    branding=branding_urls(competition)
    result={'logo':branding['logo'],'partner':branding['partner'],'cover':branding['banner'],
        'qr':reverse('slideshow-qr',args=[competition.pk])}
    for slot in IMAGE_SLOTS:
        if (competition.slide_design or {}).get('images',{}).get(slot):
            result[slot]=reverse('slideshow-image',args=[competition.pk,slot])
    return result


@require_GET
@never_cache
def image(request,competition_id,slot):
    import re
    from .models import Competition
    from .slide_settings import IMAGE_SLOTS
    from django.http import FileResponse,Http404
    from django.shortcuts import get_object_or_404
    from django.core.files.storage import default_storage
    competition=get_object_or_404(Competition,pk=competition_id)
    if not competition.slideshow_enabled and not (request.user.is_authenticated and request.user.is_active and request.user.is_staff):raise Http404()
    if slot not in IMAGE_SLOTS:raise Http404()
    key=(competition.slide_design or {}).get('images',{}).get(slot,'')
    if not isinstance(key,str) or not re.fullmatch(r'branding/'+str(competition.pk)+r'/[a-f0-9]{32}\.png',key):raise Http404()
    try:stream=default_storage.open(key,'rb')
    except (OSError,ValueError):raise Http404()
    response=FileResponse(stream,content_type='image/png')
    response['Content-Security-Policy']="default-src 'none'; sandbox"
    response['X-Content-Type-Options']='nosniff'
    return response


@require_GET
@never_cache
def qr(request,competition_id):
    import io,qrcode
    from django.conf import settings
    from django.http import HttpResponse
    from django.shortcuts import get_object_or_404
    from .models import Competition
    c=get_object_or_404(Competition,pk=competition_id,slideshow_enabled=True)
    out=io.BytesIO();code=qrcode.QRCode(border=0);code.add_data((c.slide_design or {}).get('qr_destination') or settings.PUBLIC_ORIGIN);code.make(fit=True)
    code.make_image(fill_color='#122039',back_color='white').save(out,format='PNG')
    return HttpResponse(out.getvalue(),content_type='image/png')
