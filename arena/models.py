import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

class Competition(models.Model):
    name = models.CharField(max_length=160, default='Americas Super Regional 2026')
    short_name = models.CharField(max_length=40, default='Competition')
    header_title = models.CharField(max_length=160, default='Rescue Competition Platform')
    league_name = models.CharField(max_length=100, default='Rescue Simulation')
    banner_title = models.CharField(max_length=160, default='Rescue Simulation')
    banner_subtitle = models.CharField(max_length=200, blank=True)
    logo_key = models.CharField(max_length=240, blank=True, editable=False)
    partner_logo_key = models.CharField(max_length=240, blank=True, editable=False)
    banner_key = models.CharField(max_length=240, blank=True, editable=False)
    slide_design = models.JSONField(default=dict,blank=True)
    slideshow_enabled = models.BooleanField(default=True)
    slide_intro = models.BooleanField(default=True)
    slide_schedule = models.BooleanField(default=True)
    slide_results = models.BooleanField(default=True)
    slide_intro_seconds = models.PositiveSmallIntegerField(default=12)
    slide_schedule_seconds = models.PositiveSmallIntegerField(default=18)
    slide_results_seconds = models.PositiveSmallIntegerField(default=18)
    slide_refresh_seconds = models.PositiveSmallIntegerField(default=30)
    slide_rows = models.PositiveSmallIntegerField(default=8)
    slide_schedule_scope = models.CharField(max_length=12, choices=[('all','Whole competition'),('today','Today'),('upcoming','Upcoming entries')], default='all')
    slug = models.SlugField(unique=True, default='asr26')
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    phase = models.CharField(max_length=12, choices=[('upcoming','Upcoming'),('running','Running'),('finished','Finished')], default='upcoming')
    archive_released = models.BooleanField(default=False)
    location = models.CharField(max_length=180, default='Sheridan College · Davis Campus · Brampton, Ontario')
    workbook_enabled = models.BooleanField(default=False)
    counted_rounds = models.PositiveSmallIntegerField(default=6)
    workbook_last_synced = models.DateTimeField(null=True, blank=True)
    workbook_digest = models.CharField(max_length=64, blank=True)
    class Meta:
        constraints = [models.CheckConstraint(condition=Q(ends_at__gt=models.F('starts_at')), name='competition_valid_times')]
    @property
    def display_end_date(self):
        from datetime import timedelta,time
        end=timezone.localtime(self.ends_at)
        return (end-timedelta(microseconds=1) if end.time()==time() else end).date()

    @property
    def archive_open(self):
        return self.phase == 'finished' and self.archive_released and timezone.now() >= self.ends_at
    def __str__(self):
        return self.name

class TeamQuerySet(models.QuerySet):
    def regular(self):
        return self.filter(superteam_challenge=None)

    def participants(self, challenge=None):
        return self.filter(superteam_challenge=challenge if challenge and challenge.category=='superteam' else None)

class Team(models.Model):
    objects = TeamQuerySet.as_manager()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    competition = models.ForeignKey(Competition, on_delete=models.PROTECT)
    code = models.CharField(max_length=24, unique=True)
    name = models.CharField(max_length=160)
    country = models.CharField(max_length=80)
    school = models.CharField(max_length=180, blank=True)
    leader_email = models.EmailField(blank=True)
    active = models.BooleanField(default=True)
    scheduled = models.BooleanField(default=False)
    superteam_challenge = models.ForeignKey('Challenge', on_delete=models.PROTECT, null=True, blank=True, related_name='superteams')
    members = models.ManyToManyField('self', symmetrical=False, related_name='superteam_groups', blank=True)
    @property
    def is_superteam(self):
        return self.superteam_challenge_id is not None
    def clean(self):
        if self.superteam_challenge_id and (self.superteam_challenge.category!='superteam' or self.superteam_challenge.competition_id!=self.competition_id):
            raise ValidationError({'superteam_challenge':'Choose a SuperTeam challenge in this competition.'})
    def __str__(self):
        return f'{self.code} · {self.name}'

