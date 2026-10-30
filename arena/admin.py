from django.contrib import admin
from django import forms
from .timing import RemainingTimeField, RUN_ALLOWANCE_SECONDS
from .access import staff_otp_required
from .models import (Asset, AuditEvent, Competition, EmailDelivery, Membership,
                     Programme, Round, Score, Team)

class OrganizerAdminSite(admin.AdminSite):
    def each_context(self,request):
        context=super().each_context(request);competition=Competition.objects.first()
        if competition:context.update(site_header=competition.short_name+' · System administration',site_title=competition.short_name)
        return context

    def has_permission(self,request):
        return super().has_permission(request) and (
            not staff_otp_required(request.user) or request.user.is_verified())

admin.site.__class__ = OrganizerAdminSite
admin.site.site_header = 'ASR 26 · System administration'
admin.site.site_title = 'ASR 26'

class AuditedAdmin(admin.ModelAdmin):
    def save_model(self,request,obj,form,change):
        super().save_model(request,obj,form,change)
        AuditEvent.objects.create(actor=request.user,action='admin.changed' if change else 'admin.created',
            object_id=str(obj.pk),detail={'model':obj._meta.label,'fields':list(form.changed_data)})
    def has_delete_permission(self,request,obj=None):
        return False

@admin.register(Competition)
class CompetitionAdmin(AuditedAdmin):
    list_display=['name','phase','archive_released','workbook_last_synced']
    readonly_fields=['archive_released','workbook_last_synced','workbook_digest']

@admin.register(Team)
class TeamAdmin(AuditedAdmin):
    list_display=['code','name','country','scheduled','active']
    search_fields=['code','name']

@admin.register(Round)
class RoundAdmin(AuditedAdmin):
    list_display=['number','quarantine_at','starts_at','completed','maps_released']
    readonly_fields=['completed','maps_released']

@admin.register(Programme)
class ProgrammeAdmin(AuditedAdmin):
    list_display=['title','starts_at','ends_at','team','confirmed']

class ScoreAdminForm(forms.ModelForm):
    remaining_time = RemainingTimeField()
    class Meta:
        model = Score
        exclude = ['elapsed_seconds']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial['remaining_time'] = self.instance.remaining_seconds

    def save(self, commit=True):
        obj = super().save(commit=False)
        remaining = self.cleaned_data['remaining_time']
        obj.elapsed_seconds = None if remaining is None else RUN_ALLOWANCE_SECONDS - remaining
        if commit:
            obj.save()
        return obj


@admin.register(Score)
class ScoreAdmin(AuditedAdmin):
    form=ScoreAdminForm
    list_display=['team','round','raw','normalized','elapsed_time','elapsed_seconds']
    readonly_fields=['elapsed_time','elapsed_seconds']

@admin.register(Membership)
class MembershipAdmin(AuditedAdmin):
    list_display=['user','team']

class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self,request): return False
    def has_change_permission(self,request,obj=None): return False
    def has_delete_permission(self,request,obj=None): return False

@admin.register(AuditEvent)
class AuditAdmin(ReadOnlyAdmin):
    list_display=['occurred_at','actor','team','action','object_id','sha256']
    list_filter=['action']
    search_fields=['sha256','object_id','team__code']

@admin.register(Asset)
class AssetAdmin(ReadOnlyAdmin):
    list_display=['original_name','team','round','kind','size','scan_status','public_approved','created_at']
    list_filter=['kind','scan_status','public_approved']

@admin.register(EmailDelivery)
class DeliveryAdmin(ReadOnlyAdmin):
    # Invitation links and message bodies contain setup tokens; no message body in admin.
    list_display=['team','subject','attempts','sent_at','last_error']
    exclude=['body','html_body']
