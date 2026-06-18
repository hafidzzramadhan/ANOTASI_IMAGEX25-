"""
API Views untuk fitur LOBBY / MULTI-TENANT (mobile app Flutter).

PENTING — beda dengan versi web:
Versi web (master/views.py) menyimpan "project aktif" di session Django
(request.session['current_project_uuid']). Mobile app bersifat stateless
(autentikasi pakai JWT, tanpa session cookie), jadi project_id HARUS selalu
dikirim ulang oleh client di setiap request yang butuh konteks project
(lihat get_project_or_403_api di bawah, dan endpoint job/dataset lama yang
perlu ditambah query param `project_id`).

Endpoint di file ini:
- GET  /api/lobby/projects/                          -> list project user
- GET  /api/lobby/invites/                            -> list invite pending
- POST /api/projects/create/                          -> buat project baru
- GET  /api/projects/<unique_id>/                     -> detail project
- GET  /api/projects/<unique_id>/enter/                -> cek role & masuk project
- GET  /api/projects/<unique_id>/members/              -> list member
- DELETE /api/projects/<unique_id>/members/<user_id>/  -> hapus member (master only)
- POST /api/projects/<unique_id>/invite/               -> kirim invite
- POST /api/invites/<token>/accept/                    -> terima invite
- POST /api/invites/<token>/decline/                   -> tolak invite
"""
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from master.models import CustomUser, Project, ProjectMember, ProjectInvite
from master.api_lobby_serializers import (
    ProjectMembershipSerializer,
    ProjectInviteSerializer,
    ProjectCreateSerializer,
    ProjectDetailSerializer,
    ProjectMemberSerializer,
    InviteCreateSerializer,
)


# ============================================================
# HELPER: isolasi data per project (versi API, tanpa session)
# ============================================================

def get_project_or_403_api(user, unique_id):
    """
    Ambil Project by unique_id, dan pastikan `user` adalah member-nya.
    Dipakai di semua endpoint yang scoped ke 1 project.

    Return: (project, role) jika valid.
    Raise: Project.DoesNotExist (404) atau PermissionError (403) yang
    sudah ditangani lewat helper `_project_or_error_response` di bawah.
    """
    project = get_object_or_404(Project, unique_id=unique_id)
    membership = ProjectMember.objects.filter(project=project, user=user).first()
    if not membership:
        return project, None
    return project, membership.role


def _forbidden(detail):
    return Response({'detail': detail}, status=status.HTTP_403_FORBIDDEN)


def _not_found(detail='Tidak ditemukan.'):
    return Response({'detail': detail}, status=status.HTTP_404_NOT_FOUND)


# ============================================================
# LOBBY
# ============================================================

class LobbyProjectListAPIView(APIView):
    """
    GET /api/lobby/projects/

    List semua project yang user (login) ikuti, beserta role
    user di tiap project. Dipakai untuk render halaman Lobby di mobile.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        memberships = (
            ProjectMember.objects
            .filter(user=request.user)
            .select_related('project')
            .annotate(member_count=Count('project__memberships'))
            .order_by('-project__created_at')
        )
        serializer = ProjectMembershipSerializer(memberships, many=True)
        return Response({'projects': serializer.data})


class LobbyInviteListAPIView(APIView):
    """
    GET /api/lobby/invites/

    List undangan project yang masih pending untuk user (login).
    Matching dilakukan via invited_user ATAU invited_email (untuk
    user yang diundang sebelum punya akun, lalu register dengan email itu).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        invites = (
            ProjectInvite.objects
            .filter(status='pending')
            .filter(Q(invited_user=request.user) | Q(invited_email__iexact=request.user.email))
            .select_related('project', 'invited_by')
            .order_by('-created_at')
        )
        serializer = ProjectInviteSerializer(invites, many=True)
        return Response({'invites': serializer.data})


# ============================================================
# PROJECT
# ============================================================

class ProjectCreateAPIView(APIView):
    """
    POST /api/projects/create/

    Body: { "name": "...", "description": "..." }

    Creator otomatis jadi ProjectMember dengan role 'master'.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ProjectCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            project = Project.objects.create(
                created_by=request.user,
                **serializer.validated_data,
            )
            ProjectMember.objects.create(
                project=project,
                user=request.user,
                role='master',
            )

        return Response({
            'unique_id': project.unique_id,
            'name': project.name,
            'description': project.description,
            'role': 'master',
            'created_at': project.created_at,
        }, status=status.HTTP_201_CREATED)


class ProjectDetailAPIView(APIView):
    """
    GET /api/projects/<unique_id>/

    Detail project. User harus member dari project ini.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, unique_id):
        project, role = get_project_or_403_api(request.user, unique_id)
        if role is None:
            return _forbidden('Anda tidak memiliki akses ke project ini.')

        serializer = ProjectDetailSerializer(project, context={'request': request})
        return Response(serializer.data)


