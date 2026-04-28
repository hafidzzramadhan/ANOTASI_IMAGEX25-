"""
API Serializers untuk MASTER role (mobile app Flutter).

File ini dipisah dari api_serializers.py supaya gak nyampur
sama auth serializers.

Endpoint yang dipake:
- /api/master/dashboard/
- /api/master/jobs/
- /api/master/jobs/<id>/
- /api/master/jobs/<id>/assign/
- /api/master/jobs/<id>/images/
- /api/master/users/
- /api/master/notifications/
"""
from rest_framework import serializers
from master.models import (
    CustomUser, JobProfile, JobImage, Issue, Notification, Annotation
)


# ============================================================
# USER SERIALIZERS (buat list user di master)
# ============================================================

class UserBriefSerializer(serializers.ModelSerializer):
    """Versi ringkas user — buat embed di response lain (annotator/reviewer info di job)."""
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email', 'full_name', 'role']

    def get_full_name(self, obj):
        first = obj.first_name or ''
        last = obj.last_name or ''
        return f"{first} {last}".strip() or obj.username


class UserListSerializer(serializers.ModelSerializer):
    """Buat endpoint list user di master (filter by role, etc)."""
    full_name = serializers.SerializerMethodField()
    job_count = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'full_name', 'phone_number', 'role', 'is_active',
            'date_joined', 'job_count'
        ]

    def get_full_name(self, obj):
        first = obj.first_name or ''
        last = obj.last_name or ''
        return f"{first} {last}".strip() or obj.username

    def get_job_count(self, obj):
        if obj.role == 'annotator':
            return obj.annotator_jobs.count()
        elif obj.role == 'reviewer':
            return obj.reviewer_jobs.count()
        return 0


# ============================================================
# JOB IMAGE SERIALIZERS
# ============================================================

class JobImageSerializer(serializers.ModelSerializer):
    """Versi singkat image — buat list image dalam job."""
    image_url = serializers.SerializerMethodField()
    annotator_name = serializers.SerializerMethodField()
    annotation_count = serializers.SerializerMethodField()

    class Meta:
        model = JobImage
        fields = [
            'id', 'image_url', 'status', 'annotator_name',
            'annotation_count', 'updated_at'
        ]

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None

    def get_annotator_name(self, obj):
        if obj.annotator:
            return obj.annotator.username
        return None

    def get_annotation_count(self, obj):
        return obj.annotations.count()


class JobImageUploadSerializer(serializers.Serializer):
    """
    Buat bulk upload image ke job.
    Pake multipart/form-data, field 'images' = list file.
    """
    images = serializers.ListField(
        child=serializers.ImageField(),
        allow_empty=False,
        write_only=True
    )


# ============================================================
# JOB PROFILE SERIALIZERS
# ============================================================

class JobListSerializer(serializers.ModelSerializer):
    """
    Versi ringkas job — buat endpoint list (GET /api/master/jobs/).
    """
    annotator = UserBriefSerializer(source='worker_annotator', read_only=True)
    reviewer = UserBriefSerializer(source='worker_reviewer', read_only=True)
    image_count = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    first_image_url = serializers.SerializerMethodField()

    class Meta:
        model = JobProfile
        fields = [
            'id', 'title', 'description', 'status', 'priority',
            'segmentation_type', 'shape_type', 'color',
            'start_date', 'end_date', 'date_created',
            'annotator', 'reviewer',
            'image_count', 'progress', 'first_image_url',
        ]

    def get_image_count(self, obj):
        return obj.images.count()

    def get_progress(self, obj):
        total = obj.images.count()
        if total == 0:
            return 0
        finished = obj.images.filter(
            status__in=['finished', 'annotated', 'in_review']
        ).count()
        return round((finished / total) * 100, 1)

    def get_first_image_url(self, obj):
        first = obj.images.first()
        if first and first.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(first.image.url)
            return first.image.url
        return None


class JobDetailSerializer(serializers.ModelSerializer):
    """
    Versi lengkap job — buat detail (GET /api/master/jobs/<id>/).
    """
    annotator = UserBriefSerializer(source='worker_annotator', read_only=True)
    reviewer = UserBriefSerializer(source='worker_reviewer', read_only=True)
    image_count = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    issue_count = serializers.SerializerMethodField()
    status_breakdown = serializers.SerializerMethodField()

    class Meta:
        model = JobProfile
        fields = [
            'id', 'title', 'description', 'status', 'priority',
            'segmentation_type', 'shape_type', 'color',
            'start_date', 'end_date', 'estimated_duration',
            'date_created', 'project_id',
            'annotator', 'reviewer',
            'image_count', 'progress', 'issue_count', 'status_breakdown',
        ]

    def get_image_count(self, obj):
        return obj.images.count()

    def get_progress(self, obj):
        total = obj.images.count()
        if total == 0:
            return 0
        finished = obj.images.filter(
            status__in=['finished', 'annotated', 'in_review']
        ).count()
        return round((finished / total) * 100, 1)

    def get_issue_count(self, obj):
        return obj.issues.count()

    def get_status_breakdown(self, obj):
        """Hitung berapa image per status."""
        from django.db.models import Count
        breakdown = obj.images.values('status').annotate(count=Count('id'))
        return {item['status']: item['count'] for item in breakdown}


