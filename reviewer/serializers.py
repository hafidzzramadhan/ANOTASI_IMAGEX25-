# reviewer/serializers.py

from rest_framework import serializers
from django.contrib.auth import authenticate
from master.models import (
    CustomUser, JobProfile, JobImage,
    Issue, Annotation, Segmentation, PolygonPoint,
)


# ──────────────────────────────────────────────
# AUTH
# ──────────────────────────────────────────────

class LoginSerializer(serializers.Serializer):
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(username=data['email'], password=data['password'])
        if not user:
            raise serializers.ValidationError('Email atau password salah.')
        if not user.is_active:
            raise serializers.ValidationError('Akun tidak aktif.')
        if user.role not in ('reviewer', 'master'):
            raise serializers.ValidationError('Akun ini bukan reviewer.')
        data['user'] = user
        return data


# ──────────────────────────────────────────────
# USER (ringkas, untuk relasi)
# ──────────────────────────────────────────────

class UserMinSerializer(serializers.ModelSerializer):
    class Meta:
        model  = CustomUser
        fields = ['id', 'username', 'email']


# ──────────────────────────────────────────────
# JOB
# ──────────────────────────────────────────────

class JobProfileListSerializer(serializers.ModelSerializer):
    """Dipakai di GET /api/jobs/ — ringkas."""
    image_count      = serializers.SerializerMethodField()
    time_remaining   = serializers.SerializerMethodField()

    class Meta:
        model  = JobProfile
        fields = [
            'id', 'title', 'status', 'priority',
            'end_date', 'image_count', 'time_remaining',
        ]

    def get_image_count(self, obj):
        return JobImage.objects.filter(job=obj).count()

    def get_time_remaining(self, obj):
        from datetime import datetime, time as dt_time
        from django.utils import timezone

        now      = timezone.localtime()
        deadline = datetime.combine(obj.end_date, dt_time.max)
        deadline = timezone.make_aware(deadline, now.tzinfo)
        delta    = int((deadline - now).total_seconds())

        if delta <= 0:
            return 'Times Up'
        hours, rem = divmod(delta, 3600)
        if hours:
            return f'{hours} hours left'
        minutes, _ = divmod(rem, 60)
        return f'{minutes} minutes left' if minutes else 'less than 1 minute'


class JobProfileDetailSerializer(serializers.ModelSerializer):
    """Dipakai di GET /api/jobs/{id}/ — lengkap."""
    image_count        = serializers.SerializerMethodField()
    finished_count     = serializers.SerializerMethodField()
    rework_count       = serializers.SerializerMethodField()
    open_issue_count   = serializers.SerializerMethodField()
    worker_annotator   = UserMinSerializer(read_only=True)
    worker_reviewer    = UserMinSerializer(read_only=True)
    time_remaining     = serializers.SerializerMethodField()

    class Meta:
        model  = JobProfile
        fields = [
            'id', 'title', 'status', 'priority',
            'end_date', 'segmentation_type', 'shape_type', 'color',
            'worker_annotator', 'worker_reviewer',
            'image_count', 'finished_count', 'rework_count',
            'open_issue_count', 'time_remaining',
        ]

    def get_image_count(self, obj):
        return JobImage.objects.filter(job=obj).count()

    def get_finished_count(self, obj):
        return JobImage.objects.filter(job=obj, status='finished').count()

    def get_rework_count(self, obj):
        return JobImage.objects.filter(job=obj, status='in_rework').count()

    def get_open_issue_count(self, obj):
        return Issue.objects.filter(job=obj, status='open').count()

    def get_time_remaining(self, obj):
        from datetime import datetime, time as dt_time
        from django.utils import timezone

        now      = timezone.localtime()
        deadline = datetime.combine(obj.end_date, dt_time.max)
        deadline = timezone.make_aware(deadline, now.tzinfo)
        delta    = int((deadline - now).total_seconds())

        if delta <= 0:
            return 'Times Up'
        hours, rem = divmod(delta, 3600)
        if hours:
            return f'{hours} hours left'
        minutes, _ = divmod(rem, 60)
        return f'{minutes} minutes left' if minutes else 'less than 1 minute'


