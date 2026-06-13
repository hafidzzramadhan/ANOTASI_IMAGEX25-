"""
API Views untuk MASTER role (mobile app Flutter).

Semua endpoint di file ini WAJIB authenticated user dengan role='master'.
"""
from rest_framework import status, generics, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from django.db.models import Count, Q

from master.models import (
    CustomUser, JobProfile, JobImage, Issue, Notification
)
from master.api_master_serializers import (
    UserListSerializer, UserBriefSerializer,
    JobListSerializer, JobDetailSerializer, JobCreateSerializer,
    JobAssignSerializer, JobImageSerializer, JobImageUploadSerializer,
    IssueListSerializer, NotificationSerializer, DashboardStatsSerializer,
)


# ============================================================
# CUSTOM PERMISSION
# ============================================================

class IsMaster(permissions.BasePermission):
    """
    Cuma user dengan role='master' yang boleh akses.
    """
    message = "Cuma user dengan role 'master' yang boleh akses endpoint ini."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'role', None) == 'master'
        )


# ============================================================
# CUSTOM PAGINATION
# ============================================================

class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# ============================================================
# DASHBOARD
# ============================================================

class MasterDashboardAPIView(APIView):
    """
    GET /api/master/dashboard/

    Full breakdown KPI buat master dashboard.
    Response include:
      - Jobs (per status)
      - Users (per role)
      - Images (per status — buat KPI cards)
      - Issues (per status + priority)
      - Notifications
    """
    permission_classes = [permissions.IsAuthenticated, IsMaster]

    def get(self, request):
        stats = {
            # ============================================
            # JOBS — breakdown per status
            # ============================================
            'total_jobs': JobProfile.objects.count(),
            'jobs_not_assigned': JobProfile.objects.filter(status='not_assign').count(),
            'jobs_in_progress': JobProfile.objects.filter(status='in_progress').count(),
            'jobs_in_review': JobProfile.objects.filter(status='in_review').count(),
            'jobs_finished': JobProfile.objects.filter(status='finish').count(),

            # ============================================
            # USERS — breakdown per role
            # ============================================
            'total_users': CustomUser.objects.filter(is_active=True).count(),
            'total_annotators': CustomUser.objects.filter(role='annotator', is_active=True).count(),
            'total_reviewers': CustomUser.objects.filter(role='reviewer', is_active=True).count(),
            'total_masters': CustomUser.objects.filter(role='master', is_active=True).count(),

            # ============================================
            # IMAGES — breakdown per status (buat KPI cards)
            # ============================================
            'total_images': JobImage.objects.count(),
            'images_unannotated': JobImage.objects.filter(status='unannotated').count(),
            'images_in_progress': JobImage.objects.filter(status='in_progress').count(),
            'images_annotated': JobImage.objects.filter(status='annotated').count(),
            'images_in_review': JobImage.objects.filter(status='in_review').count(),
            'images_in_rework': JobImage.objects.filter(status='in_rework').count(),
            'images_finished': JobImage.objects.filter(status='finished').count(),
            'images_with_issues': JobImage.objects.filter(status='issue').count(),

            # ============================================
            # ISSUES — breakdown per status + priority
            # ============================================
            'total_issues': Issue.objects.count(),
            'issues_open': Issue.objects.filter(status='open').count(),
            'issues_eskalasi': Issue.objects.filter(status='eskalasi').count(),
            'issues_reworking': Issue.objects.filter(status='reworking').count(),
            'issues_closed': Issue.objects.filter(status='closed').count(),
            'issues_high_priority': Issue.objects.filter(
                priority='high', status__in=['open', 'eskalasi', 'reworking']
            ).count(),

            # ============================================
            # NOTIFICATIONS
            # ============================================
            'unread_notifications': Notification.objects.filter(
                recipient=request.user, status='unread'
            ).count(),
        }
        serializer = DashboardStatsSerializer(stats)
        return Response(serializer.data)


# ============================================================
# JOB MANAGEMENT
# ============================================================

