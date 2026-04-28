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

    Response:
    {
        "total_jobs": 15,
        "jobs_in_progress": 5,
        "jobs_in_review": 3,
        "jobs_finished": 7,
        "jobs_not_assigned": 0,
        "total_users": 25,
        "total_annotators": 15,
        "total_reviewers": 8,
        "total_images": 1200,
        "images_finished": 800,
        "total_issues": 12,
        "issues_open": 4,
        "unread_notifications": 2
    }
    """
    permission_classes = [permissions.IsAuthenticated, IsMaster]

    def get(self, request):
        stats = {
            'total_jobs': JobProfile.objects.count(),
            'jobs_in_progress': JobProfile.objects.filter(status='in_progress').count(),
            'jobs_in_review': JobProfile.objects.filter(status='in_review').count(),
            'jobs_finished': JobProfile.objects.filter(status='finish').count(),
            'jobs_not_assigned': JobProfile.objects.filter(status='not_assign').count(),

            'total_users': CustomUser.objects.filter(is_active=True).count(),
            'total_annotators': CustomUser.objects.filter(role='annotator', is_active=True).count(),
            'total_reviewers': CustomUser.objects.filter(role='reviewer', is_active=True).count(),

            'total_images': JobImage.objects.count(),
            'images_finished': JobImage.objects.filter(status='finished').count(),

            'total_issues': Issue.objects.count(),
            'issues_open': Issue.objects.filter(status='open').count(),

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