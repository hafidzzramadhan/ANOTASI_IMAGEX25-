"""
API Issue Solving untuk MASTER role.

Master arbitrate kalo ada eskalasi dari annotator/reviewer.
Flow:
    Reviewer reject → Issue 'open' (assigned ke annotator)
    Annotator dispute → Issue 'eskalasi' (assigned ke master)
    Master decide → Issue 'closed' / back to 'open'

Endpoint:
- GET  /api/master/issues/<id>/                detail issue + comments + image
- POST /api/master/issues/<id>/decide/         master decide eskalasi
- GET  /api/master/issues/<id>/comments/       list comments di thread
- POST /api/master/issues/<id>/comments/       add comment

Pasang:
1. Copy file ini ke `master/api_issue_solving.py`
2. Tambahin route di `master/api_urls.py` (lihat README)
"""
from rest_framework import permissions, generics, status as drf_status, serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils import timezone

from master.models import (
    Issue, IssueComment, JobImage, Notification, CustomUser
)
from master.api_master_views import IsMaster


# ============================================================
# SERIALIZERS
# ============================================================

class IssueCommentSerializer(serializers.ModelSerializer):
    """Buat comment thread di issue."""
    author_name = serializers.CharField(source='created_by.username', read_only=True)
    author_role = serializers.CharField(source='created_by.role', read_only=True)
    time_ago = serializers.SerializerMethodField()

    class Meta:
        model = IssueComment
        fields = ['id', 'message', 'author_name', 'author_role', 'created_at', 'time_ago']
        read_only_fields = ['author_name', 'author_role', 'created_at', 'time_ago']

    def get_time_ago(self, obj):
        from django.utils.timesince import timesince
        return f"{timesince(obj.created_at)} ago"


class IssueDetailSerializer(serializers.ModelSerializer):
    """Full detail issue — buat master review sebelum decide."""
    job_title = serializers.CharField(source='job.title', read_only=True)
    image_url = serializers.SerializerMethodField()
    image_status = serializers.CharField(source='image.status', read_only=True, allow_null=True)
    assigned_to_name = serializers.CharField(source='assigned_to.username', read_only=True)
    assigned_to_role = serializers.CharField(source='assigned_to.role', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    created_by_role = serializers.CharField(source='created_by.role', read_only=True)
    comments = IssueCommentSerializer(many=True, read_only=True)
    comment_count = serializers.SerializerMethodField()

    class Meta:
        model = Issue
        fields = [
            'id', 'title', 'description', 'status', 'priority',
            'job', 'job_title',
            'image', 'image_url', 'image_status',
            'assigned_to', 'assigned_to_name', 'assigned_to_role',
            'created_by', 'created_by_name', 'created_by_role',
            'annotation_id',
            'created_at', 'updated_at', 'resolved_at',
            'comments', 'comment_count',
        ]

    def get_image_url(self, obj):
        if obj.image and obj.image.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.image.url)
            return obj.image.image.url
        return None

    def get_comment_count(self, obj):
        return obj.comments.count()


class IssueDecideSerializer(serializers.Serializer):
    """
    Body buat POST /api/master/issues/<id>/decide/

    decision:
      - side_annotator      → annotator benar, issue closed, image finished
      - side_reviewer       → reviewer benar, annotator harus rework
      - needs_clarification → keep status, master cuma kasi note
      - close_issue         → tutup issue tanpa side (admin override)
      - reopen              → buka kembali issue closed
    """
    DECISION_CHOICES = [
        ('side_annotator', 'Side with Annotator'),
        ('side_reviewer', 'Side with Reviewer'),
        ('needs_clarification', 'Needs Clarification'),
        ('close_issue', 'Close Issue (admin override)'),
        ('reopen', 'Reopen Issue'),
    ]
    decision = serializers.ChoiceField(choices=DECISION_CHOICES)
    note = serializers.CharField(
        required=False, allow_blank=True, max_length=2000,
        help_text="Penjelasan keputusan (jadi comment di thread)"
    )


class IssueCommentCreateSerializer(serializers.Serializer):
    """Body buat POST /api/master/issues/<id>/comments/"""
    message = serializers.CharField(min_length=1, max_length=2000)


# ============================================================
# VIEWS
# ============================================================

class MasterIssueDetailAPIView(generics.RetrieveAPIView):
    """
    GET /api/master/issues/<id>/

    Full detail issue: title, desc, status, priority, comments thread,
    image preview, parties involved.
    """
    permission_classes = [permissions.IsAuthenticated, IsMaster]
    serializer_class = IssueDetailSerializer
    queryset = Issue.objects.select_related(
        'job', 'image', 'assigned_to', 'created_by'
    ).prefetch_related('comments__created_by')
    lookup_field = 'pk'


