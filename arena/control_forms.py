"""Organizer forms for editable competition records; no seeded entries are fixed."""
from pathlib import PurePath
from datetime import timedelta,datetime,time
from django import forms
from django.conf import settings
from django.utils.html import format_html
from .widgets import TeamPicker, recipient_data, recipient_fields
from django.contrib.auth import get_user_model
from django.utils import timezone
from .forms import AnnouncementForm, MultipleFileField, MultipleFileInput
from .models import Asset, Challenge, Competition, FileShare, Programme, Quarantine, Round, Team
from .policy import PACKAGE_KINDS, ROUND_KINDS

DATETIME = {'type':'datetime-local'}

def local_times(form, names):
    for name in names:
        form.fields[name].widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs=DATETIME)

class TeamForm(forms.ModelForm):
    username=forms.CharField(max_length=150,required=False,label='Account username')
    create_account=forms.BooleanField(required=False,label='Create a leader account and email a password setup link')
    class Meta:
        model=Team
        fields=['code','name','country','school','leader_email','active']
        labels={'code':'Team code','leader_email':'Leader email','active':'Team is active'}
    def __init__(self,*args,competition=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.instance.competition=competition
        self.account=self.instance.membership_set.select_related('user').first() if self.instance.pk else None
        if self.account:
            self.fields['username'].initial=self.account.user.username
            self.fields.pop('create_account')
        self.fields['username'].help_text='Leave blank for a new team to use its team code.'
    def clean_username(self):
        value=self.cleaned_data.get('username','').strip()
        if value:
            get_user_model()._meta.get_field('username').run_validators(value)
            others=get_user_model().objects.filter(username=value)
            if self.account: others=others.exclude(pk=self.account.user_id)
            if others.exists(): raise forms.ValidationError('This username is already in use.')
        elif self.account:
            value=self.account.user.username
        return value
    def clean(self):
        data=super().clean()
        if data.get('create_account') and (not data.get('leader_email') or not data.get('active')):
            raise forms.ValidationError('An active team and leader email are required to create an account.')
        return data

class TimeRangeMixin:
    def time_fields(self):
        local_times(self,['starts_at','ends_at'])
        if self.instance.pk:
            from .scheduling import revision
            self.fields['revision'].initial=revision(self.instance)
        self.fields['ends_at'].required=False
        self.fields['end_mode'].initial='duration'
        if self.instance.pk:
            self.fields['duration_minutes'].initial=self.instance.duration_minutes
    def clean(self):
        data=super().clean()
        start=data.get('starts_at');end=data.get('ends_at')
        if data.get('end_mode')=='duration':
            if start and data.get('duration_minutes'):
                end=data['ends_at']=start+timedelta(minutes=data['duration_minutes'])
            else: self.add_error('duration_minutes','Enter the duration in minutes.')
        if not end and not self.errors.get('duration_minutes'):
            self.add_error('ends_at','Enter an end time or choose a duration.')
        if start and end and end<=start: self.add_error('ends_at','The end must follow the start.')
        return data

class RoundForm(forms.ModelForm):
    field_files=MultipleFileField(required=False,widget=MultipleFileInput(attrs={'webkitdirectory':True,'data-field-folder':''}),label='Field folder')
    field_paths=forms.JSONField(required=False,widget=forms.HiddenInput)
    field_choices=forms.JSONField(required=False,widget=forms.HiddenInput)
    targets=forms.ModelMultipleChoiceField(queryset=Team.objects.none(),required=False,widget=TeamPicker,label='Field recipients')
    general=forms.BooleanField(required=False,widget=forms.HiddenInput)
    public=forms.BooleanField(required=False,widget=forms.HiddenInput)
    wbt=forms.FileField(required=False,label='Webots world · WBT')
    map_json=forms.FileField(required=False,label='Controller / map JSON')
    info_json=forms.FileField(required=False,label='Field information · JSON')
    glb=forms.FileField(required=False,label='3D field model · GLB')
    jpeg=forms.FileField(required=False,label='Field thumbnail · Image',widget=forms.FileInput(attrs={'accept':'image/*'}))
    revision=forms.CharField(required=False,widget=forms.HiddenInput)
    class Meta:
        model=Round
        fields=['challenge','number','name','starts_at','completed','zero_score_policy','maps_released']
        labels={'number':'Round number','name':'Round or event title','starts_at':'Round starts · Toronto',
            'completed':'Round completed','maps_released':'Release approved maps'}
    def __init__(self,*args,competition=None,**kwargs):
        from .scheduling import LineupForm,revision
        args=recipient_data(args,competition)
        super().__init__(*args,**kwargs);self.instance.competition=competition
        self.fields['targets'].queryset=Team.objects.filter(competition=competition,active=True)
        if not self.is_bound:
            self.initial.update(general=self.instance.map_general,public=self.instance.map_public,targets=list(self.instance.map_targets.all()) if self.instance.pk else [])
        recipient_fields(self,'Publish released field files on the website')
        self.fields['maps_released'].label='Release field package'
        self.fields['completed'].help_text='Mark when the teams have finished, even if the scheduled end time is later.'
        self.fields['maps_released'].help_text='Requires Round completed. Release clean, approved files immediately to the recipients below, including when the round finishes early.'
        self.map_assets=Asset.objects.filter(round=self.instance,kind='map').order_by('-created_at') if self.instance.pk else Asset.objects.none()
        self.fields['challenge'].queryset=Challenge.objects.filter(competition=competition,archived_at=None)
        self.fields['challenge'].initial=competition.challenge_set.filter(primary=True,archived_at=None).first()
        local_times(self,['starts_at'])
        self.fields['starts_at'].initial=competition.starts_at
        self.fields['name'].required=False
        self.fields['zero_score_policy'].required=False
        self.fields['zero_score_policy'].label='If every field score is zero'
        self.fields['zero_score_policy'].help_text='Only used by Average after discards. No result is assigned until you decide. An exclusion applies equally to every team.'
        self.fields['revision'].initial=revision(self.instance) if self.instance.pk else ''
        if self.is_bound:
            selected=self.fields['challenge'].queryset.filter(pk=self.data.get('challenge')).first() if str(self.data.get('challenge','')).isdigit() else None
            self.instance.challenge=selected or competition.challenge_set.filter(primary=True,archived_at=None).first()
        if not self.is_bound and not self.instance.pk and self.initial.get('challenge'):
            self.instance.challenge=self.fields['challenge'].queryset.filter(pk=self.initial['challenge']).first()
        self.lineup_form=LineupForm(self.data if self.is_bound and 'lineup-lineup' in self.data else None,round_=self.instance,prefix='lineup')
    def clean(self):
        from .scheduling import LineupForm
        import json
        data=super().clean();challenge=data.get('challenge')
        data['zero_score_policy']=data.get('zero_score_policy') or self.instance.zero_score_policy
        from .fields import ROLES,validate_field,detect_package
        if data.get('field_files'):
            if any(data.get(role) for role in ROLES): self.add_error('field_files','Choose a folder or individual replacement files, not both.')
            else:
                try: data.update(detect_package(data['field_files'],data.get('field_paths'),data.get('field_choices')))
                except forms.ValidationError as exc: self.add_error('field_files',exc)
        self.map_metadata={}
        for role in ROLES:
            if data.get(role):
                try: self.map_metadata[role]=validate_field(data[role],role)
                except forms.ValidationError as exc: self.add_error(role,exc)
        if 'recipient_module' in self.data:
            self.instance.map_general=bool(data.get('general'));self.instance.map_public=bool(data.get('public'))
        if challenge is None: challenge=data['challenge']=self.instance.competition.challenge_set.filter(primary=True,archived_at=None).first()
        number=data.get('number')
        if number is not None:
            if number<1: self.add_error('number','Use a round number of at least 1.')
            elif Round.objects.filter(competition=self.instance.competition,challenge=challenge,number=number).exclude(pk=self.instance.pk).exists():
                self.add_error('number','This number already exists in this challenge. Edit or restore that round.')
        if not self.lineup_form.is_bound:
            self.lineup_form=LineupForm({'lineup-lineup':json.dumps(self.lineup_form.initial['lineup']),
                'lineup-revision':self.lineup_form.initial['revision']},round_=self.instance,prefix='lineup')
        if not self.lineup_form.is_valid(): self.add_error(None,'Check the participating teams and run times below.')
        elif data.get('starts_at'):
            minutes=sum(row['gap']+row['duration'] for row in self.lineup_form.cleaned_data['lineup'])
            self.instance.ends_at=data['ends_at']=data['starts_at']+timedelta(minutes=minutes)
        if self.instance._state.adding and data.get('starts_at'):
            self.instance.opens_at=data['starts_at'];self.instance.quarantine_at=data['starts_at']+timedelta(seconds=1)
            self.instance.submissions_enabled=False
        if data.get('maps_released') and not data.get('completed'):
            self.add_error('maps_released','Mark Round completed when the teams have finished, then release the field package.')
        return data

class RoundWindowForm(forms.ModelForm):
    class Meta:
        model=Round
        fields=['submissions_enabled','opens_at','quarantine_at']
        labels={'submissions_enabled':'Enable participant uploads','opens_at':'Uploads open (Toronto time)','quarantine_at':'Upload deadline (Toronto time)'}
    def __init__(self,*args,competition=None,**kwargs):
        super().__init__(*args,**kwargs);local_times(self,['opens_at','quarantine_at'])
    def clean(self):
        data=super().clean()
        if data.get('opens_at') and data.get('quarantine_at') and data['opens_at']>=data['quarantine_at']:
            self.add_error('quarantine_at','The deadline must follow the opening time.')
        return data

class ChallengeForm(forms.ModelForm):
    class Meta:
        model=Challenge
        fields=['name','category','expected_rounds','calculation','discard_count','tie_break','top_count','score_source']
        labels={'expected_rounds':'Planned number of rounds','calculation':'Score calculation','top_count':'Number of top scores counted','score_source':'Score values to use','discard_count':'Lowest normalized scores discarded per team'}
        help_texts={'expected_rounds':'Standings remain pending until this many active rounds have scores. Add the rounds in Rounds & archive.',
            'top_count':'Used only for Best scores.',
            'discard_count':'Apply this count separately to each team: discard its own lowest normalized round scores. Different teams can discard different rounds. At least one round must remain.',
            'tie_break':'Shared rank is the default. Highest retained round scores compares the best retained normalized score, then the next best.',
            'calculation':'For each team, discard its lowest normalized round scores, average only its remaining normalized scores, then multiply by 100. Normalize each round first: raw field score divided by that round’s highest raw field score.',
            'score_source':'Used by Sum, Average and Best scores. Average after discards always averages the remaining normalized scores, calculated separately for each team.'}
    def __init__(self,*args,competition=None,**kwargs):
        super().__init__(*args,**kwargs);self.instance.competition=competition
        self.fields['discard_count'].required=False
        self.fields['tie_break'].required=False
    def clean(self):
        data=super().clean()
        if self.instance.pk and self.instance.superteams.exists() and data.get('category')!='superteam':
            self.add_error('category','This challenge has SuperTeams. Keep its SuperTeam category to preserve their profiles and results.')
        data['discard_count']=data.get('discard_count') if data.get('discard_count') is not None else self.instance.discard_count
        data['tie_break']=data.get('tie_break') or self.instance.tie_break
        if data.get('calculation')=='trimmed_mean': data['score_source']='normalized'
        for key in ['expected_rounds','top_count']:
            if data.get(key) is not None and data[key]<1: self.add_error(key,'Enter at least 1.')
        if data.get('calculation')=='best' and data.get('top_count',0)>data.get('expected_rounds',0):
            self.add_error('top_count','Choose no more than the planned number of rounds.')
        return data

class CompetitionForm(forms.ModelForm):
    logo=forms.FileField(required=False,label='Competition logo',help_text='Public image. Upload a raster image; the server removes metadata and stores a PNG.')
    remove_logo=forms.BooleanField(required=False,label='Use the default competition logo')
    partner_logo=forms.FileField(required=False,label='Partner / federation logo',help_text='Optional public image displayed beside the event identity.')
    remove_partner_logo=forms.BooleanField(required=False,label='Remove the partner logo')
    banner_image=forms.FileField(required=False,label='Homepage banner image',help_text='Optional public image on the right side of the navy banner. The title remains readable on the left.')
    remove_banner_image=forms.BooleanField(required=False,label='Use the default banner image')

    first_day=forms.DateField(widget=forms.DateInput(attrs={'type':'date'}),label='First competition day')
    last_day=forms.DateField(widget=forms.DateInput(attrs={'type':'date'}),label='Last competition day')
    class Meta:
        model=Competition
        fields=['name','short_name','header_title','league_name','location','banner_title','banner_subtitle','first_day','last_day','phase','workbook_enabled']
        labels={'name':'Full competition name','short_name':'Short event name','header_title':'Header heading','league_name':'League name','banner_title':'Homepage banner title','banner_subtitle':'Homepage banner subtitle','workbook_enabled':'Import teams, programme and scores from the linked workbook'}
        help_texts={'workbook_enabled':'Manual edits pause workbook updates to preserve your changes.'}
    def __init__(self,*args,**kwargs):
        # Existing open settings forms retain new branding values when submitted after an upgrade.
        if args and args[0] is not None:
            data=args[0].copy();instance=kwargs.get('instance')
            for name in ['short_name','header_title','league_name','banner_title','banner_subtitle']:
                if name not in data:data[name]=getattr(instance,name,'')
            args=(data,*args[1:])
        super().__init__(*args,**kwargs)
        from .branding import branding_urls
        previews=branding_urls(self.instance)
        self.branding_cards=[]
        for field,slot,title in [('logo','logo','Competition logo'),('partner_logo','partner','Partner / federation logo'),('banner_image','banner','Homepage banner image')]:
            self.fields[field].label='Replace image (optional)' if previews[slot] else 'Upload image (optional)'
            self.fields[field].help_text=('Leave this empty to keep the image shown above.' if previews[slot] else 'No image is set. Choose a file to display one.')+' Uploads are safely stored as PNG.'
            self.fields[field].widget.attrs['accept']='image/*'
            self.branding_cards.append({'title':title,'slot':slot,'url':previews[slot],'field':self[field],'reset':self['remove_'+field]})
        self.original_start=self.instance.starts_at;self.original_end=self.instance.ends_at
        self.fields['first_day'].initial=timezone.localtime(self.original_start).date()
        self.fields['last_day'].initial=timezone.localtime(self.original_end-timedelta(microseconds=1)).date() if timezone.localtime(self.original_end).time()==time() else timezone.localtime(self.original_end).date()
    def clean(self):
        d=super().clean();first=d.get('first_day');last=d.get('last_day')
        from .branding import normalize_image
        self.branding_images={}
        for field in ['logo','partner_logo','banner_image']:
            if d.get(field):
                if d.get('remove_'+field):self.add_error(field,'Choose a replacement image or select removal, not both.')
                else:
                    try:self.branding_images[field]=normalize_image(d[field])
                    except forms.ValidationError as exc:self.add_error(field,exc)

        if first and last:
            if last<first: self.add_error('last_day','The last day must be on or after the first day.')
            else:
                if first!=self.fields['first_day'].initial: self.instance.starts_at=timezone.make_aware(datetime.combine(first,time()))
                if last!=self.fields['last_day'].initial: self.instance.ends_at=timezone.make_aware(datetime.combine(last+timedelta(days=1),time()))
        return d

    def save(self,commit=True):
        instance=super().save(commit=False)
        self.branding_created=[]
        from .branding import store_image
        slots={'logo':'logo_key','partner_logo':'partner_logo_key','banner_image':'banner_key'}
        try:
            for field,key in slots.items():
                if field in self.branding_images:
                    value=store_image(instance,self.branding_images[field]);self.branding_created.append(value);setattr(instance,key,value)
                elif self.cleaned_data.get('remove_'+field):setattr(instance,key,'')
            if commit:instance.save();self._save_m2m()
        except Exception:
            from django.core.files.storage import default_storage
            for key in self.branding_created:default_storage.delete(key)
            raise
        return instance


class SlideshowForm(forms.ModelForm):
    class Meta:
        model=Competition
        fields=['slideshow_enabled','slide_intro','slide_schedule','slide_results','slide_intro_seconds',
            'slide_schedule_seconds','slide_results_seconds','slide_refresh_seconds']
        labels={'slideshow_enabled':'Enable public slideshow at /slide','slide_intro':'Introduction',
            'slide_schedule':'Schedule','slide_results':'Results','slide_intro_seconds':'Introduction (seconds)',
            'slide_schedule_seconds':'Schedule (seconds)','slide_results_seconds':'Results (seconds)',
            'slide_refresh_seconds':'Check for website updates (seconds)'}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from .slide_settings import TEXTS,COLORS,IMAGE_SLOTS,values,resolve,automatic_text,text_template,challenge_context
        from .slideshow import display_day,slide_images
        now=timezone.now();context=values(self.instance,display_day(self.instance,now),now)
        design=self.instance.slide_design or {}
        challenge=self.instance.challenge_set.filter(archived_at=None).first()
        context.update(challenge_context(challenge,challenge.round_set.filter(archived_at=None).count() if challenge else 0))
        for name in ['slide_intro_seconds','slide_schedule_seconds','slide_results_seconds','slide_refresh_seconds']:
            old=self.fields[name];self.fields[name]=forms.IntegerField(label=old.label,min_value=15 if name=='slide_refresh_seconds' else 3,max_value=300 if name=='slide_refresh_seconds' else 120)
        self.slide_text_groups=[]
        for prefix,heading in [('Introduction','Introduction text'),('Schedule','Schedule text'),('Results','Results & table labels')]:
            group=[]
            for key,(label,default) in TEXTS.items():
                if not label.startswith(prefix):continue
                name='text_'+key;template=text_template(design,key);automatic=automatic_text(design,key)
                current=resolve(template,context)
                self.fields[name]=forms.CharField(label=label.split(' · ',1)[-1],required=False,max_length=300,initial=current if automatic else template,
                    widget=forms.Textarea(attrs={'rows':2}) if '\n' in default else forms.TextInput(),
                    help_text=format_html('Current display: {}',current))
                auto_field=None
                if '{' in default:
                    auto_name='auto_'+key
                    self.fields[auto_name]=forms.BooleanField(required=False,label='Use website data automatically',initial=automatic,widget=forms.CheckboxInput(attrs={'data-slide-auto':name}))
                    self.fields[name].widget.attrs['data-slide-automatic-value']=resolve(default,context)
                    if automatic:self.fields[name].widget.attrs['readonly']=True
                    auto_field=self[auto_name]
                group.append({'field':self[name],'automatic':auto_field})
            self.slide_text_groups.append({'title':heading,'fields':group})
        self.slide_color_fields=[]
        for key,(label,default) in COLORS.items():
            name='color_'+key;self.fields[name]=forms.RegexField(r'^#[0-9a-fA-F]{6}$',label=label,initial=design.get('colors',{}).get(key,default),widget=forms.TextInput(attrs={'type':'color'}));self.slide_color_fields.append(self[name])
        self.slide_image_cards=[]
        urls=slide_images(self.instance)
        for slot,label in IMAGE_SLOTS.items():
            name='image_'+slot;reset='reset_'+slot
            self.fields[name]=forms.FileField(required=False,label='Replace '+label.lower(),widget=forms.FileInput(attrs={'accept':'image/*'}))
            self.fields[reset]=forms.BooleanField(required=False,label='Use automatic / original image')
            self.slide_image_cards.append({'title':label,'url':urls[slot],'field':self[name],'reset':self[reset]})
        self.fields['qr_destination']=forms.URLField(required=False,assume_scheme='https',max_length=1000,label='QR code destination',initial=design.get('qr_destination') or settings.PUBLIC_ORIGIN,help_text='Uses the website address automatically unless you enter a different destination. An uploaded QR image replaces the generated code.')
    def clean(self):
        data=super().clean()
        if data.get('slideshow_enabled') and not any(data.get(k) for k in ['slide_intro','slide_schedule','slide_results']):
            raise forms.ValidationError('Choose at least one slide section, or disable the public slideshow.')
        from .branding import normalize_image
        from .slide_settings import IMAGE_SLOTS
        self.slide_uploads={}
        for slot in IMAGE_SLOTS:
            if data.get('image_'+slot):
                if data.get('reset_'+slot):self.add_error('image_'+slot,'Choose a replacement or reset, not both.')
                else:
                    try:self.slide_uploads[slot]=normalize_image(data['image_'+slot])
                    except forms.ValidationError as exc:self.add_error('image_'+slot,exc)
        if data.get('qr_destination') and data['qr_destination']!=settings.PUBLIC_ORIGIN:
            from urllib.parse import urlsplit
            url=urlsplit(data['qr_destination'])
            if url.scheme!='https' or url.username or url.password:self.add_error('qr_destination','Use an HTTPS URL without credentials.')
        return data
    def save(self,commit=True):
        instance=super().save(commit=False)
        from .slide_settings import TEXTS,COLORS,IMAGE_SLOTS
        from .branding import store_image
        design={'texts':{k:default if self.cleaned_data.get('auto_'+k) else self.cleaned_data.get('text_'+k,'') for k,(_,default) in TEXTS.items()},
            'automatic':{k:bool(self.cleaned_data.get('auto_'+k)) for k,(_,default) in TEXTS.items() if '{' in default},
            'colors':{k:self.cleaned_data['color_'+k] for k in COLORS},
            'images':dict((instance.slide_design or {}).get('images',{})), 'qr_destination':self.cleaned_data.get('qr_destination','')}
        if design['qr_destination']==settings.PUBLIC_ORIGIN:design['qr_destination']=''
        self.branding_created=[]
        try:
            for slot in IMAGE_SLOTS:
                if slot in self.slide_uploads:
                    key=store_image(instance,self.slide_uploads[slot]);self.branding_created.append(key);design['images'][slot]=key
                elif self.cleaned_data.get('reset_'+slot):design['images'].pop(slot,None)
            instance.slide_design=design
            if commit:instance.save(update_fields=[*self.Meta.fields,'slide_design'])
        except Exception:
            from django.core.files.storage import default_storage
            for key in self.branding_created:default_storage.delete(key)
            raise
        return instance


class ProgrammeForm(TimeRangeMixin,forms.ModelForm):
    revision=forms.CharField(required=False,widget=forms.HiddenInput)
    end_mode=forms.ChoiceField(choices=[('duration','Duration in minutes'),('end','End date and time')],required=False,label='Set the finish using')
    duration_minutes=forms.IntegerField(min_value=1,max_value=10080,required=False,label='Duration (minutes)',widget=forms.NumberInput(attrs={'step':1,'placeholder':'15'}))
    class Meta:
        model=Programme
        fields=['title','field','starts_at','end_mode','duration_minutes','ends_at','confirmed']
        labels={'starts_at':'Start date and time','ends_at':'End date and time','field':'Field / location','confirmed':'Confirmed schedule entry','round':'Challenge round (optional)'}
    def __init__(self,*args,competition=None,**kwargs):
        super().__init__(*args,**kwargs);self.instance.competition=competition
        self.time_fields()

class ManageAnnouncementForm(AnnouncementForm):
    audience=forms.ChoiceField(choices=[('all','All registered teams'),('selected','Selected teams'),
        ('public','Public homepage only'),('public_all','Public homepage + all teams'),
        ('public_selected','Public homepage + selected teams')],required=False,initial='all',label='Audience')
    send_email=forms.BooleanField(required=False,initial=True,label='Send a personalized email to the selected recipients')
    def __init__(self,*args,notice=None,**kwargs):
        args=recipient_data(args,kwargs.get('competition'))
        if notice:
            audience=('public_all' if notice.public else 'all') if notice.general else (
                'public_selected' if notice.targets.exists() else 'public') if notice.public else 'selected'
            kwargs['initial']={'title':notice.title,'body':notice.body,'general':notice.general,
                'public':notice.public,'targets':list(notice.targets.values_list('pk',flat=True)),
                'email_recipients':notice.email_recipients,'audience':audience,'send_email':False}
        if args and args[0] is not None and args[0].get('audience'):
            data=args[0].copy();audience=data.get('audience')
            data['general']='on' if audience in ['all','public_all'] else ''
            data['public']='on' if audience.startswith('public') else ''
            if audience=='public': data.setlist('targets',[]) if hasattr(data,'setlist') else data.update(targets=[])
            args=(data,*args[1:])
        super().__init__(*args,**kwargs)
        self.fields['general'].widget=forms.HiddenInput()
        self.fields['public'].widget=forms.HiddenInput()
        self.fields['targets'].help_text='Choose recipients with the checkboxes, or use select all and clear.'
        self.order_fields(['title','body','audience','targets','send_email','general','public'])
        recipient_fields(self,'Show on the public homepage')
        if notice and not self.is_bound:
            self.initial['targets']=list(notice.targets.values_list('pk',flat=True))
        self.fields['targets'].help_text='Choose registered teams and/or add email addresses. Team selections receive dashboard notices; additional addresses receive email only.'
        self.fields['title'].help_text='Email subject: RoboCup ASR 2026 - Junior Rescue Simulation - followed by this topic.'
    def clean(self):
        data=super().clean()
        if data.get('audience') in ['selected','public_selected'] and not data.get('targets') and not data.get('email_recipients') and not self.errors.get('targets') and not self.errors.get('email_recipients'):
            self.add_error('targets','Choose a team or add an email recipient.')
        return data

class FileShareForm(forms.ModelForm):
    class Meta:
        model=FileShare
        fields=['title','general','public','targets']
        widgets={'targets':TeamPicker}
        labels={'title':'Subject','targets':'Recipients'}
    def __init__(self,*args,competition=None,**kwargs):
        args=recipient_data(args,competition)
        super().__init__(*args,**kwargs)
        self.fields['targets'].queryset=Team.objects.filter(competition=competition,active=True)
        recipient_fields(self,'Publish on public Resources')
    def clean(self):
        data=super().clean()
        if not data.get('general') and not data.get('public') and not data.get('targets'):
            self.add_error('targets','Choose recipients and/or public Resources.')
        if 'public' in self.changed_data: self.instance.public_approved=False
        return data
    def save(self,commit=True):
        share=super().save(commit=commit)
        if commit: sync_share_files(share)
        return share


def sync_share_files(share):
    # These fields remain a compatibility cache; access always reads the shared record.
    share.files.update(title=share.title,general=share.general,public_copy=share.public,public_approved=share.public_approved)
    for asset in share.files.all(): asset.targets.set(share.targets.all())


class FileForm(forms.ModelForm):
    public=forms.BooleanField(required=False,label='Public resource')
    class Meta:
        model=Asset
        fields=['title','original_name','general','targets']
        widgets={'targets':TeamPicker}
        labels={'original_name':'Download filename','general':'Available to all teams','targets':'Selected teams'}
    def __init__(self,*args,competition=None,**kwargs):
        args=recipient_data(args,competition)
        super().__init__(*args,**kwargs)
        self.fields['targets'].queryset=Team.objects.filter(competition=competition,active=True)
        if self.instance.kind!='resource':
            self.fields.pop('general');self.fields.pop('targets');self.fields.pop('public')
        else:
            if self.instance.share_id:
                share=self.instance.share
                self.initial.update(title=share.title,general=share.general,public=share.public,targets=list(share.targets.all()))
            else: self.initial['public']=self.instance.public_copy
        recipient_fields(self,'Publish on public Resources')
    def clean_original_name(self):
        name=self.cleaned_data['original_name']
        if PurePath(name.replace('\\','/')).name!=name or any(not ch.isprintable() for ch in name):
            raise forms.ValidationError('Use a filename without paths or control characters.')
        return name
    def clean(self):
        data=super().clean()
        if 'targets' in self.fields:
            if not data.get('general') and not data.get('targets') and not data.get('public'):
                self.add_error('targets','Choose recipient teams and/or public Resources.')
            if bool(data.get('public'))!=self.instance.public_copy:
                self.instance.public_approved=False
            self.instance.public_copy=bool(data.get('public'))
        return data
    def save(self,commit=True):
        asset=super().save(commit=commit)
        if commit and asset.share_id:
            share=asset.share
            share.title=asset.title;share.general=asset.general
            if share.public!=asset.public_copy: share.public_approved=False
            share.public=asset.public_copy;share.save()
            share.targets.set(self.cleaned_data['targets'])
            sync_share_files(share)
        return asset

class ManagedUploadForm(forms.Form):
    replacement=forms.UUIDField(required=False,widget=forms.HiddenInput)
    destination=forms.ChoiceField(choices=[('team','Private participant documents / round files'),
        ('quarantine','Private participant quarantine'),('organizer','Private organizer / referee documents for teams'),
        ('map','Round map'),('public','Separate public archive copy'),('resource','Public resource')],initial='organizer')
    audience=forms.ChoiceField(choices=[('all','All registered teams'),('selected','Selected teams'),('public','Public resources only'),('public_all','Public resources + all teams'),('public_selected','Public resources + selected teams')],required=False,initial='selected',label='Audience',help_text='One file record serves every selected recipient. Public access requires a clean scan and administrator approval.')
    team=forms.ModelChoiceField(queryset=Team.objects.none(),required=False)
    kind=forms.ChoiceField(choices=[(k,label) for k,label in Asset.KINDS if k in PACKAGE_KINDS|{'round_file'}],initial='tdp',required=False,label='Document category')
    round=forms.ModelChoiceField(queryset=Round.objects.none(),required=False)
    quarantine=forms.ModelChoiceField(queryset=Quarantine.objects.none(),required=False)
    title=forms.CharField(max_length=180,required=False,label='Subject for these files')
    general=forms.BooleanField(required=False,label='All active teams')
    targets=forms.ModelMultipleChoiceField(queryset=Team.objects.none(),required=False,label='Selected recipient teams',widget=TeamPicker)
    files=MultipleFileField(widget=MultipleFileInput,label='Files (any type)')
    def __init__(self,*args,competition=None,**kwargs):
        args=recipient_data(args,competition)
        if args and args[0] is not None and args[0].get('destination')=='organizer' and args[0].get('audience'):
            data=args[0].copy();data['general']='on' if data['audience'] in ['all','public_all'] else ''
            if data['audience']=='public':
                data.setlist('targets',[]) if hasattr(data,'setlist') else data.update(targets=[])
            args=(data,*args[1:])
        super().__init__(*args,**kwargs)
        initial=kwargs.get('initial',{})
        if not self.is_bound: self.fields['audience'].initial=initial.get('audience') or ('all' if initial.get('general') else 'selected')
        self.fields['general'].widget=forms.HiddenInput()
        self.fields['team'].queryset=self.fields['targets'].queryset=Team.objects.filter(competition=competition,active=True)
        self.fields['round'].queryset=Round.objects.filter(competition=competition,archived_at=None).select_related('challenge')
        self.fields['quarantine'].queryset=Quarantine.objects.filter(competition=competition,archived_at=None)
        recipient_fields(self,'Publish on public Resources')
        self.fields['team'].widget=forms.HiddenInput()
        self.fields['destination'].widget=forms.HiddenInput()
        self.destination_choices=[(key,label) for key,label in self.fields['destination'].choices if key!='map']
        if not self.is_bound and initial.get('team'): self.initial['targets']=[initial['team']]
    def clean(self):
        d=super().clean();destination=d.get('destination')
        if self.data.get('recipient_module') and destination in ['team','quarantine','public']:
            if not d.get('targets'): self.add_error('targets','Select at least one team.')
            else: d['team']=d['targets'][0]
        if d.get('replacement') and len(d.get('files',[]))!=1: self.add_error('files','Choose exactly one replacement file.')
        if destination in ['team','public'] and not d.get('kind'): self.add_error('kind','Choose a document category.')
        if destination in ['team','quarantine','public'] and not d.get('team'): self.add_error('team','Choose a team.')
        if destination=='quarantine' and not d.get('quarantine'): self.add_error('quarantine','Choose a file quarantine.')
        if (destination=='map' or (destination=='team' and d.get('kind')=='round_file')) and not d.get('round'):
            self.add_error('round','Choose a round.')
        if destination=='public' and d.get('kind') not in PACKAGE_KINDS: self.add_error('kind','Choose a team document category for a public archive copy.')
        if destination=='organizer' and d.get('audience')!='public' and not d.get('general') and not d.get('targets'): self.add_error('targets','Choose recipients or All active teams.')
        return d
