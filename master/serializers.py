from rest_framework import serializers

from master.models import CustomUser, Issue, JobProfile, ProjectMember


class MobileUserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    project_role = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email', 'full_name', 'phone_number', 'role', 'project_role']

    def get_full_name(self, obj):
        name = f"{obj.first_name or ''} {obj.last_name or ''}".strip()
        return name or obj.username or obj.email

    def get_project_role(self, obj):
        project = self.context.get('project')
        if not project:
            return None
        membership = ProjectMember.objects.filter(project=project, user=obj).first()
        return membership.role if membership else None


class TeamStatusSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    name = serializers.CharField()
    role = serializers.CharField()
    status = serializers.CharField()
    active_jobs = serializers.IntegerField()
    total_jobs = serializers.IntegerField()


class PerformanceMemberSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    phone_number = serializers.CharField()
    role = serializers.CharField()
    project_count = serializers.IntegerField()
    group = serializers.CharField()


class MasterIssueMobileSerializer(serializers.ModelSerializer):
    assigned_to = MobileUserSerializer(read_only=True)
    created_by = MobileUserSerializer(read_only=True)
    job_title = serializers.CharField(source='job.title', read_only=True)
    image_id = serializers.IntegerField(source='image.id', read_only=True, allow_null=True)

    class Meta:
        model = Issue
        fields = [
            'id', 'title', 'description', 'status', 'priority',
            'job', 'job_title', 'image_id', 'assigned_to', 'created_by',
            'created_at', 'updated_at', 'resolved_at',
        ]


class AssignWorkersSerializer(serializers.Serializer):
    job_id = serializers.IntegerField()
    annotator_id = serializers.IntegerField()
    reviewer_id = serializers.IntegerField()


class PublishDatasetSerializer(serializers.Serializer):
    project_id = serializers.UUIDField()
    job_id = serializers.IntegerField()
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    dataset_file = serializers.FileField()


class IssueDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=['side_annotator', 'side_reviewer', 'needs_clarification', 'close_issue', 'reopen']
    )
    note = serializers.CharField(required=False, allow_blank=True)
