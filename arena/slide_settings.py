"""Editable content for the three reference slide layouts."""
from datetime import datetime,time
TEXTS={
 'brand_word':('Introduction · Brand word','{organization}'),
 'event_short':('Introduction · Short event name','{short_name}'),
 'event_name':('Introduction · Competition name','{competition_name}'),
 'welcome':('Introduction · Welcome label','WELCOME TO'),
 'title_small':('Introduction · Small title line','{division}'),
 'title_large':('Introduction · Large title line','{league_first}'),
 'title_bottom':('Introduction · Bottom title line','{league_rest}'),
 'qr_caption':('Introduction & schedule · QR caption','Details & schedule'),
 'venue':('Introduction & schedule · Venue','{venue}'),
 'venue_location':('Introduction & schedule · Venue location','{venue_location}'),
 'schedule_title':('Schedule · Heading','{weekday}’s highlights'),
 'schedule_subtitle':('Schedule · Subtitle','{league_display}'),
 'schedule_date':('Schedule · Date label','{date}'),
 'timezone':('Schedule · Time zone','{timezone} time · {zone}'),
 'quarantine_label':('Schedule · Round deadline label','Quarantine deadline'),
 'no_schedule':('Schedule · Empty-day message','No schedule entries for this day.'),
 'results_title':('Results · Table heading','{challenge}'),
 'results_method':('Results · Method description','{round_count} rounds · {method}'),
 'results_date':('Results · Date label','{date}'),
 'results_updated':('Results · Update label','Updated {updated} {zone}'),
 'results_link':('Results · Footer link text','{results_address}'),
 'results_released':('Results · Released footer','Final rankings · Strikethrough = discarded'),
 'results_unreleased':('Results · Unreleased footer','Scores only · Rankings not released · Strikethrough = discarded'),
 'rank':('Results · Rank column','Rank'),'team':('Results · Team column','Team'),
 'round':('Results · Round heading','Round'),'map_max':('Results · Map maximum label','Map max:'),
 'raw':('Results · Raw score label','Raw'),'normalized':('Results · Normalized label','Norm.'),
 'total_time':('Results · Time column','Total\ntime\n(s)'),
 'final_percentage':('Results · Percentage column','Final\nscore\n(%)'),
 'final_total':('Results · Other calculation column','Total'),
 'pending':('Results · Missing total','Pending'),'empty_results':('Results · Empty message','No public results available.'),
}
COLORS={'ink':('Navy text','#122039'),'muted':('Secondary text','#526074'),
 'accent':('Red accent','#d24237'),'deadline':('Deadline / map maximum','#961f2b'),
 'link':('Results link','#467886'),'score_muted':('Raw scores & team details','#3d4a5c'),'table_border':('Table borders','#d9e0e8'),'line':('Rules','#dde2e8'),'table_header':('Round header','#ebf2fa'),
 'table_alternate':('Alternate rows','#f9fafc'),'cover_edge':('Diagonal edge','#e6eef0')}
IMAGE_SLOTS={'logo':'Competition logo','partner':'Federation / partner logo','cover':'Introduction scene image','qr':'QR image (optional replacement)'}

def values(competition,day,now):
    from django.conf import settings
    from django.utils import timezone
    venue,_,location=competition.location.partition(' · ')
    words=competition.league_name.split(' ',1)
    local=timezone.localtime(now)
    header=competition.header_title
    junior=header.lower().endswith('junior')
    organization=header[:-6].strip() if junior else header
    division='JUNIOR' if junior else ''
    league_display=('Junior ' if junior and not competition.league_name.lower().startswith('junior') else '')+competition.league_name
    return {'organization':organization,'division':division,'league_display':league_display,'competition_name':competition.name,'short_name':competition.short_name,'header_title':competition.header_title,
        'league_name':competition.league_name,'league_first':words[0].upper(),'league_rest':words[1].upper() if len(words)>1 else '',
        'venue':venue,'venue_location':location,'weekday':day.strftime('%A'),
        'date':day.strftime('%a %d %b %Y').upper(),'timezone':str(timezone.get_current_timezone()).split('/')[-1].replace('_',' '),
        'zone':timezone.make_aware(datetime.combine(day,time(12))).tzname(),
        'updated':local.strftime('%H:%M'),'results_address':settings.PUBLIC_ORIGIN.removeprefix('https://')+'/results'}

def resolve(template,context):
    for key,value in context.items():template=template.replace('{'+key+'}',str(value))
    return template


LEGACY_DEFAULTS={'brand_word':'RoboCup','title_small':'JUNIOR','schedule_subtitle':'Junior {league_name}'}

def automatic_text(design,key):
    default=TEXTS[key][1]
    if '{' not in default:return False
    if key in design.get('automatic',{}):return bool(design['automatic'][key])
    saved=design.get('texts',{}).get(key)
    return saved is None or saved==default or (key in LEGACY_DEFAULTS and saved==LEGACY_DEFAULTS[key])

def text_template(design,key):
    return TEXTS[key][1] if automatic_text(design,key) else design.get('texts',{}).get(key,TEXTS[key][1])


def challenge_context(challenge,round_count):
    return {'challenge':challenge.name if challenge else 'Competition results','round_count':round_count,
        'method':('Discard '+str(challenge.discard_count)+' · Normalized average' if challenge.calculation=='trimmed_mean' else challenge.get_calculation_display()) if challenge else ''}
