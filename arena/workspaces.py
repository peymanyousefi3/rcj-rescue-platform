"""Shared SuperTeam profiles and private participant complaints."""
from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from .access import owns_team, can_download, public_asset
from .forms import MultipleFileField, MultipleFileInput
from .models import Challenge, Complaint, FileShare, Team
from .services import audit, upload_asset
from .widgets import TeamPicker


class SuperTeamForm(forms.ModelForm):
    members=forms.ModelMultipleChoiceField(queryset=Team.objects.none(),widget=TeamPicker,
        label='Member teams',help_text='Select exactly two teams. Each uses its existing login to access this shared profile; individual files stay separate.')
    class Meta:
        model=Team
        fields=['superteam_challenge','code','name','members','active']
        labels={'superteam_challenge':'SuperTeam challenge','code':'SuperTeam code','name':'SuperTeam name','active':'SuperTeam is active'}
    def __init__(self,*args,competition=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.instance.competition=competition
        self.fields['superteam_challenge'].required=True
        self.fields['superteam_challenge'].queryset=Challenge.objects.filter(competition=competition,category='superteam',archived_at=None)
        self.fields['members'].queryset=Team.objects.regular().filter(competition=competition,active=True)
        self.previous_challenge=Team.objects.filter(pk=self.instance.pk).values_list('superteam_challenge_id',flat=True).first() if self.instance.pk else None
    def clean(self):
        data=super().clean();members=data.get('members');challenge=data.get('superteam_challenge')
        if members is not None and len(members)!=2: self.add_error('members','Select exactly two member teams.')
        if self.previous_challenge and challenge and self.previous_challenge!=challenge.pk:
            self.add_error('superteam_challenge','Keep this profile in its original challenge to preserve scores and files. Create another SuperTeam for a different challenge.')
        return data
    def save(self,commit=True):
        # The admin caller holds the competition lock, including membership checks.
        members=self.cleaned_data['members'];challenge=self.cleaned_data['superteam_challenge']
        if members.filter(active=True,superteam_challenge=None,competition=self.instance.competition).count()!=2:
            raise ValidationError('Select exactly two active teams in this competition.')
        if self.cleaned_data['active'] and Team.objects.filter(superteam_challenge=challenge,active=True,members__in=members).exclude(pk=self.instance.pk).exists():
            raise ValidationError('A selected team already belongs to another active SuperTeam in this challenge.')
        self.instance.country=' + '.join(sorted({member.country for member in members}))[:80]
        return super().save(commit=commit)


class ComplaintForm(forms.ModelForm):
    files=MultipleFileField(required=False,widget=MultipleFileInput,label='Attachments',help_text='Optional. Select multiple files of any type. Only your team and administrators can access them.')
    class Meta:
        model=Complaint
        fields=['subject','message']
        widgets={'message':forms.Textarea(attrs={'rows':5})}
        labels={'message':'Describe your complaint'}


class ComplaintReviewForm(forms.ModelForm):
    class Meta:
        model=Complaint
        fields=['status','response']
        widgets={'response':forms.Textarea(attrs={'rows':5})}
        labels={'response':'Response to the team'}


def save_complaint(form,user,team):
    stored=[]
    try:
        with transaction.atomic():
            Team.objects.select_for_update().get(pk=team.pk)
            if not owns_team(user,team): raise PermissionDenied()
            complaint=form.save(commit=False)
            complaint.team=team;complaint.competition=team.competition;complaint.author=user
            complaint.save()
            for file in form.cleaned_data.get('files') or []:
                stored.append(upload_asset(user=user,team=team,kind='complaint_file',file=file,complaint=complaint,append=True))
            audit(user,'complaint.submitted',team=team,object_id=complaint.pk,detail={'attachments':len(stored)})
            return complaint
    except Exception:
        for asset in stored: default_storage.delete(asset.blob_key)
        raise


@never_cache
@require_http_methods(['GET','POST'])
def complaints(request,superteam_id=None):
    from .views import team_required
    @team_required
    def page(request):
        form=ComplaintForm(request.POST if request.method=='POST' else None,request.FILES if request.method=='POST' else None)
        if request.method=='POST' and form.is_valid():
            try: save_complaint(form,request.user,request.team)
            except (ValidationError,PermissionDenied) as exc: form.add_error(None,str(exc))
            else:
                messages.success(request,'Your complaint and attachments were submitted privately. No email was sent.')
                return redirect(base_url(request.team)+'/complaints/')
        return render(request,'arena/complaints.html',{'team':request.team,'portal_base':base_url(request.team),'section':'complaints','form':form,
            'complaints':Complaint.objects.filter(team=request.team).prefetch_related('attachments')})
    return page(request,superteam_id=superteam_id) if superteam_id else page(request)


def base_url(team):
    return f'/portal/superteams/{team.pk}' if team.is_superteam else '/portal'


def admin_shares(competition):
    shares=list(FileShare.objects.filter(competition=competition).prefetch_related('targets','files'))
    for share in shares:
        share.display_files=[asset for asset in share.files.all() if asset.current and not asset.deleted_at]
        share.history_files=[asset for asset in share.files.all() if not asset.current or asset.deleted_at]
        share.clean=bool(share.display_files) and all(asset.scan_status=='clean' for asset in share.display_files)
    return shares


def shared_resources(competition,user,*,public=False,team=None):
    shares=FileShare.objects.filter(competition=competition,archived_at=None).prefetch_related('files','targets')
    if team: shares=shares.filter(Q(general=True)|Q(targets=team)).distinct()
    visible=[]
    for share in shares:
        share.display_files=[asset for asset in share.files.all() if asset.current and not asset.deleted_at and
            (public_asset(asset) if public else can_download(user,asset))]
        if share.display_files: visible.append(share)
    return visible


@never_cache
@require_http_methods(['GET','POST'])
def review_complaint(request,complaint_id):
    from .views import staff_required,current_competition
    @staff_required
    def page(request):
        complaint=get_object_or_404(Complaint,pk=complaint_id,competition=current_competition())
        form=ComplaintReviewForm(request.POST if request.method=='POST' else None,instance=complaint)
        if request.method=='POST' and form.is_valid():
            with transaction.atomic():
                Complaint.objects.select_for_update().get(pk=complaint.pk)
                form.save();audit(request.user,'complaint.reviewed',team=complaint.team,object_id=complaint.pk,detail={'status':complaint.status})
            messages.success(request,'Complaint updated. The response is visible to the submitting team; no email was sent.')
            return redirect('/control/#complaints')
        return render(request,'arena/complaint_review.html',{'complaint':complaint,'form':form,'section':'control'})
    return page(request)
