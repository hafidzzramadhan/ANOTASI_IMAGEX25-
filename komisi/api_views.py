import zipfile

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from master.auth_utils import is_email_verified
from master.models import Dataset, JobImage
from .serializers import DatasetKomisiSerializer, LoginSerializer, ReviewDatasetSerializer, TakedownDatasetSerializer


def komisi_only(request):
    user = request.user
    if not (user and user.is_authenticated):
        return Response({'error': 'Authentication required.'}, status=status.HTTP_401_UNAUTHORIZED)
    if user.role != 'komisi':
        return Response({'error': 'Akses hanya untuk Komisi.'}, status=status.HTTP_403_FORBIDDEN)
    if not user.is_active or not is_email_verified(user):
        return Response({'error': 'Email akun Komisi belum diverifikasi.'}, status=status.HTTP_403_FORBIDDEN)
    if user.komisi_approval_status != 'approved':
        return Response({'error': 'Akun Komisi belum disetujui admin.'}, status=status.HTTP_403_FORBIDDEN)
    return None


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
def api_dataset_list(request):
    err = komisi_only(request)
    if err:
        return err

    status_filter = request.query_params.get('status', 'pending')
    allowed = ['pending', 'published', 'rejected', 'taken_down', 'history', 'all']
    if status_filter not in allowed:
        return Response({'error': f'status harus salah satu dari: {", ".join(allowed)}'}, status=status.HTTP_400_BAD_REQUEST)

    qs = Dataset.objects.select_related('project', 'labeler', 'reviewed_by', 'taken_down_by').prefetch_related('comments__user')
    if status_filter == 'history':
        qs = qs.filter(reviewed_by__isnull=False) | qs.filter(taken_down_by__isnull=False)
    elif status_filter != 'all':
        qs = qs.filter(status_publikasi=status_filter)
    qs = qs.order_by('-date_created')

    return Response({
        'datasets': DatasetKomisiSerializer(qs, many=True, context={'request': request}).data
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_dataset_detail(request, dataset_id):
    err = komisi_only(request)
    if err:
        return err

    dataset = get_object_or_404(
        Dataset.objects.select_related('project', 'labeler', 'reviewed_by', 'taken_down_by').prefetch_related('comments__user'),
        id=dataset_id,
    )
    images = []
    if dataset.project_id:
        images = JobImage.objects.filter(job__project=dataset.project).order_by('id')[:15]
        images = [
            {
                'id': image.id,
                'status': image.status,
                'image_url': request.build_absolute_uri(image.image.url) if image.image else None,
            }
            for image in images
        ]

    return Response({
        'dataset': DatasetKomisiSerializer(dataset, context={'request': request}).data,
        'preview_images': images,
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_dataset_review(request, dataset_id):
    err = komisi_only(request)
    if err:
        return err

    dataset = get_object_or_404(Dataset, id=dataset_id, status_publikasi='pending')
    serializer = ReviewDatasetSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    dataset.rating = data.get('rating')
    dataset.komisi_feedback = data.get('feedback')
    dataset.reviewed_by = request.user
    dataset.reviewed_at = timezone.now()
    dataset.status_publikasi = 'published' if data['action'] == 'approve' else 'rejected'
    dataset.save()

    return Response({
        'status': 'success',
        'message': f"Dataset '{dataset.name}' {'dipublikasikan' if data['action'] == 'approve' else 'ditolak'}.",
        'dataset': DatasetKomisiSerializer(dataset, context={'request': request}).data,
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_dataset_takedown(request, dataset_id):
    err = komisi_only(request)
    if err:
        return err

    dataset = get_object_or_404(Dataset, id=dataset_id, status_publikasi='published')
    serializer = TakedownDatasetSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    dataset.status_publikasi = 'taken_down'
    dataset.taken_down_by = request.user
    dataset.taken_down_at = timezone.now()
    dataset.takedown_reason = serializer.validated_data['reason']
    dataset.save()

    return Response({
        'status': 'success',
        'message': f"Dataset '{dataset.name}' berhasil ditarik dari publik.",
        'dataset': DatasetKomisiSerializer(dataset, context={'request': request}).data,
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_dataset_content(request, dataset_id):
    err = komisi_only(request)
    if err:
        return err

    dataset = get_object_or_404(Dataset, id=dataset_id)
    file_list = []
    try:
        with dataset.file_path.open('rb') as dataset_file:
            with zipfile.ZipFile(dataset_file, 'r') as zip_ref:
                file_list = zip_ref.namelist()[:25]
    except Exception as exc:
        return Response({'status': 'error', 'message': str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({'files': file_list}, status=status.HTTP_200_OK)
