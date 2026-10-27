"""Strict adapter for the organizer's ASR Rescue Simulation workbook.

Reads cached results without executing formulas or following hyperlinks. Validates the
whole snapshot before applying it. Never replaces last known good data after an error.
"""
import datetime as dt
import io
import re
import zipfile
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook
from .models import Challenge, Competition, Programme, Round, Score, Team

TORONTO = ZoneInfo('America/Toronto')

def text(value):
    return str(value or '').strip()

def clock(value):
    if isinstance(value,dt.datetime): return value.time()
    if isinstance(value,dt.time): return value
    try: return dt.time.fromisoformat(text(value))
    except ValueError: return None

def number(value):
    if value is None or value == '': return None
    if isinstance(value,bool): raise ValidationError('Boolean in score cell.')
    try:
        value = Decimal(str(value))
        if not value.is_finite() or abs(value) >= Decimal('10000000000'):
            raise InvalidOperation()
        return value
    except InvalidOperation as exc:
        raise ValidationError('Invalid score cell; last good results retained.') from exc

def inspect_xlsx(content):
    if len(content) > 10*1024*1024:
        raise ValidationError('Workbook exceeds the 10 MiB import limit.')
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        if len(z.infolist()) > 500 or sum(f.file_size for f in z.infolist()) > 40*1024*1024:
            raise ValidationError('Workbook expands beyond the safe import limit.')
        if any('vbaproject' in f.filename.lower() for f in z.infolist()):
            raise ValidationError('Macro-enabled workbooks are not accepted.')
    return load_workbook(io.BytesIO(content), read_only=True, data_only=True, keep_links=False)

def parse_workbook(content, year=2026):
    workbook = inspect_xlsx(content)
    try:
        sheets=[]
        for sheet in workbook.worksheets:
            values=list(sheet.values)
            width=max((len(row) for row in values),default=0)
            # Some organizer files omit worksheet dimensions; read-only rows are ragged.
            sheets.append((sheet.title,[tuple(row)+(None,)*(width-len(row)) for row in values]))
        candidates = [(name,rows) for name,rows in sheets if any(
            any('Teams and best-six totals' in text(v) for v in row) for row in rows)]
        if len(candidates)!=1:
            raise ValidationError('Expected exactly one ASR schedule sheet with Teams and best-six totals.')
        _,rows = candidates[0]
        header = next((i for i,row in enumerate(rows) if 'Team name' in [text(v) for v in row] and 'Code' in [text(v) for v in row]),None)
        if header is None: raise ValidationError('Team roster headers changed.')
        values=[text(v) for v in rows[header]]
        columns={label:values.index(label) for label in ['Team name','Code','Country','School']}
        teams=[]
        for row in rows[header+1:]:
            code=text(row[columns['Code']])
            if not code: continue
            if not re.fullmatch(r'\d{3}[A-Z]{2}',code):
                raise ValidationError('Unexpected team code in roster.')
            teams.append({key: text(row[col]) for key,col in columns.items()})
        if len({t['Code'] for t in teams})!=len(teams) or not teams:
            raise ValidationError('Missing or duplicated roster codes.')
        codes={t['Code'] for t in teams}
        time_header=next((i for i,row in enumerate(rows) if sum(text(v)=='Time' for v in row)>=4),None)
        if time_header is None: raise ValidationError('Four-day timetable headers changed.')
        time_cols=[i for i,v in enumerate(rows[time_header]) if text(v)=='Time']
        entries=[]
        round_info={}
        for col in time_cols:
            date_text=text(rows[time_header-2][col])
            try: date=dt.datetime.strptime(f'{date_text} {year}','%d %B %Y').date()
            except ValueError as exc: raise ValidationError('Unrecognized programme date.') from exc
            active_round=None
            cutoff=None
            for row_index,row in enumerate(rows[time_header+1:header],start=time_header+1):
                t=clock(row[col])
                if t is None: continue
                starts=dt.datetime.combine(date,t,TORONTO)
                label=text(row[col+1]).replace('\n',' ')
                code=text(row[col+2]) if col+2<len(row) else ''
                if label.lower()=='quarantine due':
                    cutoff=starts
                    active_round=None
                match=re.fullmatch(r'R([1-7])',label)
                if match:
                    active_round=int(match.group(1))
                    if not cutoff or cutoff>=starts: raise ValidationError('Round has no preceding quarantine time.')
                    round_info[active_round]={'number':active_round,'starts_at':starts,'quarantine_at':cutoff,'ends_at':starts}
                if code in codes and active_round:
                    end=starts+dt.timedelta(minutes=15)
                    round_info[active_round]['ends_at']=max(round_info[active_round]['ends_at'],end)
                    entries.append({'source_key':f'asr26:{date}:{t}:{code}','title':f'Round {active_round}',
                        'starts_at':starts,'ends_at':end,'team_code':code,'round_number':active_round,'confirmed':True})
                elif label and not match:
                    active_round=None
                    duration=15
                    # Merged programme cells expose their actual duration. Fallback is one slot.
                    below=[]
                    for nxt in rows[row_index+1:header]:
                        nt=clock(nxt[col])
                        if nt and text(nxt[col+1]):
                            below.append(dt.datetime.combine(date,nt,TORONTO));break
                    end=below[0] if below else starts+dt.timedelta(minutes=duration)
                    # Quarantine is an explicit deadline marker, not a long-running event.
                    if label.lower()=='quarantine due': end=starts+dt.timedelta(minutes=15)
                    entries.append({'source_key':f'asr26:{date}:{t}:programme','title':label.replace('(TBC)','').strip(),
                        'starts_at':starts,'ends_at':end,'team_code':None,'round_number':None,'confirmed':'TBC' not in label})
        if set(round_info)!=set(range(1,8)):
            raise ValidationError('Expected seven rounds. No timetable changes applied.')
        for item in round_info.values():
            item['opens_at']=dt.datetime.combine(item['starts_at'].date(),dt.time(8,30),TORONTO)
        # Score inputs are the authoritative fixed-order raw and normalized tables.
        source=next((rows for _,rows in sheets if any('Score inputs' in text(v) for v in rows[0])),None)
        if source is None: raise ValidationError('Score inputs sheet not found.')
        mode=next((text(row[1]) for row in source if text(row[0])=='Mode'),None)
        if mode not in ['Sample','Live']: raise ValidationError('Score mode must be Sample or Live.')
        raw_header=next((i for i,row in enumerate(source) if 'R1 raw' in [text(v) for v in row]),None)
        norm_header=next((i for i,row in enumerate(source) if 'R1 norm.' in [text(v) for v in row]),None)
        if raw_header is None or norm_header is None: raise ValidationError('Score table headers changed.')
        scores=[]
        raw_rows={text(r[0]):r for r in source[raw_header+1:norm_header] if text(r[0]) in codes}
        norm_rows={text(r[0]):r for r in source[norm_header+1:] if text(r[0]) in codes}
        for code,row in raw_rows.items():
            if code not in norm_rows: raise ValidationError('Normalized team row is missing.')
            for n in range(1,8):
                raw=number(row[n+1]) if mode=='Live' else None
                norm=number(norm_rows[code][n+1]) if mode=='Live' else None
                if raw is None and norm is not None: raise ValidationError('Normalized score without a raw score.')
                scores.append({'code':code,'round_number':n,'raw':raw,'normalized':norm})
        return {'teams':teams,'rounds':list(round_info.values()),'events':entries,'scores':scores,'mode':mode}
    finally:
        workbook.close()