class ProjectEnterAPIView(APIView):
    """
    GET /api/projects/<unique_id>/enter/

    Mengecek role user di project ini dan mengembalikan dashboard_url
    yang sesuai. Mobile app dipersilakan langsung memanggil endpoint
    dashboard tersebut dengan menyertakan ?project_id=<unique_id>.

    Tidak menyimpan apapun di server (stateless) — client (mobile app)
    yang bertanggung jawab menyimpan project_id aktif secara lokal dan
    menyertakannya di setiap request berikutnya.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, unique_id):
        project, role = get_project_or_403_api(request.user, unique_id)
        if role is None:
            return _forbidden('Anda tidak memiliki akses ke project ini.')

        dashboard_map = {
            'master': f'/api/master/dashboard/?project_id={project.unique_id}',
            'annotator': f'/api/annotator/dashboard/?project_id={project.unique_id}',
            'reviewer': f'/api/reviewer/dashboard/?project_id={project.unique_id}',
        }

        return Response({
            'project': {
                'unique_id': project.unique_id,
                'name': project.name,
            },
            'role': role,
            'dashboard_url': dashboard_map.get(role),
        })


class ProjectMemberListAPIView(APIView):
    """
    GET /api/projects/<unique_id>/members/

    List semua member project. User harus member dari project ini
    (semua role boleh lihat, bukan cuma master).
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, unique_id):
        project, role = get_project_or_403_api(request.user, unique_id)
        if role is None:
            return _forbidden('Anda tidak memiliki akses ke project ini.')

        members = (
            ProjectMember.objects
            .filter(project=project)
            .select_related('user')
            .order_by('role', 'user__username')
        )
        serializer = ProjectMemberSerializer(members, many=True)
        return Response({'members': serializer.data})


class ProjectMemberDetailAPIView(APIView):
    """
    DELETE /api/projects/<unique_id>/members/<user_id>/

    Hapus member dari project. Hanya boleh dilakukan oleh role 'master'
    di project tersebut. Master tidak bisa menghapus dirinya sendiri
    lewat endpoint ini (supaya project tidak kehilangan master sama sekali
    jika dia satu-satunya master).
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, unique_id, user_id):
        project, role = get_project_or_403_api(request.user, unique_id)
        if role is None:
            return _forbidden('Anda tidak memiliki akses ke project ini.')
        if role != 'master':
            return _forbidden('Hanya master project yang bisa menghapus member.')

        membership = ProjectMember.objects.filter(project=project, user_id=user_id).first()
        if not membership:
            return _not_found('Member tidak ditemukan di project ini.')

        if membership.user_id == request.user.id:
            other_masters = ProjectMember.objects.filter(
                project=project, role='master'
            ).exclude(user_id=request.user.id).exists()
            if not other_masters:
                return Response(
                    {'detail': 'Tidak bisa menghapus diri sendiri karena Anda satu-satunya master di project ini.'},
                    status=status.HTTP_409_CONFLICT,
                )

        membership.delete()
        return Response({'detail': 'Member berhasil dihapus dari project.'})


# ============================================================
# INVITE
# ============================================================

class ProjectInviteCreateAPIView(APIView):
    """
    POST /api/projects/<unique_id>/invite/

    Body: { "username": "..." }  ATAU  { "email": "..." }, plus "role".
    Hanya master project yang boleh mengundang.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, unique_id):
        project, role = get_project_or_403_api(request.user, unique_id)
        if role is None:
            return _forbidden('Anda tidak memiliki akses ke project ini.')
        if role != 'master':
            return _forbidden('Hanya master project yang bisa mengundang member.')

        serializer = InviteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        username = serializer.validated_data['username']
        email = serializer.validated_data['email']
        invite_role = serializer.validated_data['role']

        invited_user = None
        if username:
            invited_user = CustomUser.objects.filter(username__iexact=username).first()
        if not invited_user and email:
            invited_user = CustomUser.objects.filter(email__iexact=email).first()

        invited_email = invited_user.email if invited_user else email
        if not invited_email:
            return Response(
                {'detail': 'User dengan username tersebut tidak ditemukan dan tidak ada email yang diberikan.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if invited_user and ProjectMember.objects.filter(project=project, user=invited_user).exists():
            return Response(
                {'detail': 'User tersebut sudah menjadi member project ini.'},
                status=status.HTTP_409_CONFLICT,
            )

        existing_pending = ProjectInvite.objects.filter(
            project=project, invited_email__iexact=invited_email, status='pending'
        ).first()
        if existing_pending:
            return Response(
                {'detail': 'Sudah ada invite pending untuk email ini di project ini.'},
                status=status.HTTP_409_CONFLICT,
            )

        invite = ProjectInvite.objects.create(
            project=project,
            invited_by=request.user,
            invited_user=invited_user,
            invited_email=invited_email,
            role=invite_role,
        )

        return Response({
            'token': invite.token,
            'status': invite.status,
            'role': invite.role,
        }, status=status.HTTP_201_CREATED)


class InviteAcceptAPIView(APIView):
    """
    POST /api/invites/<token>/accept/
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, token):
        invite = get_object_or_404(ProjectInvite, token=token, status='pending')

        if invite.invited_user and invite.invited_user != request.user:
            return _forbidden('Invite ini bukan untuk akun Anda.')
        if invite.invited_user is None and invite.invited_email.lower() != request.user.email.lower():
            return _forbidden('Email akun Anda tidak cocok dengan invite ini.')

        with transaction.atomic():
            invite.invited_user = request.user
            invite.status = 'accepted'
            invite.save(update_fields=['invited_user', 'status'])
            ProjectMember.objects.get_or_create(
                project=invite.project,
                user=request.user,
                defaults={'role': invite.role},
            )

        return Response({
            'detail': f'Berhasil bergabung ke project "{invite.project.name}".',
            'project_unique_id': invite.project.unique_id,
            'role': invite.role,
        })


class InviteDeclineAPIView(APIView):
    """
    POST /api/invites/<token>/decline/
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, token):
        invite = get_object_or_404(ProjectInvite, token=token, status='pending')

        if invite.invited_user and invite.invited_user != request.user:
            return _forbidden('Invite ini bukan untuk akun Anda.')
        if invite.invited_user is None and invite.invited_email.lower() != request.user.email.lower():
            return _forbidden('Email akun Anda tidak cocok dengan invite ini.')

        invite.status = 'declined'
        invite.save(update_fields=['status'])

        return Response({'detail': 'Invite ditolak.'})