class Membership(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.PROTECT)

class Challenge(models.Model):
    competition = models.ForeignKey(Competition, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=12, choices=[('main','Main challenge'),('side','Side challenge'),('superteam','SuperTeam challenge')], default='side')
    expected_rounds = models.PositiveSmallIntegerField(default=1)
    calculation = models.CharField(max_length=12, choices=[('trimmed_mean','Average after discards (%)'),('sum','Sum'),('average','Average'),('best','Best scores')], default='trimmed_mean')
    discard_count = models.PositiveSmallIntegerField(default=0)
    tie_break = models.CharField(max_length=12, choices=[('none','Shared rank (tie)'),('retained','Highest retained round scores')], default='none')
    top_count = models.PositiveSmallIntegerField(default=1)
    score_source = models.CharField(max_length=12, choices=[('normalized','Normalized score'),('raw','Raw score')], default='normalized')
    rankings_released = models.BooleanField(default=False)
    primary = models.BooleanField(default=False, editable=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ['-primary','name','pk']
        constraints = [models.UniqueConstraint(fields=['competition','name'],name='unique_challenge_name'),
            models.UniqueConstraint(fields=['competition'],condition=Q(primary=True),name='one_primary_challenge')]
    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.calculation=='trimmed_mean' and self.discard_count>=self.expected_rounds:
            raise ValidationError({'discard_count':'At least one planned round must remain after discards.'})

class Round(models.Model):
    archived_at = models.DateTimeField(null=True, blank=True)
    competition = models.ForeignKey(Competition, on_delete=models.PROTECT)
    challenge = models.ForeignKey(Challenge, on_delete=models.PROTECT, null=True, blank=True)
    number = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=100, blank=True)
    opens_at = models.DateTimeField()
    quarantine_at = models.DateTimeField()
    submissions_enabled = models.BooleanField(default=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    completed = models.BooleanField(default=False)
    zero_score_policy = models.CharField(max_length=12, choices=[('pending','Await organizer decision'),('exclude','Exclude this round for every team'),('zero','Assign zero to every team')], default='pending')
    maps_released = models.BooleanField(default=False)
    map_general = models.BooleanField(default=True)
    map_public = models.BooleanField(default=True)
    map_targets = models.ManyToManyField(Team, related_name='round_maps', blank=True)
    playback_url = models.URLField(max_length=1000, blank=True)
    playback_released = models.BooleanField(default=False)
    class Meta:
        ordering = ['challenge_id','number']
        constraints = [
            models.UniqueConstraint(fields=['competition','challenge','number'], name='unique_challenge_round'),
            models.UniqueConstraint(fields=['competition','number'], condition=Q(challenge__isnull=True), name='unique_uncategorized_round'),
            models.CheckConstraint(condition=Q(opens_at__lt=models.F('quarantine_at')) & Q(starts_at__lt=models.F('ends_at')), name='round_valid_times'),
        ]
    @property
    def editable(self):
        now = timezone.now()
        return self.submissions_enabled and self.archived_at is None and not (self.challenge_id and self.challenge.archived_at) and self.competition.phase != 'finished' and self.opens_at <= now < self.quarantine_at and not self.completed
    @property
    def release_ready(self):
        return self.archived_at is None and not (self.challenge_id and self.challenge.archived_at) and self.completed
    @property
    def maps_open(self):
        return self.release_ready and self.maps_released
    @property
    def playback_open(self):
        return self.release_ready and bool(self.playback_url) and self.playback_released
    def clean(self):
        super().clean()
        if self.challenge_id and self.challenge.competition_id != self.competition_id:
            raise ValidationError({'challenge':'Choose a challenge in this competition.'})
        if self.playback_url:
            from urllib.parse import urlsplit
            url = urlsplit(self.playback_url)
            if url.scheme != 'https' or not url.hostname or url.username or url.password:
                raise ValidationError({'playback_url':'Use the public HTTPS URL of the exported Webots playback page, without credentials.'})
    def __str__(self):
        prefix = f'{self.challenge.name} · ' if self.challenge_id and not self.challenge.primary else ''
        return f'{prefix}Round {self.number}'
    @property
    def duration_minutes(self):
        return int((self.ends_at-self.starts_at).total_seconds()/60)

class Programme(models.Model):
    archived_at = models.DateTimeField(null=True, blank=True)
    source_key = models.CharField(max_length=120, unique=True)
    competition = models.ForeignKey(Competition, on_delete=models.PROTECT)
    title = models.CharField(max_length=180)
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    round = models.ForeignKey(Round, null=True, blank=True, on_delete=models.PROTECT)
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.PROTECT)
    field = models.CharField(max_length=30, blank=True)
    confirmed = models.BooleanField(default=True)
    class Meta:
        ordering = ['starts_at','pk']
    @property
    def live(self):
        return self.archived_at is None and self.confirmed and self.starts_at <= timezone.now() < self.ends_at
    @property
    def duration_minutes(self):
        return int((self.ends_at-self.starts_at).total_seconds()/60)

