import json

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from master.models import (
    Annotation,
    Issue,
    IssueComment,
    JobImage,
    JobProfile,
    MasterLabel,
    Notification,
    ProjectMember,
)
from .serializers import (
    AnnotationSaveSerializer,
    AnnotationSerializer,
    IssueListSerializer,
    JobImageDetailSerializer,
    JobImageListSerializer,
    JobProfileDetailSerializer,
    JobProfileListSerializer,
    LoginSerializer,
    MasterLabelSerializer,
    NotificationSerializer,
)


def annotator_only(request):
    user = request.user
    if user.role in ('annotator', 'master'):
        return None

    project_uuid = request.query_params.get('project_id') or request.data.get('project_id')
    if project_uuid and ProjectMember.objects.filter(
        project__unique_id=project_uuid,
        user=user,
        role__in=('annotator', 'master'),
    ).exists():
        return None

    return Response(
        {'error': 'Akses hanya untuk annotator.'},
        status=status.HTTP_403_FORBIDDEN,
    )


def _project_filter(request):
    project_uuid = request.query_params.get('project_id') or request.data.get('project_id')
    if project_uuid:
        return {'project__unique_id': project_uuid}
    return {}


def _assigned_jobs(request):
    qs = JobProfile.objects.filter(worker_annotator=request.user)
    project_filter = _project_filter(request)
    if project_filter:
        qs = qs.filter(**project_filter)
    return qs


def _assigned_images(request):
    qs = JobImage.objects.filter(job__worker_annotator=request.user)
    project_filter = _project_filter(request)
    if project_filter:
        qs = qs.filter(job__project__unique_id=project_filter['project__unique_id'])
    return qs


