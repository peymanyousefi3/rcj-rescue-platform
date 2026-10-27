"""Field standings use exact ratios; persisted normalized values are a display cache."""
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction
from types import SimpleNamespace
from .models import Score, Team
from django.core.exceptions import ValidationError


def normalize_round(round_):
    scores=list(Score.objects.filter(round=round_).select_related('team'))
    participant_ids=set(Team.objects.participants(round_.challenge).filter(competition=round_.competition,active=True).values_list('pk',flat=True))
    values=[s.raw for s in scores if s.team_id in participant_ids and s.raw is not None]
    highest=max(values,default=Decimal(0))
    changed=[]
    for score in scores:
        if score.normalized_override: continue
        pending_zero=round_.challenge_id and round_.challenge.calculation=='trimmed_mean' and not highest and round_.zero_score_policy!='zero'
        value=None if score.raw is None or pending_zero else (score.raw/highest if highest else Decimal(0)).quantize(Decimal('.0001'),rounding=ROUND_HALF_UP)
        if value is not None and abs(value)>=Decimal('10000000000'): raise ValidationError('This raw score produces an out-of-range normalized result. Check the raw scores in this round.')
        if score.normalized!=value: score.normalized=value;changed.append(score)
    if changed: Score.objects.bulk_update(changed,['normalized'])


def display_value(value):
    if value is None: return None
    with localcontext() as context:
        context.prec=50
        return Decimal(value.numerator)/Decimal(value.denominator)


def field_round_state(round_,scores,team_ids):
    raw={team_id:scores[(team_id,round_.pk)].raw if (team_id,round_.pk) in scores else None for team_id in team_ids}
    values={team_id:None for team_id in team_ids}
    missing=any(value is None for value in raw.values())
    highest=max((value for value in raw.values() if value is not None),default=Decimal(0))
    issue='Awaiting raw field scores from every team.' if missing else ''
    excluded=False
    if any(value is not None and value<0 for value in raw.values()):
        issue='Negative field score: organizer correction required.'
    elif highest>0:
        values={team_id:Fraction(value)/Fraction(highest) if value is not None else None for team_id,value in raw.items()}
    elif not missing and raw:
        if round_.zero_score_policy=='exclude': excluded=True
        elif round_.zero_score_policy=='zero': values={team_id:Fraction(0) for team_id in team_ids}
        else: issue='All field scores are zero: organizer decision required.'
    return {'values':values,'issue':issue,'excluded':excluded}


def field_standings(rounds,teams,scores,challenge):
    """For each team independently, discard its lowest normalized round scores.

    Final percentage = 100 * sum(that team's remaining normalized scores)
    / number of that team's remaining rounds. Raw scores only establish each
    round's normalized ratios; they are never averaged into this final score.
    """
    team_ids=[team.pk for team in teams]
    states=[field_round_state(round_,scores,team_ids) for round_ in rounds]
    included=[i for i,state in enumerate(states) if not state['excluded']]
    ready=len(rounds)>=challenge.expected_rounds and len(included)>challenge.discard_count and not any(state['issue'] for state in states)
    rows=[]
    for team in teams:
        dropped=sorted(included,key=lambda i:(states[i]['values'][team.pk] or 0,i))[:challenge.discard_count] if ready else []
        retained=sorted((states[i]['values'][team.pk] for i in included if i not in dropped),reverse=True) if ready else []
        exact=100*sum(retained,Fraction(0))/len(retained) if ready else None
        cells=[SimpleNamespace(raw=scores[(team.pk,round_.pk)].raw if (team.pk,round_.pk) in scores else None,
            normalized=display_value(state['values'][team.pk]),discarded=i in dropped,excluded=state['excluded'],issue=state['issue'])
            for i,(round_,state) in enumerate(zip(rounds,states))]
        issue=next((state['issue'] for state in states if state['issue']),'')
        if not issue and len(included)<=challenge.discard_count: issue='At least one round must remain. Reduce the discard count or restore a round.'
        rows.append({'team':team,'cells':cells,'total':display_value(exact),'exact':exact,
            'tie_key':tuple(retained) if challenge.tie_break=='retained' else (),
            'dropped':[rounds[i].number for i in dropped],'rank':None,'issue':issue})
    return rows


def rank_standings(rows, *, released=True):
    if not released:
        for row in rows:
            row['rank']=None; row['tie']=False
        rows.sort(key=lambda row:row['team'].name)
        return rows
    rows.sort(key=lambda x:(x['total'] is None,-(x.get('exact',x['total']) or 0),tuple(-v for v in x.get('tie_key',())),x['team'].name))
    previous, rank = object(), None
    for index,row in enumerate(rows):
        if row['total'] is not None:
            ranking=(row.get('exact',row['total']),row.get('tie_key',()))
            if ranking != previous:
                rank = index + 1
            row['rank'] = rank
            previous = ranking
    for row in rows:
        row['tie']=row['rank'] is not None and sum(other['rank']==row['rank'] for other in rows)>1
    return rows
