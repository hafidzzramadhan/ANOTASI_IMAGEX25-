from django.contrib.auth import authenticate
from rest_framework import serializers

from master.auth_utils import is_email_verified
from master.models import CustomUser, Dataset, DatasetComment


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(username=data['email'], password=data['password'])
        if not user:
            raise serializers.ValidationError('Email atau password salah.')
        if user.role != 'komisi':
            raise serializers.ValidationError('Akun ini bukan akun Komisi.')
        if not user.is_active:
            raise serializers.ValidationError('Akun belum aktif.')
        if not is_email_verified(user):
            raise serializers.ValidationError('Email belum diverifikasi.')
        if user.komisi_approval_status == 'pending':
            raise serializers.ValidationError('Akun kamu masih menunggu persetujuan admin.')
        if user.komisi_approval_status == 'rejected':
            raise serializers.ValidationError('Pendaftaran akun Komisi kamu ditolak admin.')
        if user.komisi_approval_status != 'approved':
            raise serializers.ValidationError('Status akun Komisi belum valid.')
        data['user'] = user
        return data


class UserMinSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email']


class DatasetCommentSerializer(serializers.ModelSerializer):
    user = UserMinSerializer(read_only=True)

    class Meta:
        model = DatasetComment
        fields = ['id', 'user', 'text', 'created_at']


class DatasetKomisiSerializer(serializers.ModelSerializer):
    labeler = UserMinSerializer(read_only=True)
    reviewed_by = UserMinSerializer(read_only=True)
    taken_down_by = UserMinSerializer(read_only=True)
    project_name = serializers.CharField(source='project.name', read_only=True, allow_null=True)
    file_url = serializers.SerializerMethodField()
    latest_comments = serializers.SerializerMethodField()
    comment_count = serializers.SerializerMethodField()

    class Meta:
        model = Dataset
        fields = [
            'id', 'project', 'project_name', 'name', 'description',
            'labeler', 'date_created', 'file_url', 'count',
            'status_publikasi', 'annotation_type', 'rating',
            'komisi_feedback', 'reviewed_by', 'reviewed_at',
            'taken_down_by', 'taken_down_at', 'takedown_reason',
            'latest_comments', 'comment_count',
        ]

    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file_path and request:
            return request.build_absolute_uri(obj.file_path.url)
        if obj.file_path:
            return obj.file_path.url
        return None

    def get_latest_comments(self, obj):
        qs = obj.comments.select_related('user').order_by('-created_at')[:3]
        return DatasetCommentSerializer(qs, many=True).data

    def get_comment_count(self, obj):
        return obj.comments.count()


class ReviewDatasetSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['approve', 'reject'])
    rating = serializers.DecimalField(max_digits=3, decimal_places=1, required=False, allow_null=True)
    feedback = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class TakedownDatasetSerializer(serializers.Serializer):
    reason = serializers.CharField()
