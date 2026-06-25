from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from master.models import JobProfile, JobImage, Annotation, PolygonPoint,Notification
from .serializers import *
from django.shortcuts import get_object_or_404

#dashboard
class DashboardAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        jobs = JobProfile.objects.filter(worker_annotator=user)

        total = jobs.count()
        in_progress = jobs.filter(status='in_progress').count()
        finished = jobs.filter(status='finish').count()
        not_started = jobs.filter(status='not_assign').count()

        return Response({
            "total_jobs": total,
            "in_progress": in_progress,
            "finished": finished,
            "not_started": not_started
        })

class MyJobsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        jobs = JobProfile.objects.filter(worker_annotator=request.user)
        serializer = JobSerializer(jobs, many=True)
        return Response(serializer.data)


class JobImagesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, job_id):
        images = JobImage.objects.filter(job_id=job_id)
        serializer = JobImageSerializer(images, many=True)
        return Response(serializer.data)


class AnnotationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        image_id = request.data.get('image_id')
        label = request.data.get('label')

        annotation = Annotation.objects.create(
            job_image_id=image_id,
            label=label,
            annotator=request.user
        )

        # polygon
        points = request.data.get('points')
        if points:
            for i, p in enumerate(points):
                PolygonPoint.objects.create(
                    segmentation=annotation.segmentation,
                    x=p['x'],
                    y=p['y'],
                    order_index=i
                )

        return Response({'message': 'saved'})
    
    # ===============
    # NOTIFIKASI
    # ===============
    
#notifikasi anatator
class NotificationListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        notifications = Notification.objects.filter(
            recipient=request.user
        ).order_by('-created_at')

        serializer = NotificationSerializer(notifications, many=True)

        return Response({
            "count": notifications.count(),
            "data": serializer.data
        })
        
#notif dibaca
class MarkNotificationAsReadAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, id):
        try:
            notif = Notification.objects.get(
                id=id,
                recipient=request.user  # biar aman (user cuma bisa akses notif dia)
            )
        except Notification.DoesNotExist:
            return Response(
                {"error": "Notification tidak ditemukan"},
                status=status.HTTP_404_NOT_FOUND
            )
            
        notif.mark_as_read()

        return Response({
            "message": "Notification berhasil ditandai sebagai dibaca",
            "id": notif.id,
            "status": notif.status
        }, status=status.HTTP_200_OK)

# BELUM DIBACA
class UnreadNotificationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        notifications = Notification.objects.filter(
            recipient=request.user,
            status='unread'
        ).order_by('-created_at')

        serializer = NotificationSerializer(notifications, many=True)

        return Response({
            "count": notifications.count(),
            "data": serializer.data
        })
        
#LABEL

class LabeledDataDetailAPIView(APIView):
    # Pastikan endpoint aman
    permission_classes = [IsAuthenticated]

    def get(self, request, image_id):
        # Cari gambar berdasarkan ID
        job_image = get_object_or_404(JobImage, id=image_id)
        
        # Masukkan request ke context agar build_absolute_uri di get_image_url berfungsi
        serializer = JobImageSerializer(job_image, context={'request': request})
        
        return Response({
            "message": "Data gambar dan anotasi berhasil diambil",
            "data": serializer.data
        }, status=status.HTTP_200_OK)