class Quarantine(models.Model):
    challenge = models.ForeignKey(Challenge, on_delete=models.PROTECT, null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    competition = models.ForeignKey(Competition, on_delete=models.PROTECT)
    name = models.CharField(max_length=180)
    instructions = models.TextField(max_length=4000, blank=True)
    deadline = models.DateTimeField()
    opens_at = models.DateTimeField(null=True, blank=True)
    all_teams = models.BooleanField(default=True)
    round = models.ForeignKey(Round, on_delete=models.PROTECT, null=True, blank=True)
    class Meta:
        ordering = ['deadline', 'name', 'pk']
    def clean(self):
        if self.opens_at and self.deadline and self.opens_at >= self.deadline:
            raise ValidationError({'deadline':'The deadline must follow the opening time.'})
        if self.round_id and self.round.competition_id != self.competition_id:
            raise ValidationError('Choose a round in this competition.')
    def deadline_for(self, team):
        if self.archived_at is not None or not team.active or team.competition_id != self.competition_id:
            return None
        if team.superteam_challenge_id != self.challenge_id or self.challenge_id and self.challenge.archived_at:
            return None
        target = next((row for row in self.team_deadlines.all() if row.team_id == team.pk), None)
        if not self.all_teams and target is None:
            return None
        return target.deadline if target and target.deadline else self.deadline
    def __str__(self):
        return self.name

class QuarantineTeam(models.Model):
    quarantine = models.ForeignKey(Quarantine, on_delete=models.PROTECT, related_name='team_deadlines')
    team = models.ForeignKey(Team, on_delete=models.PROTECT)
    deadline = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['quarantine','team'], name='one_quarantine_team')]
    def clean(self):
        if self.team.competition_id != self.quarantine.competition_id:
            raise ValidationError('Choose a team in this competition.')

class Score(models.Model):
    team = models.ForeignKey(Team, on_delete=models.PROTECT)
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    raw = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    normalized = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    normalized_override = models.BooleanField(default=False)
    elapsed_seconds = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(480)],
        help_text='Elapsed run time in seconds, converted from the time remaining out of 8 minutes.')
    class Meta:
        constraints = [models.UniqueConstraint(fields=['team','round'], name='unique_round_score'),
            models.CheckConstraint(condition=Q(elapsed_seconds__isnull=True) | Q(elapsed_seconds__lte=480), name='score_elapsed_within_allowance')]

    @property
    def remaining_seconds(self):
        return None if self.elapsed_seconds is None else 480 - self.elapsed_seconds

    @property
    def elapsed_time(self):
        from .timing import format_clock
        return format_clock(self.elapsed_seconds) or '—'