class MasterIssueDecideAPIView(APIView):
    """
    POST /api/master/issues/<id>/decide/

    Body:
    {
        "decision": "side_annotator" | "side_reviewer" | "needs_clarification",
        "note": "Penjelasan optional"
    }

    Effect:
    - side_annotator    → issue.status = 'closed', image.status = 'finished'
    - side_reviewer     → issue.status = 'open', image.status = 'in_rework'
    - needs_clarification → keep 'eskalasi', cuma add note + notif
    """
    permission_classes = [permissions.IsAuthenticated, IsMaster]

    def post(self, request, pk):
        issue = get_object_or_404(Issue, pk=pk)

        serializer = IssueDecideSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision = serializer.validated_data['decision']
        note = serializer.validated_data.get('note', '').strip()

        # Validasi: reopen cuma valid kalo udah closed
        if decision == 'reopen' and issue.status != 'closed':
            return Response({
                'detail': f"Issue #{issue.id} masih aktif (status '{issue.status}'). Reopen cuma buat issue 'closed'."
            }, status=drf_status.HTTP_400_BAD_REQUEST)

        # Validasi: decision lain selain reopen butuh issue masih aktif
        if decision != 'reopen' and issue.status == 'closed':
            return Response({
                'detail': f"Issue #{issue.id} udah closed. Pake decision 'reopen' kalo mau buka lagi."
            }, status=drf_status.HTTP_400_BAD_REQUEST)

        # Tambahin comment dari master (track decision di thread)
        decision_label = dict(IssueDecideSerializer.DECISION_CHOICES)[decision]
        comment_msg = f"[MASTER DECISION: {decision_label}]"
        if note:
            comment_msg += f"\n\n{note}"
        IssueComment.objects.create(
            issue=issue,
            created_by=request.user,
            message=comment_msg,
        )

        # Apply decision logic
        if decision == 'side_annotator':
            # Annotator benar — close issue + finalize image
            issue.status = 'closed'
            issue.resolved_at = timezone.now()
            issue.save()

            if issue.image:
                issue.image.status = 'finished'
                issue.image.save(update_fields=['status', 'updated_at'])

            self._notif(
                issue, request.user, 'issue_resolved',
                annotator_title=f"Issue #{issue.id} resolved",
                annotator_msg="Master sided with you. Issue ditutup ✓",
                reviewer_title=f"Issue #{issue.id} resolved",
                reviewer_msg="Master sided with annotator. Annotation diterima.",
            )

        elif decision == 'side_reviewer':
            # Reviewer benar — annotator harus rework
            issue.status = 'reworking'
            issue.save()

            if issue.image:
                issue.image.status = 'in_rework'
                issue.image.save(update_fields=['status', 'updated_at'])

            self._notif(
                issue, request.user, 'issue_rework',
                annotator_title=f"Issue #{issue.id}: rework required",
                annotator_msg="Master sided with reviewer. Tolong rework annotation.",
                reviewer_title=f"Issue #{issue.id} sided with you",
                reviewer_msg="Master sided with you. Annotator akan rework.",
            )

        elif decision == 'needs_clarification':
            # Keep status, master cuma kasi note → tunggu response
            self._notif(
                issue, request.user, 'issue_clarification',
                annotator_title=f"Issue #{issue.id}: clarification dari master",
                annotator_msg="Master perlu info tambahan. Cek comment thread.",
                reviewer_title=f"Issue #{issue.id}: clarification dari master",
                reviewer_msg="Master perlu info tambahan. Cek comment thread.",
            )

        elif decision == 'close_issue':
            # Admin override — close paksa
            issue.status = 'closed'
            issue.resolved_at = timezone.now()
            issue.save()
            self._notif(
                issue, request.user, 'issue_closed',
                annotator_title=f"Issue #{issue.id}: closed by master",
                annotator_msg="Master tutup issue ini secara langsung.",
                reviewer_title=f"Issue #{issue.id}: closed by master",
                reviewer_msg="Master tutup issue ini secara langsung.",
            )

        elif decision == 'reopen':
            # Buka kembali issue closed
            issue.status = 'open'
            issue.resolved_at = None
            issue.save()
            self._notif(
                issue, request.user, 'issue_reopened',
                annotator_title=f"Issue #{issue.id}: dibuka kembali",
                annotator_msg="Master buka kembali issue ini.",
                reviewer_title=f"Issue #{issue.id}: dibuka kembali",
                reviewer_msg="Master buka kembali issue ini.",
            )

        detail = IssueDetailSerializer(issue, context={'request': request})
        return Response(detail.data, status=drf_status.HTTP_200_OK)

    def _notif(self, issue, sender, notif_type,
               annotator_title, annotator_msg,
               reviewer_title, reviewer_msg):
        """Helper bikin notif ke 2 parties."""
        # Notif ke annotator (assigned_to)
        if issue.assigned_to and issue.assigned_to != sender:
            Notification.objects.create(
                recipient=issue.assigned_to,
                sender=sender,
                notification_type=notif_type,
                title=annotator_title,
                message=annotator_msg,
                issue=issue,
                job=issue.job,
            )
        # Notif ke reviewer (created_by issue)
        if issue.created_by and issue.created_by != sender:
            Notification.objects.create(
                recipient=issue.created_by,
                sender=sender,
                notification_type=notif_type,
                title=reviewer_title,
                message=reviewer_msg,
                issue=issue,
                job=issue.job,
            )


class MasterIssueCommentAPIView(APIView):
    """
    GET  /api/master/issues/<id>/comments/   - list comments di thread
    POST /api/master/issues/<id>/comments/   - add comment baru

    POST body:
    {
        "message": "Isi comment lu..."
    }
    """
    permission_classes = [permissions.IsAuthenticated, IsMaster]

    def get(self, request, pk):
        issue = get_object_or_404(Issue, pk=pk)
        comments = issue.comments.select_related('created_by').order_by('created_at')
        serializer = IssueCommentSerializer(comments, many=True)
        return Response(serializer.data)

    def post(self, request, pk):
        issue = get_object_or_404(Issue, pk=pk)

        serializer = IssueCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        comment = IssueComment.objects.create(
            issue=issue,
            created_by=request.user,
            message=serializer.validated_data['message'],
        )

        # Notif ke parties (annotator + reviewer)
        for party in [issue.assigned_to, issue.created_by]:
            if party and party != request.user:
                Notification.objects.create(
                    recipient=party,
                    sender=request.user,
                    notification_type='issue_comment',
                    title=f"Comment baru di Issue #{issue.id}",
                    message=f"Master kasi comment: {comment.message[:80]}...",
                    issue=issue,
                    job=issue.job,
                )

        return Response(
            IssueCommentSerializer(comment).data,
            status=drf_status.HTTP_201_CREATED
        )