class DashboardStatsSerializer(serializers.Serializer):
    """Response body GET /api/dashboard/stats/"""
    total_job        = serializers.IntegerField()
    menunggu_diterima = serializers.IntegerField()
    sedang_direview  = serializers.IntegerField()
    selesai          = serializers.IntegerField()
    urgent           = serializers.IntegerField()


# ──────────────────────────────────────────────
# IMAGE
# ──────────────────────────────────────────────

class PolygonPointSerializer(serializers.ModelSerializer):
    class Meta:
        model  = PolygonPoint
        fields = ['order_index', 'x', 'y']


class AnnotationSerializer(serializers.ModelSerializer):
    polygon_points = serializers.SerializerMethodField()
    label          = serializers.SerializerMethodField()
    color          = serializers.SerializerMethodField()

    class Meta:
        model  = Annotation
        fields = [
            'id', 'label', 'color',
            'x_min', 'y_min', 'x_max', 'y_max',
            'polygon_points',
        ]

    def get_polygon_points(self, obj):
        if obj.segmentation:
            pts = obj.segmentation.polygon_points.all().order_by('order_index')
            return PolygonPointSerializer(pts, many=True).data
        return []

    def get_label(self, obj):
        if obj.segmentation:
            return obj.segmentation.label
        return getattr(obj, 'label', None)

    def get_color(self, obj):
        if obj.segmentation:
            return obj.segmentation.color
        return None


class JobImageListSerializer(serializers.ModelSerializer):
    """Ringkas — untuk list image dalam satu job."""
    annotator    = UserMinSerializer(read_only=True)
    image_url    = serializers.SerializerMethodField()
    issue_count  = serializers.SerializerMethodField()

    class Meta:
        model  = JobImage
        fields = [
            'id', 'image_url', 'status',
            'annotator', 'label_time', 'issue_count',
        ]

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return None

    def get_issue_count(self, obj):
        return Issue.objects.filter(image=obj).count()


class JobImageDetailSerializer(serializers.ModelSerializer):
    """Lengkap — termasuk anotasi & issue, untuk canvas review."""
    annotator    = UserMinSerializer(read_only=True)
    image_url    = serializers.SerializerMethodField()
    annotations  = serializers.SerializerMethodField()
    issues       = serializers.SerializerMethodField()

    class Meta:
        model  = JobImage
        fields = [
            'id', 'image_url', 'status',
            'annotator', 'label_time',
            'annotations', 'issues',
        ]

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return None

    def get_annotations(self, obj):
        anns = Annotation.objects.filter(job_image=obj)
        return AnnotationSerializer(anns, many=True).data

    def get_issues(self, obj):
        iss = Issue.objects.filter(image=obj).order_by('-created_at')
        return IssueListSerializer(iss, many=True).data


# ──────────────────────────────────────────────
# ISSUE
# ──────────────────────────────────────────────

class IssueListSerializer(serializers.ModelSerializer):
    """Ringkas — untuk list & nested di image detail."""
    assigned_to  = UserMinSerializer(read_only=True)
    created_by   = UserMinSerializer(read_only=True)
    job_title    = serializers.CharField(source='job.title', read_only=True)
    image_id     = serializers.IntegerField(source='image.id', read_only=True, allow_null=True)

    class Meta:
        model  = Issue
        fields = [
            'id', 'title', 'description', 'priority', 'status',
            'job_title', 'image_id', 'assigned_to', 'created_by',
            'created_at',
        ]


class IssueCreateSerializer(serializers.Serializer):
    """Body POST /api/issues/"""
    image_id    = serializers.IntegerField()
    title       = serializers.CharField(max_length=255, required=False, default='')
    description = serializers.CharField()
    priority    = serializers.ChoiceField(choices=['low', 'medium', 'high'], default='medium')

    def validate_image_id(self, value):
        if not JobImage.objects.filter(id=value).exists():
            raise serializers.ValidationError('Image tidak ditemukan.')
        return value


class IssueUpdateSerializer(serializers.Serializer):
    """Body PATCH /api/issues/{id}/"""
    status = serializers.ChoiceField(choices=['open', 'reworking', 'closed'])


class IssueSummarySerializer(serializers.Serializer):
    """Response GET /api/issues/summary/"""
    total    = serializers.IntegerField()
    open     = serializers.IntegerField()
    reworking = serializers.IntegerField()
    closed   = serializers.IntegerField()