class FileShare(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    competition = models.ForeignKey(Competition, on_delete=models.PROTECT)
    title = models.CharField(max_length=180)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    general = models.BooleanField(default=False)
    public = models.BooleanField(default=False)
    public_approved = models.BooleanField(default=False)
    targets = models.ManyToManyField(Team, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    archived_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ['-created_at','-pk']

class Asset(models.Model):
    share = models.ForeignKey(FileShare, on_delete=models.PROTECT, null=True, blank=True, related_name='files')
    map_role = models.CharField(max_length=20, blank=True)
    field_info = models.JSONField(default=dict, blank=True)
    KINDS = [(k,'Submission file' if k.startswith('round_') else k.upper() if k in ['tdp','bom'] else k.replace('_',' ').title()) for k in ['round_file','round_code','round_json','tdp','video','code','bom','poster','resource','map','quarantine_file','complaint_file']]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    competition = models.ForeignKey(Competition, on_delete=models.PROTECT)
    team = models.ForeignKey(Team, on_delete=models.PROTECT, null=True, blank=True)
    round = models.ForeignKey(Round, on_delete=models.PROTECT, null=True, blank=True)
    quarantine = models.ForeignKey(Quarantine, on_delete=models.PROTECT, null=True, blank=True)
    complaint = models.ForeignKey('Complaint', on_delete=models.PROTECT, null=True, blank=True, related_name='attachments')
    kind = models.CharField(max_length=20, choices=KINDS)
    title = models.CharField(max_length=180, blank=True)
    blob_key = models.CharField(max_length=240, unique=True, editable=False)
    original_name = models.CharField(max_length=180)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64, editable=False)
    uploader = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    current = models.BooleanField(default=True)
    scan_status = models.CharField(max_length=12, choices=[('pending','Pending'),('clean','Clean'),('rejected','Rejected')], default='pending')
    public_approved = models.BooleanField(default=False)
    public_copy = models.BooleanField(default=False, help_text='Separate organizer upload intended for public release. Team submissions always remain private.')
    targets = models.ManyToManyField(Team, related_name='targeted_assets', blank=True)
    general = models.BooleanField(default=False)
    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['team','round','kind','current'], name='arena_asset_slot_idx')]
        constraints = [
            models.UniqueConstraint(fields=['team','round','kind'], condition=Q(current=True, deleted_at__isnull=True, kind__in=['round_code','round_json']), name='one_current_round_slot'),
        ]
    def clean(self):
        if self.share_id and (self.kind!='resource' or self.team_id or self.round_id or self.share.competition_id!=self.competition_id):
            raise ValidationError('A shared organizer delivery stores each file once, without a participant owner or round.')
        if self.kind=='complaint_file':
            if not self.complaint_id or self.complaint.team_id!=self.team_id or self.complaint.competition_id!=self.competition_id or self.public_copy or self.general or self.public_approved or self.round_id:
                raise ValidationError('Complaint attachments are private to their submitting team and administrators.')
        elif self.complaint_id:
            raise ValidationError('Only complaint attachments can belong to a complaint.')
        if self.kind == 'quarantine_file':
            if not self.quarantine_id or not self.team_id:
                raise ValidationError('Quarantine files require a quarantine and a team.')
            if self.quarantine.competition_id != self.competition_id:
                raise ValidationError('Quarantine belongs to a different competition.')
            if self.round_id != self.quarantine.round_id:
                raise ValidationError('File round must match the named quarantine.')
        elif self.quarantine_id:
            raise ValidationError('Only quarantine files can belong to a named quarantine.')
        if self.public_copy and self.kind not in ['tdp','video','code','bom','poster','resource']:
            raise ValidationError('Only separate archive packages and public resources can be public copies.')
        if self.kind.startswith('round_') and (not self.team_id or not self.round_id):
            raise ValidationError('Round submissions require a team and a round.')
        if self.kind == 'map' and not self.round_id:
            raise ValidationError('Maps require a round.')
        if self.team_id and self.team.competition_id != self.competition_id:
            raise ValidationError('Asset team belongs to a different competition.')
        if self.round_id and self.round.competition_id != self.competition_id:
            raise ValidationError('Asset round belongs to a different competition.')

