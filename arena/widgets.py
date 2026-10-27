from django import forms


class TeamPicker(forms.CheckboxSelectMultiple):
    template_name='arena/widgets/team_picker.html'
    def create_option(self,name,value,label,selected,index,subindex=None,attrs=None):
        option=super().create_option(name,value,label,selected,index,subindex,attrs)
        team=getattr(value,'instance',None)
        if team is not None: option['attrs']['data-team-challenge']=str(team.superteam_challenge_id or '')
        return option


def recipient_data(args, competition):
    """Translate the single recipient picker into the existing access policy."""
    if not args or args[0] is None or not args[0].get('recipient_module'): return args
    from .models import Team, Challenge
    data=args[0].copy()
    selected=set(map(str,data.getlist('targets') if hasattr(data,'getlist') else data.get('targets',[])))
    challenge=Challenge.objects.filter(competition=competition,category='superteam',pk=data.get('challenge')).first() if data.get('form')=='quarantine' and str(data.get('challenge','')).isdigit() else None
    available=Team.objects.participants(challenge) if data.get('form')=='quarantine' else Team.objects.all()
    active=set(str(pk) for pk in available.filter(competition=competition,active=True).values_list('pk',flat=True))
    all_teams=bool(active) and selected==active
    public=bool(data.get('public_visibility'))
    data['general']=data['all_teams']='on' if all_teams else ''
    data['public']='on' if public else ''
    data['audience']=('public_all' if all_teams else 'public_selected' if selected else 'public') if public else ('all' if all_teams else 'selected')
    return (data,*args[1:])


def recipient_fields(form, public_label=None):
    if 'targets' not in form.fields: return
    flag=next((key for key in ['general','all_teams'] if key in form.fields),None)
    if not form.is_bound and flag and form[flag].value():
        form.initial['targets']=list(form.fields['targets'].queryset.values_list('pk',flat=True))
    form.fields['targets'].label='Recipients'
    form.fields['targets'].help_text='Select teams below. Only selected teams and administrators can access private content.'
    form.recipient_public_label=public_label
    form.recipient_public_checked=bool(form.data.get('public_visibility')) if form.is_bound and form.data.get('recipient_module') else bool(form['public'].value()) if 'public' in form.fields else False
    if not form.data.get('recipient_module') and 'audience' in form.fields:
        form.recipient_public_checked=str(form['audience'].value()).startswith('public')
    for key in ['general','all_teams','public','audience']:
        if key in form.fields: form.fields[key].widget=forms.HiddenInput()
