from datetime import timedelta
from django.conf import settings
from django import forms
from .widgets import TeamPicker, recipient_data, recipient_fields
from django.contrib.auth.forms import PasswordResetForm
from django.template.loader import render_to_string
from django.utils import timezone
from .models import Asset, EmailConfiguration, EmailDelivery, Membership, Quarantine, Round, Team
from .policy import PACKAGE_KINDS, ROUND_KINDS

class QueuedPasswordResetForm(PasswordResetForm):
    def send_mail(self, subject_template_name, email_template_name, context, from_email,
                  to_email, html_email_template_name=None):
        import uuid
        membership = Membership.objects.filter(user=context['user']).first()
        EmailDelivery.objects.create(team=membership.team if membership else None,
            dedupe_key=f'password-reset:{uuid.uuid4()}', recipient=to_email,
            expires_at=timezone.now()+timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT),
            subject=''.join(render_to_string(subject_template_name, context).splitlines())[:200],
            body=render_to_string(email_template_name, context))

class AdminUploadForm(forms.Form):
    team = forms.ModelChoiceField(queryset=Team.objects.none(), required=False)
    kind = forms.ChoiceField(choices=[])
    round = forms.ModelChoiceField(queryset=Round.objects.none(), required=False)
    title = forms.CharField(max_length=180, required=False)
    file = forms.FileField()
    attested = forms.BooleanField(required=False, label='For round submissions: I confirm these are the files used for this round.')
    replacement = forms.ModelChoiceField(queryset=Asset.objects.none(),required=False,
        label='Replace an existing private file (optional)')
    def __init__(self, *args, competition=None, public_copy=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.public_copy = public_copy
        kinds = PACKAGE_KINDS | ({'resource'} if public_copy else {'round_file'})
        self.fields['kind'].choices = [pair for pair in Asset.KINDS if pair[0] in kinds]
        self.fields['team'].queryset = Team.objects.filter(competition=competition, active=True)
        self.fields['round'].queryset = Round.objects.filter(competition=competition,archived_at=None).select_related('challenge')
        self.fields['replacement'].queryset = Asset.objects.filter(competition=competition,
            public_copy=False,current=True,deleted_at=None,quarantine=None,kind__in=ROUND_KINDS | PACKAGE_KINDS)
        if public_copy:
            self.fields.pop('round')
            self.fields.pop('attested')
            self.fields.pop('replacement')
    def clean(self):
        d = super().clean()
        if d.get('kind') != 'resource' and not d.get('team'):
            self.add_error('team', 'Choose a team.')
        if d.get('kind') in ROUND_KINDS:
            if not d.get('round'):
                self.add_error('round', 'Choose a round.')
            if not d.get('attested'):
                self.add_error('attested', 'Confirm that the submission matches the round.')
        elif d.get('round'):
            self.add_error('round', 'Select a round only for round submissions.')
        if d.get('kind') == 'resource' and d.get('team'):
            self.add_error('team', 'Public resources are for everyone. Leave the team empty.')
        return d

class UploadForm(forms.Form):
    file = forms.FileField(label='Select file')
    attested = forms.BooleanField(required=False, label='I confirm these are the files used for this round.')

class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True

class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        if not data and not self.required: return []
        files = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleFileField, self).clean(file, initial) for file in files]

class QuarantineUploadForm(forms.Form):
    files = MultipleFileField(widget=MultipleFileInput, label='Files (any type)')
    replacement = forms.UUIDField(required=False, widget=forms.HiddenInput)

class SubmissionUploadForm(QuarantineUploadForm):
    attested = forms.BooleanField(required=False, label='I confirm these are the files used for this round.')

