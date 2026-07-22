from datetime import datetime, time as dt_time

from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import serializers

from master.auth_utils import is_email_verified
from master.models import (
    Annotation,
    CustomUser,
    Issue,
    JobImage,
    JobProfile,
    MasterLabel,
    Notification,
)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(username=data['email'], password=data['password'])
        if not user:
            raise serializers.ValidationError('Email atau password salah.')
        if not user.is_active:
            raise serializers.ValidationError('Akun tidak aktif.')
        if not is_email_verified(user):
            raise serializers.ValidationError('Email belum diverifikasi.')

        has_global_role = user.role in ('annotator', 'master')
        has_project_role = user.project_memberships.filter(
            role__in=('annotator', 'master')
        ).exists()

        if not (has_global_role or has_project_role):
            raise serializers.ValidationError('Akun ini bukan annotator.')

        data['user'] = user
        return data


class UserMinSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email']


def time_remaining_for(end_date):
    now = timezone.localtime()
    deadline = datetime.combine(end_date, dt_time.max)
    deadline = timezone.make_aware(deadline, now.tzinfo)
    delta = int((deadline - now).total_seconds())
    if delta <= 0:
        return 'Times Up'
    hours, rem = divmod(delta, 3600)
    if hours:
        return f'{hours} hours left'
    minutes, _ = divmod(rem, 60)
    return f'{minutes} minutes left' if minutes else 'less than 1 minute'


class AnnotationSerializer(serializers.ModelSerializer):
    color = serializers.SerializerMethodField()

    class Meta:
        model = Annotation
        fields = [
            'id', 'label', 'color', 'type', 'points',
            'x_min', 'y_min', 'x_max', 'y_max',
            'is_auto_generated', 'status', 'notes',
            'created_at', 'updated_at',
        ]

    def get_color(self, obj):
        if obj.segmentation:
            return obj.segmentation.color
        if obj.job_image and obj.job_image.job:
            return obj.job_image.job.color
        return None


class JobImageListSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    annotation_count = serializers.SerializerMethodField()
    issue_count = serializers.SerializerMethodField()

    class Meta:
        model = JobImage
        fields = [
            'id', 'image_url', 'status', 'label_time',
            'annotation_count', 'issue_count', 'updated_at',
        ]

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        if obj.image:
            return obj.image.url
        return None

    def get_annotation_count(self, obj):
        return obj.annotations.count()

    def get_issue_count(self, obj):
        return obj.issues.count()


class IssueListSerializer(serializers.ModelSerializer):
    assigned_to = UserMinSerializer(read_only=True)
    created_by = UserMinSerializer(read_only=True)
    job_title = serializers.CharField(source='job.title', read_only=True)
    image_id = serializers.IntegerField(source='image.id', read_only=True, allow_null=True)

    class Meta:
        model = Issue
        fields = [
            'id', 'title', 'description', 'priority', 'status',
            'job_title', 'image_id', 'assigned_to', 'created_by',
            'created_at', 'updated_at',
        ]


class JobImageDetailSerializer(JobImageListSerializer):
    annotations = serializers.SerializerMethodField()
    issues = serializers.SerializerMethodField()

    class Meta(JobImageListSerializer.Meta):
        fields = JobImageListSerializer.Meta.fields + ['annotations', 'issues']

    def get_annotations(self, obj):
        qs = Annotation.objects.filter(job_image=obj).order_by('id')
        return AnnotationSerializer(qs, many=True).data

    def get_issues(self, obj):
        qs = Issue.objects.filter(image=obj).select_related('assigned_to', 'created_by', 'job')
        return IssueListSerializer(qs, many=True).data


class JobProfileListSerializer(serializers.ModelSerializer):
    image_count = serializers.SerializerMethodField()
    completed_images = serializers.SerializerMethodField()
    in_review_images = serializers.SerializerMethodField()
    issue_images = serializers.SerializerMethodField()
    time_remaining = serializers.SerializerMethodField()

    class Meta:
        model = JobProfile
        fields = [
            'id', 'title', 'description', 'status', 'priority',
            'segmentation_type', 'shape_type', 'color',
            'start_date', 'end_date', 'image_count',
            'completed_images', 'in_review_images', 'issue_images',
            'time_remaining',
        ]

    def get_image_count(self, obj):
        return obj.images.count()

    def get_completed_images(self, obj):
        return obj.images.filter(status__in=['annotated', 'in_review', 'finished']).count()

    def get_in_review_images(self, obj):
        return obj.images.filter(status='in_review').count()

    def get_issue_images(self, obj):
        return obj.images.filter(status__in=['issue', 'in_rework']).count()

    def get_time_remaining(self, obj):
        return time_remaining_for(obj.end_date)


class JobProfileDetailSerializer(JobProfileListSerializer):
    worker_annotator = UserMinSerializer(read_only=True)
    worker_reviewer = UserMinSerializer(read_only=True)

    class Meta(JobProfileListSerializer.Meta):
        fields = JobProfileListSerializer.Meta.fields + [
            'worker_annotator', 'worker_reviewer',
        ]


class AnnotationSaveSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    label = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    type = serializers.ChoiceField(choices=['box', 'polygon'], default='box')
    points = serializers.JSONField(required=False, allow_null=True)
    x_min = serializers.FloatField(required=False, allow_null=True)
    y_min = serializers.FloatField(required=False, allow_null=True)
    x_max = serializers.FloatField(required=False, allow_null=True)
    y_max = serializers.FloatField(required=False, allow_null=True)

    def validate(self, attrs):
        annotation_type = attrs.get('type', 'box')
        if annotation_type == 'polygon':
            if not attrs.get('points'):
                raise serializers.ValidationError('points wajib diisi untuk polygon.')
        else:
            required = ['x_min', 'y_min', 'x_max', 'y_max']
            missing = [field for field in required if attrs.get(field) is None]
            if missing:
                raise serializers.ValidationError(f'Field box wajib diisi: {", ".join(missing)}.')
        return attrs


class NotificationSerializer(serializers.ModelSerializer):
    sender = UserMinSerializer(read_only=True)
    job_id = serializers.IntegerField(source='job.id', read_only=True, allow_null=True)
    issue_id = serializers.IntegerField(source='issue.id', read_only=True, allow_null=True)
    task_id = serializers.SerializerMethodField()
    time_display = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'id', 'notification_type', 'title', 'message', 'status',
            'sender', 'job_id', 'issue_id', 'task_id',
            'time_display', 'created_at', 'read_at',
        ]

    def get_task_id(self, obj):
        return obj.get_task_id()

    def get_time_display(self, obj):
        return obj.get_time_display()


class MasterLabelSerializer(serializers.ModelSerializer):
    class Meta:
        model = MasterLabel
        fields = ['id', 'name', 'color']
