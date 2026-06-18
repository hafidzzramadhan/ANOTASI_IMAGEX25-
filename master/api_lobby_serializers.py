"""
Serializers untuk fitur LOBBY / MULTI-TENANT (mobile app Flutter).

Dipakai oleh master/api_lobby_views.py.
"""
from rest_framework import serializers

from master.models import Project, ProjectMember, ProjectInvite


class ProjectMembershipSerializer(serializers.Serializer):
    """
    Representasi 1 project dari sudut pandang user yang login,
    dipakai untuk list project di halaman Lobby.
    """
    unique_id = serializers.UUIDField(source='project.unique_id')
    name = serializers.CharField(source='project.name')
    description = serializers.CharField(source='project.description')
    role = serializers.CharField()
    member_count = serializers.IntegerField()
    created_at = serializers.DateTimeField(source='project.created_at')


class ProjectInviteSerializer(serializers.Serializer):
    """
    Representasi 1 invite pending untuk ditampilkan di Lobby.
    """
    token = serializers.UUIDField()
    project_name = serializers.CharField(source='project.name')
    project_unique_id = serializers.UUIDField(source='project.unique_id')
    invited_by = serializers.CharField(source='invited_by.username')
    role = serializers.CharField()
    created_at = serializers.DateTimeField()


class ProjectCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ['name', 'description']

    def validate_name(self, value):
        value = (value or '').strip()
        if not value:
            raise serializers.ValidationError('Nama project wajib diisi.')
        return value


class ProjectDetailSerializer(serializers.ModelSerializer):
    my_role = serializers.SerializerMethodField()
    created_by = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Project
        fields = ['unique_id', 'name', 'description', 'created_by', 'created_at', 'my_role']

    def get_my_role(self, obj):
        request = self.context.get('request')
        if not request:
            return None
        membership = obj.memberships.filter(user=request.user).first()
        return membership.role if membership else None


class ProjectMemberSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)

    class Meta:
        model = ProjectMember
        fields = ['user_id', 'username', 'email', 'role', 'joined_at']


class InviteCreateSerializer(serializers.Serializer):
    """
    Body untuk POST /api/projects/<unique_id>/invite/

    Salah satu dari `username` atau `email` wajib diisi.
    """
    username = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=ProjectMember.ROLE_CHOICES)

    def validate(self, attrs):
        username = (attrs.get('username') or '').strip()
        email = (attrs.get('email') or '').strip()
        if not username and not email:
            raise serializers.ValidationError('Isi username atau email user yang ingin diundang.')
        attrs['username'] = username
        attrs['email'] = email
        return attrs


class InviteActionResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectInvite
        fields = ['token', 'status', 'role']