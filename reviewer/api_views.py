from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import datetime, time as dt_time

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from master.models import (
    JobProfile, JobImage, Issue, Notification,
)
from .serializers import (
    LoginSerializer,
    JobProfileListSerializer,
    JobProfileDetailSerializer,
    DashboardStatsSerializer,
    JobImageListSerializer,
    JobImageDetailSerializer,
    IssueListSerializer,
    IssueCreateSerializer,
    IssueUpdateSerializer,
    IssueSummarySerializer,
)


# ─────────────────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────────────────

def reviewer_only(request):
    """
    Return error Response jika user bukan reviewer/master, else None.

    Cek role GLOBAL dulu (legacy). Kalau bukan, cek role PER-PROJECT
    (ProjectMember) di project yang sedang aktif — dari query param
    ?project_id=<uuid> (mobile) atau session current_project_uuid (web).
    """
    user = request.user
    if user.role in ('reviewer', 'master'):
        return None

    project_uuid = request.query_params.get('project_id') or request.session.get('current_project_uuid')
    if project_uuid:
        from master.models import ProjectMember
        is_member_ok = ProjectMember.objects.filter(
            project__unique_id=project_uuid,
            user=user,
            role__in=('reviewer', 'master'),
        ).exists()
        if is_member_ok:
            return None

    return Response(
        {'error': 'Akses hanya untuk reviewer.'},
        status=status.HTTP_403_FORBIDDEN,
    )


def _time_remaining(end_date):
    now      = timezone.localtime()
    deadline = datetime.combine(end_date, dt_time.max)
    deadline = timezone.make_aware(deadline, now.tzinfo)
    delta    = int((deadline - now).total_seconds())
    if delta <= 0:
        return 'Times Up'
    hours, rem = divmod(delta, 3600)
    if hours:
        return f'{hours} hours left'
    minutes, _ = divmod(rem, 60)
    return f'{minutes} minutes left' if minutes else 'less than 1 minute'


# ─────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────