@api_view(['POST'])
@permission_classes([AllowAny])
def api_login(request):
    serializer = LoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    user = serializer.validated_data['user']
    refresh = RefreshToken.for_user(user)
    return Response({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'username': user.username,
        'role': user.role,
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_logout(request):
    refresh_token = request.data.get('refresh')
    if not refresh_token:
        return Response({'error': 'Refresh token wajib diisi.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        RefreshToken(refresh_token).blacklist()
    except TokenError:
        return Response({'error': 'Token tidak valid atau sudah expired.'}, status=status.HTTP_400_BAD_REQUEST)
    return Response({'message': 'Logout berhasil.'}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_job_list(request):
    err = annotator_only(request)
    if err:
        return err

    qs = _assigned_jobs(request).order_by('-date_created')
    status_filter = request.query_params.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)

    serializer = JobProfileListSerializer(qs, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_job_detail(request, job_id):
    err = annotator_only(request)
    if err:
        return err

    job = get_object_or_404(_assigned_jobs(request), id=job_id)
    serializer = JobProfileDetailSerializer(job)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_image_list(request, job_id):
    err = annotator_only(request)
    if err:
        return err

    job = get_object_or_404(_assigned_jobs(request), id=job_id)
    images = JobImage.objects.filter(job=job).order_by('id')
    status_filter = request.query_params.get('status')
    if status_filter:
        images = images.filter(status=status_filter)

    serializer = JobImageListSerializer(images, many=True, context={'request': request})
    return Response({
        'job_id': job.id,
        'job_title': job.title,
        'total_images': images.count(),
        'images': serializer.data,
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_image_detail(request, image_id):
    err = annotator_only(request)
    if err:
        return err

    image = get_object_or_404(_assigned_images(request), id=image_id)
    serializer = JobImageDetailSerializer(image, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['POST', 'PATCH'])
@permission_classes([IsAuthenticated])
def api_annotation_save(request, image_id):
    err = annotator_only(request)
    if err:
        return err

    image = get_object_or_404(_assigned_images(request), id=image_id)
    serializer = AnnotationSaveSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    annotation_id = data.get('id')
    if annotation_id:
        annotation = get_object_or_404(Annotation, id=annotation_id, job_image=image)
    else:
        annotation = Annotation(
            job_image=image,
            image=image,
            annotator=request.user,
            created_by=request.user,
        )

    annotation.label = data.get('label')
    annotation.type = data.get('type', 'box')
    annotation.points = data.get('points')
    annotation.x_min = data.get('x_min')
    annotation.y_min = data.get('y_min')
    annotation.x_max = data.get('x_max')
    annotation.y_max = data.get('y_max')
    annotation.x_coordinate = data.get('x_min')
    annotation.y_coordinate = data.get('y_min')

    if data.get('x_max') is not None and data.get('x_min') is not None:
        annotation.width = data.get('x_max') - data.get('x_min')
    if data.get('y_max') is not None and data.get('y_min') is not None:
        annotation.height = data.get('y_max') - data.get('y_min')

    annotation.is_auto_generated = False
    annotation.notes = 'manual'
    annotation.save()

    image.status = 'in_progress'
    image.annotator = request.user
    image.save(update_fields=['status', 'annotator', 'updated_at'])

    return Response({
        'status': 'success',
        'annotation': AnnotationSerializer(annotation).data,
    }, status=status.HTTP_200_OK if annotation_id else status.HTTP_201_CREATED)


@api_view(['DELETE', 'POST'])
@permission_classes([IsAuthenticated])
def api_annotation_delete(request, image_id, annotation_id=None):
    err = annotator_only(request)
    if err:
        return err

    image = get_object_or_404(_assigned_images(request), id=image_id)
    annotation_id = annotation_id or request.data.get('id')
    if not annotation_id:
        return Response({'error': 'id annotation wajib diisi.'}, status=status.HTTP_400_BAD_REQUEST)

    deleted, _ = Annotation.objects.filter(id=annotation_id, job_image=image).delete()
    if not deleted:
        return Response({'error': 'Annotation tidak ditemukan.'}, status=status.HTTP_404_NOT_FOUND)

    return Response({'status': 'deleted'}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_image_finish(request, image_id):
    err = annotator_only(request)
    if err:
        return err

    image = get_object_or_404(_assigned_images(request), id=image_id)
    image.status = 'in_review'
    image.label_time = timezone.now() - image.updated_at
    image.annotator = request.user
    image.save(update_fields=['status', 'label_time', 'annotator', 'updated_at'])

    return Response({
        'success': True,
        'message': 'Annotation marked as finished and sent for review',
        'image_status': image.status,
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_issue_list(request):
    err = annotator_only(request)
    if err:
        return err

    qs = Issue.objects.filter(assigned_to=request.user).select_related('job', 'image', 'assigned_to', 'created_by')
    project_uuid = request.query_params.get('project_id')
    if project_uuid:
        qs = qs.filter(job__project__unique_id=project_uuid)
    status_filter = request.query_params.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)

    return Response(IssueListSerializer(qs, many=True).data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_issue_dispute(request, issue_id):
    err = annotator_only(request)
    if err:
        return err

    issue = get_object_or_404(Issue, id=issue_id, assigned_to=request.user)
    if issue.status != 'open':
        return Response({
            'status': 'error',
            'message': f'Issue ini statusnya "{issue.status}". Cuma issue "open" yang bisa di-dispute.',
        }, status=status.HTTP_400_BAD_REQUEST)

    reason = (request.data.get('reason') or '').strip()
    if not reason:
        return Response({'status': 'error', 'message': 'Alasan dispute wajib diisi.'}, status=status.HTTP_400_BAD_REQUEST)

    issue.status = 'eskalasi'
    issue.save(update_fields=['status', 'updated_at'])

    IssueComment.objects.create(
        issue=issue,
        created_by=request.user,
        message=f"[DISPUTE oleh annotator]\n\n{reason}",
    )

    masters = ProjectMember.objects.filter(project=issue.job.project, role='master').select_related('user')
    for pm in masters:
        Notification.objects.create(
            recipient=pm.user,
            sender=request.user,
            notification_type='issue_updated',
            title=f'Issue #{issue.id} di-eskalasi',
            message=f'{request.user.email} dispute issue "{issue.title}". Butuh keputusan kamu.',
            issue=issue,
            job=issue.job,
        )

    if issue.created_by and issue.created_by != request.user:
        Notification.objects.create(
            recipient=issue.created_by,
            sender=request.user,
            notification_type='issue_updated',
            title=f'Issue #{issue.id} di-dispute annotator',
            message='Annotator dispute issue ini. Menunggu keputusan master.',
            issue=issue,
            job=issue.job,
        )

    return Response({'status': 'success', 'message': 'Issue berhasil di-eskalasi ke master.'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_notification_list(request):
    qs = Notification.objects.filter(recipient=request.user).select_related('sender', 'job', 'issue')
    status_filter = request.query_params.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)
    return Response(NotificationSerializer(qs, many=True).data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_notification_accept(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, recipient=request.user)
    notification.status = 'accepted'
    notification.read_at = timezone.now()
    notification.save(update_fields=['status', 'read_at'])
    return Response({'status': 'success', 'message': 'Notification accepted successfully'})


class MasterLabelAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        labels = MasterLabel.objects.all()
        serializer = MasterLabelSerializer(labels, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        name = (request.data.get('name') or '').strip()
        if not name:
            return Response({'error': 'Nama label wajib diisi!'}, status=status.HTTP_400_BAD_REQUEST)
        color = request.data.get('color') or '#7C3AED'
        label, created = MasterLabel.objects.get_or_create(name=name, defaults={'color': color})
        return Response(
            MasterLabelSerializer(label).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