class JobListCreateAPIView(generics.ListCreateAPIView):
    """
    GET  /api/master/jobs/        - List semua job (with pagination)
    POST /api/master/jobs/        - Bikin job baru

    Query params (GET):
    - status: filter by status (not_assign/in_progress/in_review/finish)
    - priority: filter by priority (low/medium/high/urgent)
    - search: cari di title
    - page: nomor halaman (default 1)
    - page_size: jumlah per halaman (default 20, max 100)
    """
    permission_classes = [permissions.IsAuthenticated, IsMaster]
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = JobProfile.objects.select_related(
            'worker_annotator', 'worker_reviewer'
        ).prefetch_related('images').order_by('-date_created')

        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        priority_filter = self.request.query_params.get('priority')
        if priority_filter:
            qs = qs.filter(priority=priority_filter)

        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(title__icontains=search)

        return qs

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return JobCreateSerializer
        return JobListSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job = serializer.save()

        # Auto-set status kalo annotator/reviewer udah di-assign
        if job.worker_annotator and job.worker_reviewer:
            job.status = 'in_progress'
            job.save()

        # Return pake JobDetailSerializer biar response lebih lengkap
        detail = JobDetailSerializer(job, context={'request': request})
        return Response(detail.data, status=status.HTTP_201_CREATED)


class JobDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/master/jobs/<id>/   - Detail job
    PATCH  /api/master/jobs/<id>/   - Update job
    DELETE /api/master/jobs/<id>/   - Hapus job
    """
    permission_classes = [permissions.IsAuthenticated, IsMaster]
    queryset = JobProfile.objects.all()
    lookup_field = 'pk'

    def get_serializer_class(self):
        if self.request.method in ['PATCH', 'PUT']:
            return JobCreateSerializer
        return JobDetailSerializer


class JobAssignAPIView(APIView):
    """
    POST /api/master/jobs/<id>/assign/

    Body:
    {
        "annotator_id": 5,    // optional
        "reviewer_id": 8      // optional
    }

    Response: detail job ter-update.
    """
    permission_classes = [permissions.IsAuthenticated, IsMaster]

    def post(self, request, pk):
        job = get_object_or_404(JobProfile, pk=pk)
        serializer = JobAssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        annotator_id = serializer.validated_data.get('annotator_id')
        reviewer_id = serializer.validated_data.get('reviewer_id')

        if annotator_id is not None:
            job.worker_annotator = CustomUser.objects.get(id=annotator_id)
        if reviewer_id is not None:
            job.worker_reviewer = CustomUser.objects.get(id=reviewer_id)

        # Auto-update status
        if job.worker_annotator and job.worker_reviewer and job.status == 'not_assign':
            job.status = 'in_progress'

        job.save()

        # Bikin notifikasi ke annotator
        if annotator_id is not None:
            Notification.objects.create(
                recipient=job.worker_annotator,
                sender=request.user,
                notification_type='job_assigned',
                title=f"Job baru: {job.title}",
                message=f"Lu di-assign ke job '{job.title}'. Buka aplikasi buat mulai annotate.",
                job=job,
            )

        # Bikin notifikasi ke reviewer
        if reviewer_id is not None:
            Notification.objects.create(
                recipient=job.worker_reviewer,
                sender=request.user,
                notification_type='job_assigned',
                title=f"Review job: {job.title}",
                message=f"Lu di-assign sebagai reviewer untuk job '{job.title}'.",
                job=job,
            )

        detail = JobDetailSerializer(job, context={'request': request})
        return Response(detail.data, status=status.HTTP_200_OK)


# ============================================================
# JOB IMAGES (list + bulk upload)
# ============================================================

class JobImageListUploadAPIView(APIView):
    """
    GET  /api/master/jobs/<id>/images/   - List image dalam job
    POST /api/master/jobs/<id>/images/   - Bulk upload image

    POST Body (multipart/form-data):
    - images: file1, file2, file3, ...
    """
    permission_classes = [permissions.IsAuthenticated, IsMaster]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = StandardPagination

    def get(self, request, pk):
        job = get_object_or_404(JobProfile, pk=pk)
        images = job.images.select_related('annotator').order_by('id')

        # Pagination
        paginator = StandardPagination()
        page = paginator.paginate_queryset(images, request)
        serializer = JobImageSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

    def post(self, request, pk):
        job = get_object_or_404(JobProfile, pk=pk)

        files = request.FILES.getlist('images')
        if not files:
            return Response(
                {'detail': "Field 'images' wajib diisi (multipart, list file)."},
                status=status.HTTP_400_BAD_REQUEST
            )

        created = []
        for f in files:
            img = JobImage.objects.create(
                job=job,
                image=f,
                annotator=job.worker_annotator,
                status='unannotated',
            )
            created.append(img)

        # Update image_count di job
        job.image_count = job.images.count()
        job.save()

        serializer = JobImageSerializer(created, many=True, context={'request': request})
        return Response({
            'message': f'{len(created)} image berhasil di-upload.',
            'images': serializer.data,
        }, status=status.HTTP_201_CREATED)


class JobImageDetailAPIView(APIView):
    """
    DELETE /api/master/images/<id>/   - Hapus image
    """
    permission_classes = [permissions.IsAuthenticated, IsMaster]

    def delete(self, request, pk):
        img = get_object_or_404(JobImage, pk=pk)
        job_id = img.job.id
        img.delete()

        # Update image_count
        job = JobProfile.objects.get(id=job_id)
        job.image_count = job.images.count()
        job.save()

        return Response(status=status.HTTP_204_NO_CONTENT)


# ============================================================
# USER MANAGEMENT
# ============================================================

class UserListAPIView(generics.ListAPIView):
    """
    GET /api/master/users/

    Query params:
    - role: annotator/reviewer/master/guest/member
    - search: cari di username/email/first_name
    - is_active: true/false
    """
    permission_classes = [permissions.IsAuthenticated, IsMaster]
    serializer_class = UserListSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = CustomUser.objects.all().order_by('-date_joined')

        role = self.request.query_params.get('role')
        if role:
            qs = qs.filter(role=role)

        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(
                Q(username__icontains=search)
                | Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )

        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            qs = qs.filter(is_active=(is_active.lower() == 'true'))

        return qs


class UserDetailAPIView(APIView):
    """
    GET    /api/master/users/<id>/         - Detail user
    PATCH  /api/master/users/<id>/         - Update user (role, is_active, dll)
    DELETE /api/master/users/<id>/         - Soft delete (set is_active=False)

    PATCH body example:
    {
        "role": "annotator",        // master | annotator | reviewer | guest
        "is_active": true,
        "first_name": "Budi",       // optional
        "last_name": "Santoso",     // optional
        "phone_number": "08xxx"     // optional
    }
    """
    permission_classes = [permissions.IsAuthenticated, IsMaster]

    # Field yg boleh di-update master
    ALLOWED_UPDATE_FIELDS = [
        'role', 'is_active', 'first_name', 'last_name',
        'phone_number', 'email',
    ]

    # Role yg valid
    VALID_ROLES = ['master', 'annotator', 'reviewer', 'guest', 'member']

    def get(self, request, pk):
        user = get_object_or_404(CustomUser, pk=pk)
        serializer = UserListSerializer(user)
        return Response(serializer.data)

    def patch(self, request, pk):
        user = get_object_or_404(CustomUser, pk=pk)

        # Cegah master ngapus role dirinya sendiri
        if user.id == request.user.id and 'role' in request.data:
            if request.data['role'] != 'master':
                return Response({
                    'detail': "Gak bisa demote diri sendiri dari role master."
                }, status=status.HTTP_400_BAD_REQUEST)

        # Validate role
        new_role = request.data.get('role')
        if new_role and new_role not in self.VALID_ROLES:
            return Response({
                'role': [f"Role harus salah satu: {', '.join(self.VALID_ROLES)}"]
            }, status=status.HTTP_400_BAD_REQUEST)

        # Apply field updates (cuma yg di whitelist)
        updated = []
        for field in self.ALLOWED_UPDATE_FIELDS:
            if field in request.data:
                value = request.data[field]
                # is_active special: convert string ke bool
                if field == 'is_active':
                    if isinstance(value, str):
                        value = value.lower() in ('true', '1', 'yes')
                setattr(user, field, value)
                updated.append(field)

        if not updated:
            return Response({
                'detail': f"Gak ada field valid yg di-update. Allowed: {self.ALLOWED_UPDATE_FIELDS}"
            }, status=status.HTTP_400_BAD_REQUEST)

        user.save(update_fields=updated)

        # Bikin notif ke user kalo role berubah
        if 'role' in updated:
            Notification.objects.create(
                recipient=user,
                sender=request.user,
                notification_type='role_changed',
                title="Role lu diubah",
                message=f"Master ngubah role lu jadi '{user.role}'.",
            )

        serializer = UserListSerializer(user)
        return Response({
            'detail': f"User updated. Fields: {', '.join(updated)}",
            'user': serializer.data,
        })

    def delete(self, request, pk):
        user = get_object_or_404(CustomUser, pk=pk)

        # Cegah master delete dirinya sendiri
        if user.id == request.user.id:
            return Response({
                'detail': "Gak bisa delete akun sendiri."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Cegah delete superuser lain
        if user.is_superuser:
            return Response({
                'detail': "Gak bisa delete superuser."
            }, status=status.HTTP_403_FORBIDDEN)

        # Soft delete: set inactive
        user.is_active = False
        user.save(update_fields=['is_active'])

        # Blacklist semua JWT refresh token user — force logout
        try:
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken, BlacklistedToken
            tokens = OutstandingToken.objects.filter(user=user)
            for token in tokens:
                BlacklistedToken.objects.get_or_create(token=token)
        except Exception:
            pass  # Token blacklist app gak terpasang, skip

        return Response({
            'detail': f"User '{user.username}' di-deactivate (soft delete + token blacklisted).",
        }, status=status.HTTP_200_OK)


class UserActivateAPIView(APIView):
    """
    POST /api/master/users/<id>/activate/

    Aktifin kembali user yg sebelumnya di-soft-delete.
    """
    permission_classes = [permissions.IsAuthenticated, IsMaster]

    def post(self, request, pk):
        user = get_object_or_404(CustomUser, pk=pk)
        user.is_active = True
        user.save(update_fields=['is_active'])

        Notification.objects.create(
            recipient=user,
            sender=request.user,
            notification_type='account_activated',
            title="Akun lu di-aktifin",
            message="Master ngaktifin kembali akun lu.",
        )

        return Response({
            'detail': f"User '{user.username}' di-aktifin.",
        })


# ============================================================
# ISSUE MANAGEMENT
# ============================================================

class MasterIssueListAPIView(generics.ListAPIView):
    """
    GET /api/master/issues/

    Query params:
    - status: open/eskalasi/reworking/closed
    - priority: low/medium/high
    - job_id: filter by job
    """
    permission_classes = [permissions.IsAuthenticated, IsMaster]
    serializer_class = IssueListSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = Issue.objects.select_related(
            'job', 'image', 'assigned_to', 'created_by'
        ).order_by('-created_at')

        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        priority_filter = self.request.query_params.get('priority')
        if priority_filter:
            qs = qs.filter(priority=priority_filter)

        job_id = self.request.query_params.get('job_id')
        if job_id:
            qs = qs.filter(job_id=job_id)

        return qs


# ============================================================
# NOTIFICATIONS
# ============================================================

class MasterNotificationListAPIView(generics.ListAPIView):
    """
    GET /api/master/notifications/

    Query params:
    - status: unread/read/accepted/rejected
    - type: job_assigned/job_updated/issue_created/issue_updated/job_deadline
    """
    permission_classes = [permissions.IsAuthenticated, IsMaster]
    serializer_class = NotificationSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = Notification.objects.filter(recipient=self.request.user).order_by('-created_at')

        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)

        type_filter = self.request.query_params.get('type')
        if type_filter:
            qs = qs.filter(notification_type=type_filter)

        return qs


class MasterNotificationMarkReadAPIView(APIView):
    """
    POST /api/master/notifications/<id>/read/   - Mark as read
    POST /api/master/notifications/read-all/    - Mark semua as read
    """
    permission_classes = [permissions.IsAuthenticated, IsMaster]

    def post(self, request, pk=None):
        if pk is None:
            # Mark all as read
            count = Notification.objects.filter(
                recipient=request.user, status='unread'
            ).update(status='read')
            return Response({
                'message': f'{count} notifikasi ditandai sebagai dibaca.'
            })

        notif = get_object_or_404(
            Notification, pk=pk, recipient=request.user
        )
        notif.mark_as_read()
        return Response({'message': 'Notifikasi ditandai sebagai dibaca.'})