class AdminQuarantineUploadForm(QuarantineUploadForm):
    quarantine = forms.ModelChoiceField(queryset=Quarantine.objects.none())
    team = forms.ModelChoiceField(queryset=Team.objects.none())
    def __init__(self,*args,competition=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['quarantine'].queryset = Quarantine.objects.filter(competition=competition,archived_at=None)
        self.fields['team'].queryset = Team.objects.filter(competition=competition,active=True)
        self.fields['replacement'].label = 'Replace an existing file (optional; select one replacement file only)'
        self.fields['replacement'].widget = forms.Select(choices=[('','Add new files')]+[
            (str(asset.pk),f'{asset.team.code} / {asset.quarantine.name} / {asset.original_name}')
            for asset in Asset.objects.filter(competition=competition,kind='quarantine_file',
                current=True,deleted_at=None).select_related('team','quarantine')])

class QuarantineForm(forms.ModelForm):
    challenge = forms.ModelChoiceField(queryset=Team.objects.none(), required=False, label='SuperTeam challenge (optional)', help_text='Leave blank for individual teams. Select a SuperTeam challenge to request shared submissions from its paired teams.')
    targets = forms.ModelMultipleChoiceField(queryset=Team.objects.none(), required=False,
        label='Specific teams', widget=TeamPicker, help_text='Used when All teams is off. Individual deadlines can be set after saving.')
    class Meta:
        model = Quarantine
        fields = ['name','instructions','challenge','opens_at','deadline','all_teams','targets']
        widgets = {'opens_at':forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs={'type':'datetime-local'}), 'deadline':forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs={'type':'datetime-local'}),
            'instructions':forms.Textarea(attrs={'rows':3})}
        labels = {'opens_at':'Uploads open (optional, Toronto time)', 'deadline':'Default upload deadline (Toronto time)', 'all_teams':'All teams', 'round':'Related round (optional)'}
        help_texts = {'round':'For organization only. This quarantine uses its own deadline.',
            'deadline':'At this time, new files, replacements and deletions lock. Existing individual deadlines are shown below.'}
    def __init__(self,*args,competition=None,**kwargs):
        args=recipient_data(args,competition)
        super().__init__(*args,**kwargs)
        self.instance.competition = competition
        from .models import Challenge
        self.fields['challenge'].queryset=Challenge.objects.filter(competition=competition,category='superteam',archived_at=None)
        self.fields['targets'].queryset = Team.objects.filter(competition=competition,active=True)
        if self.instance.pk and not self.instance._state.adding:
            self.fields['targets'].initial = self.instance.team_deadlines.values_list('team_id',flat=True)
        recipient_fields(self)
    def clean(self):
        d = super().clean()
        if d.get('targets') and any(team.superteam_challenge_id!=(d['challenge'].pk if d.get('challenge') else None) for team in d['targets']):
            self.add_error('targets','Choose participants in the selected challenge only; leave the challenge blank for individual teams.')
        if not d.get('all_teams') and not d.get('targets'):
            self.add_error('targets','Select at least one team or choose All teams.')
        return d

class QuarantineDeadlineForm(forms.Form):
    deadline = forms.DateTimeField(required=False,
        widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs={'type':'datetime-local'}))

class EmailConfigurationForm(forms.ModelForm):
    provider = forms.ChoiceField(choices=[('gmail','Gmail / Google Workspace'),('smtp','Other email provider')],
        label='Send email through')
    password = forms.CharField(required=False, strip=False, label='SMTP password / app password',
        widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}),
        help_text='Stored encrypted. Leave blank to keep the saved password; it is never displayed.')
    clear_password = forms.BooleanField(required=False, label='Remove the saved SMTP password')
    class Meta:
        model = EmailConfiguration
        fields = ['provider','enabled','sender_name','sender_email','host','port','security','username','announcement_cc','announcement_bcc']
        widgets = {'announcement_cc':forms.Textarea(attrs={'rows':2}), 'announcement_bcc':forms.Textarea(attrs={'rows':2})}
        labels = {'announcement_cc':'Announcement CC addresses','announcement_bcc':'Announcement BCC addresses',
            'enabled':'Enable automatic email delivery','host':'SMTP server',
            'port':'SMTP port','security':'Connection security','username':'SMTP username'}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['provider'].initial='gmail' if self.instance.host=='smtp.gmail.com' else 'smtp'
        if self.is_bound and self.data.get('provider')=='gmail':
            self.data=self.data.copy()
            self.data.update(host='smtp.gmail.com',port=587,security='starttls',
                username=self.data.get('sender_email','').strip().lower())
        self.fields['sender_email'].help_text='For Gmail, enter the Google account address you will send from.'
    def clean(self):
        data = super().clean()
        if data.get('provider')=='gmail':
            password=''.join(data.get('password','').split())
            if password and (len(password)!=16 or not password.isascii() or not password.isalnum()):
                self.add_error('password','Enter the 16-character Google app password, not your Google account password.')
            else:
                data['password']=password
            if (self.instance.password_encrypted and not password and not data.get('clear_password') and
                    (self.instance.host!='smtp.gmail.com' or self.instance.username.lower()!=data.get('username','').lower())):
                self.add_error('password','Enter a new app password when changing the Google account.')
        from .mail import recipient_list
        for field in ['announcement_cc','announcement_bcc']:
            try: data[field]='\n'.join(recipient_list(data.get(field,'')))
            except forms.ValidationError: self.add_error(field,'Enter email addresses only, separated by commas or new lines.')
        for field in ['sender_name','host','username']:
            value=data.get(field,'')
            if '\n' in value or '\r' in value:
                self.add_error(field,'Enter a single line.')
        host=data.get('host','')
        if host and any(char in host for char in '/:@?# \\'):
            self.add_error('host','Enter a server hostname, without a URL, port or credentials.')
        if data.get('port') and not 1 <= data['port'] <= 65535:
            self.add_error('port','Enter a port from 1 to 65535.')
        if data.get('enabled'):
            for field in ['host','sender_email']:
                if not data.get(field):
                    self.add_error(field,'Required to enable delivery.')
            has_password=bool(data.get('password') or (self.instance.password_encrypted and not data.get('clear_password')))
            if data.get('username') and not has_password:
                self.add_error('password','Enter the SMTP password for this username.')
        return data
    def save(self, commit=True):
        from .mail import credential_cipher
        config=super().save(commit=False)
        config.pk=1
        if self.cleaned_data.get('clear_password'):
            config.password_encrypted=''
        if self.cleaned_data.get('password'):
            config.password_encrypted=credential_cipher().encrypt(self.cleaned_data['password'].encode()).decode()
        if commit:
            config.save()
        return config

