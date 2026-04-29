"""
API Dashboards untuk role ANNOTATOR + REVIEWER (mobile app Flutter).

File ini berisi:
- IsAnnotator + IsReviewer permission classes
- AnnotatorDashboardSerializer + AnnotatorDashboardAPIView
- ReviewerDashboardSerializer  + ReviewerDashboardAPIView

Endpoint yang dipake:
- GET /api/annotator/dashboard/  (cuma role='annotator')
- GET /api/reviewer/dashboard/   (cuma role='reviewer')

Pasang di project lu:
1. Copy file ini ke `master/api_role_dashboards.py`
2. Tambahin 2 route di `master/api_urls.py` (lihat README)
"""
from rest_framework import permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import serializers
from django.db.models import Q

from master.models import (
    JobProfile, JobImage, Issue, Notification
)


# ============================================================
# CUSTOM PERMISSIONS
# ============================================================

class IsAnnotator(permissions.BasePermission):
    """Cuma user dengan role='annotator'."""
    message = "Cuma user dengan role 'annotator' yang boleh akses."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'role', None) == 'annotator'
        )


class IsReviewer(permissions.BasePermission):
    """Cuma user dengan role='reviewer'."""
    message = "Cuma user dengan role 'reviewer' yang boleh akses."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, 'role', None) == 'reviewer'
        )


# ============================================================
# SERIALIZERS (read-only stats)
# ============================================================

class AnnotatorDashboardSerializer(serializers.Serializer):
    """KPI cards buat annotator."""
    # Job stats
    total_jobs_assigned = serializers.IntegerField()
    jobs_in_progress = serializers.IntegerField()
    jobs_finished = serializers.IntegerField()

    # Image stats (yang di-assign ke gw sebagai annotator)
    total_images_assigned = serializers.IntegerField()
    images_unannotated = serializers.IntegerField()
    images_in_progress = serializers.IntegerField()
    images_in_rework = serializers.IntegerField()
    images_done = serializers.IntegerField()

    # Issue + Notif
    pending_issues = serializers.IntegerField()
    unread_notifications = serializers.IntegerField()


class ReviewerDashboardSerializer(serializers.Serializer):
    """KPI cards buat reviewer."""
    # Job stats
    total_jobs_assigned = serializers.IntegerField()
    jobs_in_progress = serializers.IntegerField()
    jobs_in_review = serializers.IntegerField()
    jobs_finished = serializers.IntegerField()

    # Image stats (image di job yang gw review)
    total_images_in_my_jobs = serializers.IntegerField()
    images_pending_review = serializers.IntegerField()
    images_reviewed = serializers.IntegerField()

    # Issue stats (yang gw bikin)
    total_issues_created = serializers.IntegerField()
    issues_open = serializers.IntegerField()
    issues_closed = serializers.IntegerField()

    # Notif
    unread_notifications = serializers.IntegerField()


# ============================================================
# DASHBOARD VIEWS
# ============================================================

class AnnotatorDashboardAPIView(APIView):
    """
    GET /api/annotator/dashboard/

    Response:
    {
        "total_jobs_assigned": 5,
        "jobs_in_progress": 3,
        "jobs_finished": 2,
        "total_images_assigned": 120,
        "images_unannotated": 40,
        "images_in_progress": 5,
        "images_in_rework": 2,
        "images_done": 73,
        "pending_issues": 3,
        "unread_notifications": 1
    }
    """
    permission_classes = [permissions.IsAuthenticated, IsAnnotator]

    def get(self, request):
        user = request.user

        # --- Job stats (jobs where I'm the annotator) ---
        my_jobs = JobProfile.objects.filter(worker_annotator=user)

        # --- Image stats (images assigned to me) ---
        my_images = JobImage.objects.filter(annotator=user)

        stats = {
            # Jobs
            'total_jobs_assigned': my_jobs.count(),
            'jobs_in_progress': my_jobs.filter(status='in_progress').count(),
            'jobs_finished': my_jobs.filter(status='finish').count(),

            # Images
            'total_images_assigned': my_images.count(),
            'images_unannotated': my_images.filter(status='unannotated').count(),
            'images_in_progress': my_images.filter(status='in_progress').count(),
            'images_in_rework': my_images.filter(status='in_rework').count(),
            'images_done': my_images.filter(
                status__in=['annotated', 'in_review', 'finished']
            ).count(),

            # Issues assigned to me (yang harus gw rework)
            'pending_issues': Issue.objects.filter(
                assigned_to=user,
                status__in=['open', 'reworking']
            ).count(),

            # Notif
            'unread_notifications': Notification.objects.filter(
                recipient=user, status='unread'
            ).count(),
        }

        serializer = AnnotatorDashboardSerializer(stats)
        return Response(serializer.data)


class ReviewerDashboardAPIView(APIView):
    """
    GET /api/reviewer/dashboard/

    Response:
    {
        "total_jobs_assigned": 4,
        "jobs_in_progress": 2,
        "jobs_in_review": 1,
        "jobs_finished": 1,
        "total_images_in_my_jobs": 80,
        "images_pending_review": 12,
        "images_reviewed": 45,
        "total_issues_created": 7,
        "issues_open": 3,
        "issues_closed": 4,
        "unread_notifications": 2
    }
    """
    permission_classes = [permissions.IsAuthenticated, IsReviewer]

    def get(self, request):
        user = request.user

        # --- Job stats (jobs where I'm the reviewer) ---
        my_jobs = JobProfile.objects.filter(worker_reviewer=user)

        # --- Image stats (images dalam job yang gw review) ---
        images_in_my_jobs = JobImage.objects.filter(job__worker_reviewer=user)

        # --- Issue stats (issues yang gw bikin) ---
        my_issues = Issue.objects.filter(created_by=user)

        stats = {
            # Jobs
            'total_jobs_assigned': my_jobs.count(),
            'jobs_in_progress': my_jobs.filter(status='in_progress').count(),
            'jobs_in_review': my_jobs.filter(status='in_review').count(),
            'jobs_finished': my_jobs.filter(status='finish').count(),

            # Images
            'total_images_in_my_jobs': images_in_my_jobs.count(),
            'images_pending_review': images_in_my_jobs.filter(status='in_review').count(),
            'images_reviewed': images_in_my_jobs.filter(status='finished').count(),

            # Issues
            'total_issues_created': my_issues.count(),
            'issues_open': my_issues.filter(
                status__in=['open', 'eskalasi', 'reworking']
            ).count(),
            'issues_closed': my_issues.filter(status='closed').count(),

            # Notif
            'unread_notifications': Notification.objects.filter(
                recipient=user, status='unread'
            ).count(),
        }

        serializer = ReviewerDashboardSerializer(stats)
        return Response(serializer.data)