@csrf_exempt
@api_view(['POST'])
@permission_classes([AllowAny])
def api_login(request):
    """
    POST /api/auth/login/
    Body : { "email": "...", "password": "..." }
    Return: { "access": "...", "refresh": "...", "username": "...", "role": "..." }
    """
    serializer = LoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user    = serializer.validated_data['user']
    refresh = RefreshToken.for_user(user)

    return Response({
        'access':   str(refresh.access_token),
        'refresh':  str(refresh),
        'username': user.username,
        'role':     user.role,
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_logout(request):
    """
    POST /api/auth/logout/
    Body : { "refresh": "<refresh_token>" }
    Blacklist refresh token sehingga tidak bisa dipakai lagi.
    """
    refresh_token = request.data.get('refresh')
    if not refresh_token:
        return Response(
            {'error': 'Refresh token wajib diisi.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
    except TokenError:
        return Response(
            {'error': 'Token tidak valid atau sudah expired.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response({'message': 'Logout berhasil.'}, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_dashboard_stats(request):
    """
    GET /api/dashboard/stats/
    KPI card data untuk home_reviewer.
    """
    err = reviewer_only(request)
    if err:
        return err

    qs   = JobProfile.objects.filter(worker_reviewer=request.user)
    now  = timezone.localtime()

    # hitung urgent: job in_review yang sudah mepet/lewat deadline
    urgent = 0
    for p in qs.filter(status='in_review'):
        tr = _time_remaining(p.end_date)
        if 'Times Up' in tr or 'minute' in tr:
            urgent += 1

    data = {
        'total_job':         qs.count(),
        'menunggu_diterima': qs.filter(status='in_progress').count(),
        'sedang_direview':   qs.filter(status='in_review').count(),
        'selesai':           qs.filter(status='finish').count(),
        'urgent':            urgent,
    }
    return Response(data, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────
# JOBS
# ─────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_job_list(request):
    """
    GET /api/jobs/
    Query params:
      ?status=in_progress|in_review|finish   (opsional, filter status)
    Return: list job milik reviewer yang login.
    """
    err = reviewer_only(request)
    if err:
        return err

    qs = JobProfile.objects.filter(worker_reviewer=request.user)

    status_filter = request.query_params.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)

    qs = qs.order_by('-id')
    serializer = JobProfileListSerializer(qs, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_job_detail(request, job_id):
    """
    GET /api/jobs/{job_id}/
    Detail satu job beserta stats image dan issue.
    """
    err = reviewer_only(request)
    if err:
        return err

    job = get_object_or_404(JobProfile, id=job_id, worker_reviewer=request.user)
    serializer = JobProfileDetailSerializer(job)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_job_accept(request, job_id):
    """
    POST /api/jobs/{job_id}/accept/
    Reviewer terima job → status: in_progress → in_review.
    """
    err = reviewer_only(request)
    if err:
        return err

    job = get_object_or_404(JobProfile, id=job_id, worker_reviewer=request.user)

    if job.status != 'in_progress':
        return Response(
            {'error': f'Job tidak bisa diterima dari status "{job.status}".'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    job.status = 'in_review'
    job.save()
    return Response(
        {'message': f'Job "{job.title}" berhasil diterima.', 'status': job.status},
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_job_drop(request, job_id):
    """
    POST /api/jobs/{job_id}/drop/
    Reviewer drop job → status kembali ke in_progress.
    """
    err = reviewer_only(request)
    if err:
        return err

    job = get_object_or_404(JobProfile, id=job_id, worker_reviewer=request.user)

    if job.status != 'in_review':
        return Response(
            {'error': f'Hanya job dengan status "in_review" yang bisa di-drop.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    job.status = 'in_progress'
    job.save()
    return Response(
        {'message': f'Job "{job.title}" di-drop kembali ke in_progress.', 'status': job.status},
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_job_done(request, job_id):
    """
    POST /api/jobs/{job_id}/done/
    Mark seluruh job selesai → semua image yang belum finished ikut di-mark finished.
    """
    err = reviewer_only(request)
    if err:
        return err

    job = get_object_or_404(JobProfile, id=job_id, worker_reviewer=request.user)

    if job.status not in ('in_review',):
        return Response(
            {'error': f'Job dengan status "{job.status}" tidak bisa di-done.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    job.status = 'finish'
    job.save()

    updated = JobImage.objects.filter(job=job).exclude(status='finished').update(status='finished')

    return Response({
        'message':         f'Job "{job.title}" selesai dan dikirim ke Master.',
        'status':          job.status,
        'images_finished': updated,
    }, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────
# IMAGES
# ─────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_image_list(request, job_id):
    """
    GET /api/jobs/{job_id}/images/
    List semua image dalam satu job.
    Query params:
      ?status=finished|in_review|in_rework|annotated|in_progress   (opsional)
    """
    err = reviewer_only(request)
    if err:
        return err

    job    = get_object_or_404(JobProfile, id=job_id, worker_reviewer=request.user)
    images = JobImage.objects.filter(job=job).select_related('annotator').order_by('id')

    status_filter = request.query_params.get('status')
    if status_filter:
        images = images.filter(status=status_filter)

    serializer = JobImageListSerializer(images, many=True, context={'request': request})
    return Response({
        'job_id':       job.id,
        'job_title':    job.title,
        'total_images': images.count(),
        'images':       serializer.data,
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_image_detail(request, image_id):
    """
    GET /api/images/{image_id}/
    Detail image lengkap: annotations, polygon points, dan daftar issue.
    """
    err = reviewer_only(request)
    if err:
        return err

    image = get_object_or_404(
        JobImage,
        id=image_id,
        job__worker_reviewer=request.user,
    )
    serializer = JobImageDetailSerializer(image, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_image_finish(request, image_id):
    """
    POST /api/images/{image_id}/finish/
    Mark satu image sebagai finished.
    Jika semua image dalam job sudah finished → job otomatis di-set finish.
    """
    err = reviewer_only(request)
    if err:
        return err

    image = get_object_or_404(
        JobImage,
        id=image_id,
        job__worker_reviewer=request.user,
    )

    # Jika image sudah berstatus finished, langsung return respons bersih
    if image.status == 'finished':
        return Response(
            {'message': 'Image sudah berstatus finished.'},
            status=status.HTTP_200_OK,
        )

    # Update status image saat ini
    image.status      = 'finished'
    image.review_time = timezone.now() - image.updated_at
    image.save()

    # Logika internal backend untuk otomatis menyelesaikan Job tetap berjalan di database
    job            = image.job
    total          = JobImage.objects.filter(job=job).count()
    finished_count = JobImage.objects.filter(job=job, status='finished').count()

    # Jika semua image sudah selesai, status job utama berubah jadi 'finish'
    if total == finished_count:
        job.status = 'finish'
        job.save()

    # Respons JSON di bawah ini sekarang bersih tanpa membawa field job_completed
    return Response({
        'message':       'Image berhasil di-finish.',
        'image_status':  image.status,
    }, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────
# ISSUES
# ─────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_issue_list(request):
    """
    GET /api/issues/
    List semua issue dari job yang di-review oleh user ini.
    Query params:
      ?status=open|reworking|closed|eskalasi
      ?priority=low|medium|high
      ?job_id=<int>
    """
    err = reviewer_only(request)
    if err:
        return err

    qs = (
        Issue.objects
        .filter(job__worker_reviewer=request.user)
        .select_related('job', 'image', 'assigned_to', 'created_by')
        .order_by('-created_at')
    )

    status_filter   = request.query_params.get('status')
    priority_filter = request.query_params.get('priority')
    job_filter      = request.query_params.get('job_id')

    if status_filter:
        qs = qs.filter(status=status_filter)
    if priority_filter:
        qs = qs.filter(priority=priority_filter)
    if job_filter:
        qs = qs.filter(job_id=job_filter)

    serializer = IssueListSerializer(qs, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_issue_create(request):
    """
    POST /api/issues/
    Body:
      {
        "image_id":    <int>,
        "title":       "...",          (opsional)
        "description": "...",
        "priority":    "low|medium|high"
      }
    - Set image → status: in_rework
    - Kirim notifikasi ke annotator
    """
    err = reviewer_only(request)
    if err:
        return err

    serializer = IssueCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data     = serializer.validated_data
    image_id = data['image_id']
    image    = get_object_or_404(JobImage, id=image_id)

    # Pastikan reviewer ini yang handle job-nya
    if image.job.worker_reviewer != request.user:
        return Response(
            {'error': 'Kamu bukan reviewer untuk job ini.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Tentukan annotator target
    annotator = image.annotator or image.job.worker_annotator
    if not annotator:
        return Response(
            {'error': 'Tidak ada annotator yang ter-assign di gambar ini.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    title = data.get('title') or f'Issue on image {image_id}'

    # Buat issue
    issue = Issue.objects.create(
        job         = image.job,
        image       = image,
        assigned_to = annotator,
        created_by  = request.user,
        title       = title,
        description = data['description'],
        priority    = data['priority'],
        status      = 'open',
    )

    # Set image ke in_rework
    image.status = 'in_rework'
    image.save()

    # Notifikasi annotator
    Notification.objects.create(
        recipient         = annotator,
        sender            = request.user,
        notification_type = 'issue_created',
        title             = f'Issue baru di "{image.job.title}"',
        message           = f'Reviewer {request.user.username} kasih feedback: {data["description"][:140]}',
        job               = image.job,
        issue             = issue,
    )

    return Response({
        'message':  'Issue berhasil dibuat dan annotator sudah dinotifikasi.',
        'issue_id': issue.id,
        'issue':    IssueListSerializer(issue).data,
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_issue_detail(request, issue_id):
    """
    GET /api/issues/{issue_id}/
    Detail satu issue.
    """
    err = reviewer_only(request)
    if err:
        return err

    issue = get_object_or_404(
        Issue,
        id=issue_id,
        job__worker_reviewer=request.user,
    )
    serializer = IssueListSerializer(issue)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def api_issue_update(request, issue_id):
    """
    PATCH /api/issues/{issue_id}/
    Body: { "status": "open|reworking|closed" }
    Update status issue.
    """
    err = reviewer_only(request)
    if err:
        return err

    issue = get_object_or_404(
        Issue,
        id=issue_id,
        job__worker_reviewer=request.user,
    )

    serializer = IssueUpdateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    new_status   = serializer.validated_data['status']
    issue.status = new_status
    issue.save()

    return Response({
        'message':    f'Status issue #{issue.id} berhasil diubah ke "{new_status}".',
        'issue_id':   issue.id,
        'new_status': issue.status,
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_issue_summary(request):
    """
    GET /api/issues/summary/
    Aggregate count issue: total, open, reworking, closed.
    Scope: hanya issue dari job reviewer yang login.
    """
    err = reviewer_only(request)
    if err:
        return err

    qs = Issue.objects.filter(job__worker_reviewer=request.user)

    data = {
        'total':    qs.count(),
        'open':     qs.filter(status='open').count(),
        'reworking': qs.filter(status='reworking').count(),
        'closed':   qs.filter(status='closed').count(),
    }
    return Response(data, status=status.HTTP_200_OK)