class AnnouncementForm(forms.Form):
    title = forms.CharField(max_length=180)
    body = forms.CharField(max_length=12000, widget=forms.Textarea(attrs={'rows':6}), help_text='Use **text** for bold emphasis.')
    general = forms.BooleanField(required=False, initial=True, label='Send to all registered teams',
        help_text='Uncheck this to send only to the teams selected below.')
    public = forms.BooleanField(required=False, label='Also show on the main public homepage',
        help_text='Anyone can read the announcement when checked. Dashboard notices and emails go to the chosen teams.')
    targets = forms.ModelMultipleChoiceField(queryset=Team.objects.none(), required=False,
        label='Selected teams',widget=TeamPicker,
        help_text='Used only when Send to all registered teams is unchecked.')
    email_recipients = forms.CharField(required=False,max_length=12000,label='Additional email recipients',
        widget=forms.Textarea(attrs={'rows':3,'placeholder':'Mentor name <mentor@example.com>','spellcheck':'false'}),
        help_text='One address per line. Add a name as Name &lt;email&gt; for a personal greeting. These recipients receive email only; no account or private dashboard access is created.')
    def __init__(self, *args, competition=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['targets'].queryset = Team.objects.filter(competition=competition, active=True)
    def clean_email_recipients(self):
        from .mail import announcement_recipients
        return '\n'.join(f'{row["name"]} <{row["email"]}>' if row['name'] else row['email']
            for row in announcement_recipients(self.cleaned_data.get('email_recipients','')))
    def clean(self):
        data=super().clean()
        if not data.get('general') and not data.get('targets') and not data.get('public') and not data.get('email_recipients') and 'email_recipients' not in self.errors:
            self.add_error('targets','Select a team, add an email recipient, or publish on the homepage.')
        return data

class ResourceForm(forms.Form):
    title = forms.CharField(max_length=180)
    file = MultipleFileField(widget=MultipleFileInput, label='Files')
    general = forms.BooleanField(required=False, label='All teams')
    targets = forms.ModelMultipleChoiceField(queryset=Team.objects.none(), required=False, widget=TeamPicker)
    round = forms.ModelChoiceField(queryset=Round.objects.none(), required=False, label='Round (maps only)')
    kind = forms.ChoiceField(choices=[('resource','Team document'),('map','Round map')])
    def __init__(self, *args, competition=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['targets'].queryset = Team.objects.filter(competition=competition, active=True)
        self.fields['round'].queryset = Round.objects.filter(competition=competition,archived_at=None).select_related('challenge')
    def clean(self):
        d = super().clean()
        if d.get('kind') == 'map' and not d.get('round'):
            self.add_error('round','Choose the map’s round.')
        if d.get('kind') == 'resource' and not d.get('general') and not d.get('targets'):
            self.add_error('targets','Choose recipient teams or select all teams.')
        return d

class InviteForm(forms.Form):
    team = forms.ModelChoiceField(queryset=Team.objects.none())
    email = forms.EmailField(label='Team leader email', widget=forms.EmailInput(attrs={'autocomplete':'email'}))
    def __init__(self,*args,competition=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['team'].queryset = Team.objects.regular().filter(competition=competition, active=True, membership__isnull=True)

class PlaybackForm(forms.Form):
    round = forms.ModelChoiceField(queryset=Round.objects.none())
    playback_url = forms.URLField(max_length=1000, assume_scheme='https', label='Webots playback page URL', help_text='Public HTTPS page exported from the actual round recording, including its scene, animation and textures.')
    released = forms.BooleanField(required=False, label='Publish after this round is completed')
    def __init__(self,*args,competition=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['round'].queryset = Round.objects.filter(competition=competition,archived_at=None).select_related('challenge')
    def clean(self):
        data = super().clean()
        round_ = data.get('round')
        if round_ and data.get('playback_url'):
            round_.playback_url = data['playback_url']
            round_.clean()
            if data.get('released') and not round_.release_ready:
                raise forms.ValidationError('Mark this round as completed before publishing its playback.')
        return data
