from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from master.models import (
    CustomUser,
    Dataset,
    Issue,
    IssueComment,
    JobImage,
    JobProfile,
    Notification,
    Project,
    ProjectMember,
)
from master.serializers import (
    AssignWorkersSerializer,
    IssueDecisionSerializer,
    MasterIssueMobileSerializer,
    PerformanceMemberSerializer,
    PublishDatasetSerializer,
    TeamStatusSerializer,
)


def get_master_project(request):
    project_uuid = request.query_params.get('project_id') or request.data.get('project_id')
    if not project_uuid:
        return None, Response({'error': 'project_id wajib diisi.'}, status=status.HTTP_400_BAD_REQUEST)

    project = get_object_or_404(Project, unique_id=project_uuid)
    if request.user.role == 'master':
        return project, None

    is_master = ProjectMember.objects.filter(project=project, user=request.user, role='master').exists()
    if not is_master:
        return None, Response({'error': 'Akses hanya untuk master project ini.'}, status=status.HTTP_403_FORBIDDEN)
    return project, None


def _job_stats(project):
    jobs = JobProfile.objects.filter(project=project)
    images = JobImage.objects.filter(job__project=project)
    issues = Issue.objects.filter(job__project=project)
    return {
        'total_jobs': jobs.count(),
        'jobs_not_assigned': jobs.filter(status='not_assign').count(),
        'jobs_in_progress': jobs.filter(status='in_progress').count(),
        'jobs_in_review': jobs.filter(status='in_review').count(),
        'jobs_finished': jobs.filter(status='finish').count(),
        'total_images': images.count(),
        'images_unannotated': images.filter(status='unannotated').count(),
        'images_in_progress': images.filter(status='in_progress').count(),
        'images_annotated': images.filter(status='annotated').count(),
        'images_in_review': images.filter(status='in_review').count(),
        'images_in_rework': images.filter(status='in_rework').count(),
        'images_finished': images.filter(status='finished').count(),
        'images_with_issues': images.filter(status='issue').count(),
        'total_issues': issues.count(),
        'issues_open': issues.filter(status='open').count(),
        'issues_eskalasi': issues.filter(status='eskalasi').count(),
        'issues_reworking': issues.filter(status='reworking').count(),
        'issues_closed': issues.filter(status='closed').count(),
        'issues_high_priority': issues.filter(priority='high', status__in=['open', 'eskalasi', 'reworking']).count(),
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_dashboard_summary(request):
    project, err = get_master_project(request)
    if err:
        return err
    data = _job_stats(project)
    data['project'] = {'id': project.id, 'unique_id': str(project.unique_id), 'name': project.name}
    data['total_members'] = ProjectMember.objects.filter(project=project).count()
    return Response(data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_team_status(request):
    project, err = get_master_project(request)
    if err:
        return err

    members = CustomUser.objects.filter(
        project_memberships__project=project,
        project_memberships__role__in=['annotator', 'reviewer'],
    ).distinct().order_by('email')
    roles = dict(ProjectMember.objects.filter(project=project, user__in=members).values_list('user_id', 'role'))

    rows = []
    for user in members:
        role = roles.get(user.id)
        if role == 'annotator':
            active_jobs = JobProfile.objects.filter(project=project, worker_annotator=user, status='in_progress').count()
            total_jobs = JobProfile.objects.filter(project=project, worker_annotator=user).count()
        elif role == 'reviewer':
            active_jobs = JobProfile.objects.filter(project=project, worker_reviewer=user, status__in=['in_progress', 'in_review']).count()
            total_jobs = JobProfile.objects.filter(project=project, worker_reviewer=user).count()
        else:
            active_jobs = 0
            total_jobs = 0

        if active_jobs:
            member_status = 'In Job'
        elif total_jobs:
            member_status = 'Ready'
        else:
            member_status = 'Not Ready'

        rows.append({
            'id': user.id,
            'email': user.email,
            'name': f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email,
            'role': role,
            'status': member_status,
            'active_jobs': active_jobs,
            'total_jobs': total_jobs,
        })

    return Response({'team': TeamStatusSerializer(rows, many=True).data}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_assign_workers(request):
    project, err = get_master_project(request)
    if err:
        return err

    serializer = AssignWorkersSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    job = get_object_or_404(JobProfile, id=data['job_id'], project=project)
    annotator = get_object_or_404(CustomUser, id=data['annotator_id'])
    reviewer = get_object_or_404(CustomUser, id=data['reviewer_id'])

    if not ProjectMember.objects.filter(project=project, user=annotator, role='annotator').exists():
        return Response({'error': 'Annotator is not a member of this project'}, status=status.HTTP_403_FORBIDDEN)
    if not ProjectMember.objects.filter(project=project, user=reviewer, role='reviewer').exists():
        return Response({'error': 'Reviewer is not a member of this project'}, status=status.HTTP_403_FORBIDDEN)

    job.worker_annotator = annotator
    job.worker_reviewer = reviewer
    job.status = 'in_progress'
    job.save(update_fields=['worker_annotator', 'worker_reviewer', 'status'])

    Notification.objects.create(
        recipient=annotator,
        sender=request.user,
        notification_type='job_assigned',
        title=f"Annotate project: {job.title}",
        message=f"You have been assigned a new annotation job: {job.title}.",
        job=job,
        status='unread',
    )

    return Response({
        'status': 'success',
        'job_id': job.id,
        'annotator_name': annotator.email,
        'reviewer_name': reviewer.email,
        'new_status': job.status,
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_performance_report(request):
    project, err = get_master_project(request)
    if err:
        return err

    members = CustomUser.objects.filter(
        project_memberships__project=project,
        project_memberships__role__in=['annotator', 'reviewer'],
    ).distinct().order_by('email')

    rows = []
    for user in members:
        membership = ProjectMember.objects.filter(
            project=project,
            user=user,
            role__in=['annotator', 'reviewer'],
        ).first()
        role = membership.role if membership else user.role
        project_count = JobProfile.objects.filter(project=project, worker_annotator=user).count()
        if role == 'reviewer':
            project_count = JobProfile.objects.filter(project=project, worker_reviewer=user).count()
        rows.append({
            'id': user.id,
            'email': user.email,
            'phone_number': user.phone_number or '-',
            'role': dict(ProjectMember.ROLE_CHOICES).get(role, role),
            'project_count': project_count,
            'group': '-',
        })

    stats = _job_stats(project)
    total_images = stats['total_images']
    finished = stats['images_finished']
    return Response({
        'members': PerformanceMemberSerializer(rows, many=True).data,
        'status_counts': {
            'unannotated': stats['images_unannotated'],
            'assigned': total_images - stats['images_unannotated'],
            'in_review': stats['images_in_review'],
            'in_rework': stats['images_in_rework'],
            'finished': finished,
            'issues': stats['images_with_issues'],
        },
        'total_images': total_images,
        'completion_percentage': round((finished / total_images) * 100) if total_images else 0,
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def api_publish_dataset(request):
    project, err = get_master_project(request)
    if err:
        return err

    serializer = PublishDatasetSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    job = get_object_or_404(JobProfile, id=data['job_id'], project=project)

    dataset = Dataset.objects.create(
        project=project,
        name=data['name'],
        description=data.get('description') or '',
        labeler=request.user,
        file_path=data['dataset_file'],
        status_publikasi='pending',
        annotation_type=job.get_shape_type_display(),
        count=JobImage.objects.filter(job=job).count(),
    )

    return Response({
        'status': 'success',
        'message': 'Dataset berhasil dikirim! Menunggu ulasan dari Komisi.',
        'dataset_id': dataset.id,
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_issue_list(request):
    project, err = get_master_project(request)
    if err:
        return err

    qs = Issue.objects.filter(job__project=project).select_related('job', 'image', 'assigned_to', 'created_by')
    issue_status = request.query_params.get('status')
    if issue_status:
        qs = qs.filter(status=issue_status)
    return Response(MasterIssueMobileSerializer(qs, many=True).data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_issue_decide(request, issue_id):
    project, err = get_master_project(request)
    if err:
        return err

    issue = get_object_or_404(Issue, id=issue_id, job__project=project)
    serializer = IssueDecisionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    decision = serializer.validated_data['decision']
    note = serializer.validated_data.get('note', '').strip()

    if decision == 'reopen' and issue.status != 'closed':
        return Response({'error': 'Reopen cuma untuk issue closed.'}, status=status.HTTP_400_BAD_REQUEST)
    if decision != 'reopen' and issue.status == 'closed':
        return Response({'error': "Issue sudah closed. Pakai decision 'reopen'."}, status=status.HTTP_400_BAD_REQUEST)

    label = decision.replace('_', ' ').upper()
    message = f"[MASTER DECISION: {label}]"
    if note:
        message += f"\n\n{note}"
    IssueComment.objects.create(issue=issue, created_by=request.user, message=message)

    if decision == 'side_annotator':
        issue.status = 'closed'
        issue.resolved_at = timezone.now()
        if issue.image:
            issue.image.status = 'finished'
            issue.image.save(update_fields=['status', 'updated_at'])
    elif decision == 'side_reviewer':
        issue.status = 'reworking'
        issue.resolved_at = None
        if issue.image:
            issue.image.status = 'in_rework'
            issue.image.save(update_fields=['status', 'updated_at'])
    elif decision == 'needs_clarification':
        for recipient, title, msg in [
            (
                issue.assigned_to,
                f"Issue #{issue.id}: clarification dari master",
                "Master perlu info tambahan. Cek comment thread.",
            ),
            (
                issue.created_by,
                f"Issue #{issue.id}: clarification dari master",
                "Master perlu info tambahan. Cek comment thread.",
            ),
        ]:
            if recipient and recipient != request.user:
                Notification.objects.create(
                    recipient=recipient,
                    sender=request.user,
                    notification_type='issue_clarification',
                    title=title,
                    message=msg,
                    issue=issue,
                    job=issue.job,
                )
    elif decision == 'close_issue':
        issue.status = 'closed'
        issue.resolved_at = timezone.now()
    elif decision == 'reopen':
        issue.status = 'open'
        issue.resolved_at = None

    issue.save()
    if decision != 'needs_clarification':
        for recipient in [issue.assigned_to, issue.created_by]:
            if recipient and recipient != request.user:
                Notification.objects.create(
                    recipient=recipient,
                    sender=request.user,
                    notification_type='issue_updated',
                    title=f'Issue #{issue.id} updated by master',
                    message=message,
                    issue=issue,
                    job=issue.job,
                )

    return Response(MasterIssueMobileSerializer(issue).data, status=status.HTTP_200_OK)
