"""Rounds own their existing programme runs; calendar edits are atomic and private."""
import hashlib
import json
import uuid
from datetime import timedelta, datetime
from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from .models import Asset, Programme, Round, Team
from .widgets import TeamPicker


def round_runs(round_):
    if not round_.pk: return Programme.objects.none()
    return Programme.objects.filter(round=round_, competition=round_.competition, archived_at=None, team__isnull=False).select_related('team').order_by('starts_at','pk')


def revision(item):
    data=[(field.attname,getattr(item,field.attname).timestamp() if isinstance(getattr(item,field.attname),datetime) else str(getattr(item,field.attname))) for field in item._meta.concrete_fields]
    if isinstance(item,Round):
        data += sorted(str(pk) for pk in item.map_targets.values_list('pk',flat=True)) if item.pk else []
        data += list(Asset.objects.filter(round=item,kind='map').values_list('pk','current','deleted_at','public_approved')) if item.pk else []
        data += list(round_runs(item).values_list('pk','team_id','starts_at','ends_at','field','confirmed'))
    return hashlib.sha256(json.dumps(data,default=str).encode()).hexdigest()


def lineup_data(round_):
    if not round_.pk:
        return [{'team':str(team.pk),'duration':15,'gap':0,'field':'','confirmed':True} for team in Team.objects.participants(round_.challenge).filter(competition=round_.competition,active=True).order_by('name')]
    previous=round_.starts_at
    rows=[]
    for run in round_runs(round_):
        rows.append({'id':run.pk,'team':str(run.team_id),'duration':(run.ends_at-run.starts_at).total_seconds()/60,
            'gap':(run.starts_at-previous).total_seconds()/60,'field':run.field,'confirmed':run.confirmed})
        previous=run.ends_at
    return rows


class LineupForm(forms.Form):
    revision=forms.CharField(max_length=64,required=False,widget=forms.HiddenInput)
    lineup=forms.JSONField(widget=forms.HiddenInput,required=False)
    teams=forms.ModelMultipleChoiceField(queryset=Team.objects.none(),required=False,widget=TeamPicker,label="Teams in this round")
    def __init__(self,*args,round_,**kwargs):
        self.round=round_
        super().__init__(*args,**kwargs)
        self.fields['teams'].queryset=Team.objects.filter(competition=round_.competition).filter(Q(active=True)|Q(programme__round_id=round_.pk,programme__archived_at=None) if round_.pk else Q(active=True)).distinct()
        if not self.is_bound: self.initial['teams']=[row['team'] for row in lineup_data(round_)]
        if not self.is_bound: self.initial.update(revision=revision(round_) if round_.pk else '',lineup=lineup_data(round_))
    def clean_lineup(self):
        rows=self.cleaned_data.get('lineup') or []
        if not rows: raise forms.ValidationError('Choose at least one participating team.')
        if not isinstance(rows,list) or len(rows)>1000: raise forms.ValidationError('Choose a valid team lineup.')
        teams={str(t.pk) for t in Team.objects.participants(self.round.challenge).filter(competition=self.round.competition,active=True)}
        existing={r.pk:r for r in round_runs(self.round)}
        seen=set();ids=set();finish=0
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('team'),str) or row.get('team') in seen: raise forms.ValidationError('Each team may appear once in a round.')
            if row.get('team') not in teams:
                raise forms.ValidationError('Choose teams from this competition.')
            seen.add(row['team'])
            pk=row.get('id')
            if pk is not None and (type(pk) is not int or pk not in existing or str(existing[pk].team_id)!=row['team'] or pk in ids):
                raise forms.ValidationError('The lineup changed. Reload this round and try again.')
            ids.add(pk)
            for key,minimum in [('duration',0.01),('gap',0)]:
                try: value=forms.DecimalField(min_value=minimum,max_value=10080,decimal_places=4).clean(row.get(key,0))
                except ValidationError: raise forms.ValidationError('Use valid minutes for every run and gap.')
                row[key]=float(value)
            if not isinstance(row.get('field',''),str) or len(row.get('field',''))>30:
                raise forms.ValidationError('Use a location of at most 30 characters.')
            if not isinstance(row.get('confirmed',True),bool): raise forms.ValidationError('Choose a valid confirmation status.')
            start=finish+row['gap'];finish=start+row['duration']
            if start<0 or finish>10080:
                raise forms.ValidationError('Keep one round within seven days.')
        return rows
    def save(self,user,*,round_=None,verify=True):
        from .services import audit
        # Caller holds the competition lock, shared with workbook and calendar edits.
        round_=round_ or Round.objects.select_for_update().get(pk=self.round.pk)
        if verify and self.cleaned_data.get('revision') and self.cleaned_data['revision']!=revision(round_):
            raise ValidationError('This round changed in another window. Reload it before saving the lineup.')
        if round_.archived_at or round_.challenge_id and round_.challenge.archived_at:
            raise ValidationError('Restore this round and challenge before changing its lineup.')
        rows=self.cleaned_data['lineup'];kept=[];previous=round_.starts_at
        existing={r.pk:r for r in round_runs(round_)}
        for row in rows:
            run=existing.get(row.get('id')) or Programme(competition=round_.competition,round=round_,team_id=row['team'],source_key='manual:'+uuid.uuid4().hex,title=str(round_))
            run.starts_at=previous+timedelta(minutes=row['gap']);run.ends_at=run.starts_at+timedelta(minutes=row['duration'])
            run.field=row.get('field','');run.confirmed=row.get('confirmed',True)
            run.full_clean();run.save();kept.append(run.pk);previous=run.ends_at
        # Keep removed runs and all their historical references, rather than deleting rows.
        round_runs(round_).exclude(pk__in=kept).update(archived_at=timezone.now())
        round_.ends_at=previous;round_.save(update_fields=['ends_at'])
        audit(user,'round.lineup_updated',object_id=round_.pk,detail={'run_ids':kept})


def move_round_runs(round_,old_start):
    delta=round_.starts_at-old_start
    runs=list(round_runs(round_))
    if any(run.ends_at+delta>round_.ends_at for run in runs):
        raise ValidationError('The team runs do not fit in this duration. Adjust the lineup before shortening the round.')
    for run in runs:
        run.starts_at+=delta;run.ends_at+=delta
    Programme.objects.bulk_update(runs,['starts_at','ends_at'])


def calendar_entries(competition):
    entries=[]
    rounds=Round.objects.filter(competition=competition,archived_at=None).filter(Q(challenge=None)|Q(challenge__archived_at=None)).select_related('challenge')
    events=Programme.objects.filter(competition=competition,round=None,archived_at=None)
    for kind,items in [('round',rounds),('event',events)]:
        for item in items:
            entries.append({'id':f'{kind}:{item.pk}','title':str(item)+(f' · {item.name}' if item.name else '') if kind=='round' else item.title,
                'start':timezone.localtime(item.starts_at).strftime('%Y-%m-%dT%H:%M:%S'),
                'end':timezone.localtime(item.ends_at).strftime('%Y-%m-%dT%H:%M:%S'),
                'durationEditable':kind!='round', 'classNames':['calendar-'+kind], 'extendedProps':{'kind':kind,'pk':item.pk,'revision':revision(item),
                    'editUrl':f'/control/?{kind}={item.pk}#{"round" if kind=="round" else "event"}-editor-{item.pk}'}})
    return entries