@transaction.atomic
def apply_snapshot(snapshot,digest,competition,*,allow_initial_deadlines=False):
    competition=Competition.objects.select_for_update(no_key=True).get(pk=competition.pk)
    if not competition.workbook_enabled:
        raise ValidationError('Workbook updates were paused; administrator edits are preserved.')
    team_map={}
    scheduled_codes={e['team_code'] for e in snapshot['events'] if e['team_code']}
    for t in snapshot['teams']:
        team,created=Team.objects.get_or_create(code=t['Code'],defaults={'competition':competition,
            'name':t['Team name'],'country':t['Country'],'school':t['School']})
        if team.competition_id!=competition.pk: raise ValidationError('Team code belongs to another competition.')
        team.name,team.country,team.school=t['Team name'],t['Country'],t['School']
        team.scheduled=team.code in scheduled_codes
        team.save(update_fields=['name','country','school','scheduled'])
        team_map[team.code]=team
    round_map={}
    challenge,_=Challenge.objects.get_or_create(competition=competition,primary=True,
        defaults={'name':'Main competition','category':'main','expected_rounds':len(snapshot['rounds']),
            'calculation':'trimmed_mean','discard_count':max(0,len(snapshot['rounds'])-competition.counted_rounds),'top_count':competition.counted_rounds})
    if challenge.archived_at:
        raise ValidationError('The workbook challenge was removed; restore it before importing.')
    for value in snapshot['rounds']:
        r=Round.objects.select_for_update().filter(competition=competition,challenge=challenge,number=value['number']).first()
        if r:
            # The sheet defines run/deadline times, not when submission slots open.
            value={**value,'opens_at':r.opens_at}
        if r and r.quarantine_at<=timezone.now() and any(getattr(r,k)!=value[k] for k in ['opens_at','quarantine_at']):
            raise ValidationError('A locked round deadline changed in the workbook. Administrator review required.')
        if not r and value['quarantine_at']<=timezone.now() and not allow_initial_deadlines:
            raise ValidationError('Initial import contains past deadlines; explicit initial-import flag required.')
        if r:
            for k,v in value.items(): setattr(r,k,v)
            r.full_clean();r.save()
        else:
            r=Round(competition=competition,challenge=challenge,**value);r.full_clean();r.save()
        round_map[r.number]=r
    keys=[]
    for value in snapshot['events']:
        v=dict(value); code=v.pop('team_code');rn=v.pop('round_number');key=v.pop('source_key')
        keys.append(key)
        Programme.objects.update_or_create(source_key=key,defaults={**v,'competition':competition,
            'team':team_map.get(code),'round':round_map.get(rn),'field':'A' if rn else ''})
    Programme.objects.filter(competition=competition,source_key__startswith='asr26:').exclude(source_key__in=keys).delete()
    for score in snapshot['scores']:
        Score.objects.update_or_create(team=team_map[score['code']],round=round_map[score['round_number']],
            defaults={'raw':score['raw'],'normalized':score['normalized'],'normalized_override':False})
    competition.workbook_last_synced=timezone.now()
    competition.workbook_digest=digest
    competition.save(update_fields=['workbook_last_synced','workbook_digest'])
    return len(keys)