class Complaint(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    competition = models.ForeignKey(Competition, on_delete=models.PROTECT)
    team = models.ForeignKey(Team, on_delete=models.PROTECT)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    recording = models.ForeignKey('RunRecording', on_delete=models.PROTECT, null=True, blank=True, related_name='complaints')
    playback_time_ms = models.PositiveBigIntegerField(null=True, blank=True)
    subject = models.CharField(max_length=180)
    message = models.TextField(max_length=12000)
    status = models.CharField(max_length=12, choices=[('submitted','Submitted'),('reviewing','Under review'),('resolved','Resolved')], default='submitted')
    response = models.TextField(max_length=12000, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['-created_at','-pk']

    @property
    def playback_timestamp(self):
        if self.playback_time_ms is None: return ''
        seconds=self.playback_time_ms//1000
        return f'{seconds//60:02d}:{seconds%60:02d}'

class Announcement(models.Model):
    archived_at = models.DateTimeField(null=True, blank=True)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    competition = models.ForeignKey(Competition, on_delete=models.PROTECT)
    title = models.CharField(max_length=180)
    body = models.TextField(max_length=12000)
    general = models.BooleanField(default=True)
    public = models.BooleanField(default=False)
    targets = models.ManyToManyField(Team, blank=True)
    email_recipients = models.TextField(blank=True, default='')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    class Meta:
        ordering = ['-created_at']
    @property
    def email_recipient_count(self):
        return len([line for line in self.email_recipients.splitlines() if line.strip()])

class Notification(models.Model):
    team = models.ForeignKey(Team, on_delete=models.PROTECT)
    announcement = models.ForeignKey(Announcement, on_delete=models.PROTECT)
    read_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['team','announcement'], name='one_team_notice')]

class EmailConfiguration(models.Model):
    # One site-wide connection. Never expose the encrypted credential in forms/admin.
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False)
    sender_name = models.CharField(max_length=120, default='ASR 26 Rescue Simulation')
    sender_email = models.EmailField(blank=True)
    host = models.CharField(max_length=253, blank=True)
    port = models.PositiveIntegerField(default=587)
    security = models.CharField(max_length=8, choices=[('starttls','STARTTLS'),('ssl','SSL/TLS')], default='starttls')
    username = models.CharField(max_length=254, blank=True)
    password_encrypted = models.TextField(blank=True, editable=False)
    announcement_cc = models.TextField(blank=True, default='')
    announcement_bcc = models.TextField(blank=True, default='')

class EmailDelivery(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey(Team, on_delete=models.PROTECT, null=True, blank=True)
    dedupe_key = models.CharField(max_length=160, unique=True)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    html_body = models.TextField(blank=True)
    recipient = models.EmailField()
    created_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    last_error = models.CharField(max_length=200, blank=True)
    class Meta:
        ordering = ['created_at']

class AuditEvent(models.Model):
    id = models.BigAutoField(primary_key=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)
    team = models.ForeignKey(Team, on_delete=models.PROTECT, null=True)
    action = models.CharField(max_length=80)
    object_id = models.CharField(max_length=80, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    detail = models.JSONField(default=dict)
    class Meta:
        ordering = ['-id']

class RequestQuota(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)

class RunRecording(models.Model):
    """A team/run replay, with video taking precedence over its Webots export."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    team = models.ForeignKey(Team, on_delete=models.PROTECT)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    current = models.BooleanField(default=True)
    published = models.BooleanField(default=False)
    entry_path = models.CharField(max_length=1000)
    preview_path = models.CharField(max_length=1000)
    scene_path = models.CharField(max_length=1000)
    animation_path = models.CharField(max_length=1000)
    player_version = models.CharField(max_length=30, default='R2023b')
    frame_count = models.PositiveIntegerField()
    duration_ms = models.PositiveBigIntegerField()
    manifest = models.JSONField(default=dict)
    video_key = models.CharField(max_length=240, blank=True)
    video_name = models.CharField(max_length=180, blank=True)
    video_type = models.CharField(max_length=30, blank=True)
    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['round','team'],condition=Q(current=True),name='one_current_run_recording')]
    @property
    def public_open(self):
        return self.current and self.published and self.team.active and self.round.release_ready
