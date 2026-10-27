"""Framework-independent access and deadline policy, also exercised offline."""
PACKAGE_KINDS = frozenset(['tdp', 'video', 'code', 'bom', 'poster'])
ROUND_KINDS = frozenset(['round_file', 'round_code', 'round_json'])

def submission_open(*, now, opens_at, quarantine_at, completed=False, finished=False):
    return not completed and not finished and opens_at <= now < quarantine_at

def visible_to_public(*, kind, current, deleted, clean, approved, competition_finished,
                      archive_released, competition_ended, round_completed=False,
                      round_released=False, round_ended=False, general=False, public_copy=False):
    if deleted or not current or not clean or not approved:
        return False
    if kind in ROUND_KINDS:
        return False
    if kind == 'map':
        return round_completed and round_released
    if kind in PACKAGE_KINDS:
        return public_copy and competition_finished and archive_released and competition_ended
    return kind == 'resource' and public_copy

def best_six(values):
    """Workbook contract: 0 recorded, None pending; earliest tied minimum excluded."""
    if len(values) != 7 or any(v is None for v in values):
        return None, None
    drop = min(range(7), key=lambda i: (values[i], i))
    return sum(v for i, v in enumerate(values) if i != drop), drop + 1


def best_rounds(values, count):
    """Count the best configured scores once all active rounds have a score."""
    if not values or any(value is None for value in values):
        return None, []
    drop=sorted(range(len(values)),key=lambda i:(values[i],i))[:max(0,len(values)-count)]
    return sum(value for i,value in enumerate(values) if i not in drop), [i+1 for i in drop]


def challenge_total(values,method='sum',top_count=1,expected=1):
    if len(values)<expected or not values or any(value is None for value in values):
        return None,[]
    if method=='best': return best_rounds(values,top_count)
    total=sum(values)
    return (total/len(values) if method=='average' else total),[]