class JobCreateSerializer(serializers.ModelSerializer):
    """
    Buat POST /api/master/jobs/ — bikin job baru.
    """
    class Meta:
        model = JobProfile
        fields = [
            'title', 'description', 'segmentation_type', 'shape_type',
            'color', 'start_date', 'end_date', 'priority',
            'estimated_duration', 'worker_annotator', 'worker_reviewer',
        ]
        extra_kwargs = {
            'worker_annotator': {'required': False, 'allow_null': True},
            'worker_reviewer': {'required': False, 'allow_null': True},
            'estimated_duration': {'required': False, 'allow_null': True},
            'description': {'required': False, 'allow_blank': True},
        }

    def validate(self, attrs):
        if attrs.get('end_date') and attrs.get('start_date'):
            if attrs['end_date'] < attrs['start_date']:
                raise serializers.ValidationError({
                    'end_date': 'End date harus setelah start date.'
                })
        return attrs


class JobAssignSerializer(serializers.Serializer):
    """
    Buat POST /api/master/jobs/<id>/assign/ — assign annotator + reviewer.
    """
    annotator_id = serializers.IntegerField(required=False, allow_null=True)
    reviewer_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_annotator_id(self, value):
        if value is not None:
            try:
                user = CustomUser.objects.get(id=value)
                if user.role != 'annotator':
                    raise serializers.ValidationError(
                        f"User #{value} bukan annotator (role: {user.role})."
                    )
            except CustomUser.DoesNotExist:
                raise serializers.ValidationError(f"User #{value} gak ada.")
        return value

    def validate_reviewer_id(self, value):
        if value is not None:
            try:
                user = CustomUser.objects.get(id=value)
                if user.role != 'reviewer':
                    raise serializers.ValidationError(
                        f"User #{value} bukan reviewer (role: {user.role})."
                    )
            except CustomUser.DoesNotExist:
                raise serializers.ValidationError(f"User #{value} gak ada.")
        return value


# ============================================================
# ISSUE SERIALIZERS
# ============================================================

class IssueListSerializer(serializers.ModelSerializer):
    """Buat list issue di master."""
    job_title = serializers.CharField(source='job.title', read_only=True)
    image_id = serializers.IntegerField(source='image.id', read_only=True, allow_null=True)
    assigned_to_name = serializers.CharField(source='assigned_to.username', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Issue
        fields = [
            'id', 'title', 'description', 'status', 'priority',
            'job', 'job_title', 'image_id',
            'assigned_to', 'assigned_to_name',
            'created_by', 'created_by_name',
            'created_at', 'updated_at', 'resolved_at',
        ]


# ============================================================
# NOTIFICATION SERIALIZERS
# ============================================================

class NotificationSerializer(serializers.ModelSerializer):
    """Buat list notif di master."""
    sender_name = serializers.SerializerMethodField()
    job_title = serializers.SerializerMethodField()
    time_ago = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'id', 'notification_type', 'title', 'message',
            'sender_name', 'job', 'job_title', 'issue',
            'status', 'created_at', 'read_at', 'time_ago',
        ]

    def get_sender_name(self, obj):
        return obj.sender.username if obj.sender else None

    def get_job_title(self, obj):
        return obj.job.title if obj.job else None

    def get_time_ago(self, obj):
        from django.utils.timesince import timesince
        return f"{timesince(obj.created_at)} ago"


# ============================================================
# DASHBOARD SERIALIZER (read-only stats)
# ============================================================

class DashboardStatsSerializer(serializers.Serializer):
    """
    Buat GET /api/master/dashboard/ — KPI cards.
    Ini bukan ModelSerializer — langsung dict dari view.
    """
    total_jobs = serializers.IntegerField()
    jobs_in_progress = serializers.IntegerField()
    jobs_in_review = serializers.IntegerField()
    jobs_finished = serializers.IntegerField()
    jobs_not_assigned = serializers.IntegerField()

    total_users = serializers.IntegerField()
    total_annotators = serializers.IntegerField()
    total_reviewers = serializers.IntegerField()

    total_images = serializers.IntegerField()
    images_finished = serializers.IntegerField()

    total_issues = serializers.IntegerField()
    issues_open = serializers.IntegerField()
    unread_notifications = serializers.IntegerField()