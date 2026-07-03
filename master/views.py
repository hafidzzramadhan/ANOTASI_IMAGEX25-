from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.sites.shortcuts import get_current_site
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.contrib.auth import get_backends
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Count, Q, F
from django.db.models.functions import Coalesce
from django.core.exceptions import PermissionDenied
from django.db import transaction
from functools import wraps
from django.utils import timezone
import json
from .tokens import account_activation_token
from .models import (
    CustomUser,
    Dataset,
    Issue,
    JobProfile,
    JobImage,
    Notification,
    Project,
    ProjectInvite,
    ProjectMember,
)
from .forms import SignUpForm

def create_job_notification(job, recipient, sender):
    """
    Helper function to create notification when job is assigned
    """
    notification = Notification.objects.create(
        recipient=recipient,
        sender=sender,
        notification_type='job_assigned',
        title=f"Annotate project: {job.title}",
        message=f"You have been assigned a new annotation job: {job.title}. Please start working on it as soon as possible.",
        job=job,
        status='unread'
    )
    return notification

import os
from django.core.files.storage import FileSystemStorage
from django.conf import settings  # Add this at the top with other imports
import logging

logger = logging.getLogger(__name__)

def master_required(view_func):
    """
    Custom decorator that requires user to be logged in and have master role
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('master:login')
        if request.user.role != 'master' and request.session.get('current_project_role') != 'master':
            messages.error(request, f'Access denied. You are logged in as {request.user.role}. This portal is for administrators only.')
            # Redirect to appropriate portal based on role
            if request.user.role == 'annotator':
                return redirect('/annotator/')
            elif request.user.role == 'reviewer':
                return redirect('/reviewer/')
            elif request.user.role == 'guest':
                return redirect('master:access_denied')
            else:
                return redirect('master:access_denied')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def get_project_or_403(request, unique_id):
    project = get_object_or_404(Project, unique_id=unique_id)
    member = ProjectMember.objects.filter(
        project=project,
        user=request.user
    ).first()
    if not member:
        raise PermissionDenied
    return project, member.role


def get_current_project_or_redirect(request):
    unique_id = request.session.get('current_project_uuid')
    if not unique_id:
        messages.error(request, 'Pilih project dari lobby terlebih dahulu.')
        return None, None, redirect('master:lobby')

    try:
        project, role = get_project_or_403(request, unique_id)
        return project, role, None
    except PermissionDenied:
        request.session.pop('current_project_uuid', None)
        request.session.pop('current_project_role', None)
        messages.error(request, 'Anda bukan member project tersebut.')
        return None, None, redirect('master:lobby')


def landing_view(request):
    """
    Public landing page shown at the root URL. Accessible to everyone,
    logged in or not — think of it as the "lobby of the cinema" before
    entering a specific theater (project lobby / app).
    """
    return render(request, 'master/landing.html')


@login_required
def lobby_view(request):
    memberships = (
        ProjectMember.objects
        .filter(user=request.user)
        .select_related('project')
        .annotate(member_count=Count('project__memberships'))
        .order_by('-project__created_at')
    )
    pending_invites = (
        ProjectInvite.objects
        .filter(status='pending')
        .filter(Q(invited_user=request.user) | Q(invited_email__iexact=request.user.email))
        .select_related('project', 'invited_by')
        .order_by('-created_at')
    )

    return render(request, 'master/lobby.html', {
        'memberships': memberships,
        'pending_invites': pending_invites,
    })


@login_required
@require_http_methods(["POST"])
def create_project_view(request):
    name = (request.POST.get('name') or '').strip()
    description = (request.POST.get('description') or '').strip()

    if not name:
        messages.error(request, 'Nama project wajib diisi.')
        return redirect('master:lobby')

    with transaction.atomic():
        project = Project.objects.create(
            name=name,
            description=description,
            created_by=request.user,
        )
        ProjectMember.objects.create(
            project=project,
            user=request.user,
            role='master',
        )

    messages.success(request, f'Project "{project.name}" berhasil dibuat.')
    return redirect('master:lobby')


@login_required
@require_http_methods(["POST"])
def delete_project_view(request, unique_id):
    """
    Hapus project secara permanen (hard delete).
    Hanya boleh dilakukan oleh user dengan role 'master' di project tersebut.

    Dataset & JobProfile menggunakan on_delete=SET_NULL ke Project (supaya
    data lama tidak ikut hilang kalau project di-archive biasa), JADI untuk
    hard delete di sini job & dataset milik project dihapus manual dulu,
    SEBELUM project itu sendiri dihapus (yang otomatis CASCADE ke
    ProjectMember & ProjectInvite).
    """
    try:
        project, role = get_project_or_403(request, unique_id)
    except PermissionDenied:
        messages.error(request, 'Anda bukan member project tersebut.')
        return redirect('master:lobby')

    if role != 'master':
        messages.error(request, 'Hanya master project yang bisa menghapus project ini.')
        return redirect('master:lobby')

    project_name = project.name

    with transaction.atomic():
        # Hapus job & dataset manual dulu karena FK-nya SET_NULL, bukan CASCADE.
        # JobImage, Annotation, Issue dll yang berelasi ke JobProfile akan ikut
        # terhapus otomatis lewat CASCADE bawaan masing-masing model.
        project.jobs.all().delete()
        project.datasets.all().delete()

        # ProjectMember & ProjectInvite sudah CASCADE, jadi cukup hapus project.
        project.delete()

        # Kalau project yang dihapus adalah project aktif di session, bersihkan.
        if request.session.get('current_project_uuid') == str(unique_id):
            request.session.pop('current_project_uuid', None)
            request.session.pop('current_project_role', None)

    messages.success(request, f'Project "{project_name}" berhasil dihapus secara permanen.')
    return redirect('master:lobby')


@login_required
@require_http_methods(["POST"])
def invite_member_view(request, unique_id):
    try:
        project, role = get_project_or_403(request, unique_id)
    except PermissionDenied:
        messages.error(request, 'Anda bukan member project tersebut.')
        return redirect('master:lobby')

    if role != 'master':
        messages.error(request, 'Hanya master project yang bisa mengundang member.')
        return redirect('master:lobby')

    username_or_email = (request.POST.get('username_or_email') or '').strip()
    invite_role = request.POST.get('role')
    valid_roles = {choice[0] for choice in ProjectMember.ROLE_CHOICES}

    if not username_or_email or invite_role not in valid_roles:
        messages.error(request, 'Isi username/email dan role yang valid.')
        return redirect('master:lobby')

    invited_user = (
        CustomUser.objects
        .filter(Q(username__iexact=username_or_email) | Q(email__iexact=username_or_email))
        .first()
    )
    invited_email = invited_user.email if invited_user else username_or_email

    if invited_user and ProjectMember.objects.filter(project=project, user=invited_user).exists():
        messages.info(request, 'User tersebut sudah menjadi member project ini.')
        return redirect('master:lobby')

    ProjectInvite.objects.create(
        project=project,
        invited_by=request.user,
        invited_user=invited_user,
        invited_email=invited_email,
        role=invite_role,
    )
    messages.success(request, f'Invite untuk {invited_email} sudah dibuat.')
    return redirect('master:lobby')


@login_required
def accept_invite_view(request, token):
    invite = get_object_or_404(ProjectInvite, token=token, status='pending')
    if invite.invited_user and invite.invited_user != request.user:
        messages.error(request, 'Invite ini bukan untuk akun Anda.')
        return redirect('master:lobby')
    if invite.invited_email.lower() != request.user.email.lower() and invite.invited_user is None:
        messages.error(request, 'Email akun Anda tidak cocok dengan invite ini.')
        return redirect('master:lobby')

    with transaction.atomic():
        invite.invited_user = request.user
        invite.status = 'accepted'
        invite.save(update_fields=['invited_user', 'status'])
        ProjectMember.objects.get_or_create(
            project=invite.project,
            user=request.user,
            defaults={'role': invite.role},
        )

    messages.success(request, f'Anda bergabung ke project "{invite.project.name}".')
    return redirect('master:lobby')


@login_required
def decline_invite_view(request, token):
    invite = get_object_or_404(ProjectInvite, token=token, status='pending')
    if invite.invited_user and invite.invited_user != request.user:
        messages.error(request, 'Invite ini bukan untuk akun Anda.')
        return redirect('master:lobby')
    if invite.invited_email.lower() != request.user.email.lower() and invite.invited_user is None:
        messages.error(request, 'Email akun Anda tidak cocok dengan invite ini.')
        return redirect('master:lobby')

    invite.status = 'declined'
    invite.save(update_fields=['status'])
    messages.info(request, f'Invite project "{invite.project.name}" ditolak.')
    return redirect('master:lobby')


@login_required
def enter_project_view(request, unique_id):
    try:
        project, role = get_project_or_403(request, unique_id)
    except PermissionDenied:
        messages.error(request, 'Anda bukan member project tersebut.')
        return redirect('master:lobby')

    request.session['current_project_uuid'] = str(project.unique_id)
    request.session['current_project_id'] = project.id
    request.session['current_project_role'] = role
    messages.success(request, f'Masuk ke project "{project.name}" sebagai {role}.')

    if role == 'master':
        return redirect('master:home')
    if role == 'annotator':
        return redirect('/annotator/')
    if role == 'reviewer':
        return redirect('/reviewer/')
    return redirect('master:lobby')

def signup_view(request):
    if request.method == "POST":
        print("POST data:", request.POST)  # Debug print
        # Create a form instance with the POST data
        data = {
            'username': request.POST.get('username'),
            'first_name': request.POST.get('first_name'),
            'last_name': request.POST.get('last_name'),
            'email': request.POST.get('email'),
            'phone_number': request.POST.get('phone_number'),
            'password1': request.POST.get('password1'),
            'password2': request.POST.get('password2'),
        }
        print("Form data:", data)
        form = SignUpForm(data)

        if form.is_valid():
            print("Form is valid")
            user = form.save()
            print("User saved:", user)
            # Authenticate user
            user = authenticate(
                request,
                username=form.cleaned_data['email'],
                password=form.cleaned_data['password1']
            )
            if user:
                # login(request, user)
                messages.success(request, "Akun berhasil dibuat! Selamat datang!")
                return redirect("master:login")
            else:
                messages.error(request, "Gagal melakukan autentikasi")
        else:
            # Add form errors to messages
            for field in form.errors:
                for error in form.errors[field]:
                    messages.error(request, f"{field}: {error}")
    else:
        form = SignUpForm()

    return render(request, "master/signup.html", {"form": form})

def login_view(request):
    error_message = None
    if request.method == "POST":
        username_or_email = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, email=username_or_email, password=password)
        if user is None:
            user = authenticate(request, username=username_or_email, password=password)

        if user is not None:
            if user.is_active:
                login(request, user)
                messages.success(request, "Login berhasil!")
                
                # --- LOGIKA ROLE BARU ---
                # Cek role user, jika komisi arahkan ke lobi komisi
                if hasattr(user, 'role') and user.role == 'komisi':
                    return redirect("komisi:lobby")
                else:
                    return redirect("master:lobby")
                # -----------------------
            else:
                error_message = "Akun belum diaktifkan!"
        else:
            error_message = "Username/Email atau Password salah!"
            messages.error(request, error_message)

    return render(request, "master/login.html", {"error_message": error_message})

def logout_view(request):
    logout(request)
    return redirect('master:login')

def access_denied_view(request):
    """
    View for users who don't have permission to access master functionality
    """
    return render(request, 'access_denied.html', {
        'user_role': request.user.role if request.user.is_authenticated else 'anonymous'
    })

def activate(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = CustomUser.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        user = None

    if user is not None and account_activation_token.check_token(user, token):
        user.is_active = True
        user.save()
        login(request, user)
        messages.success(request, "Akun berhasil diaktifkan! Silakan login.")
        return redirect("master:home")
    else:
        messages.error(request, "Link aktivasi tidak valid atau sudah kedaluwarsa.")
        return redirect("master:login")

@master_required
def home_view(request):
    current_project, current_role, redirect_response = get_current_project_or_redirect(request)
    if redirect_response:
        return redirect_response

    project_jobs = JobProfile.objects.filter(project=current_project)
    project_images = JobImage.objects.filter(job__project=current_project)
    project_issues = Issue.objects.filter(job__project=current_project)

    # Real data for Status Section - get users with job assignments
    annotators_reviewers = CustomUser.objects.filter(
        project_memberships__project=current_project,
        project_memberships__role__in=['annotator', 'reviewer']
    ).distinct().order_by('email')
    
    # Real status data - determine user status based on job assignments
    status_list = []
    for user in annotators_reviewers:
        # Check if user has active job assignments
        has_active_jobs = False
        if user.role == 'annotator':
            has_active_jobs = JobProfile.objects.filter(
                project=current_project,
                worker_annotator=user, 
                status__in=['in_progress']
            ).exists()
        elif user.role == 'reviewer':
            has_active_jobs = JobProfile.objects.filter(
                project=current_project,
                worker_reviewer=user, 
                status__in=['in_progress']
            ).exists()
        
        # Determine status based on job assignments
        if has_active_jobs:
            status = 'In Job'
            status_class = 'text-blue-700 bg-blue-100'
        else:
            # Check if user has any jobs assigned but not active
            has_any_jobs = False
            if user.role == 'annotator':
                has_any_jobs = project_jobs.filter(worker_annotator=user).exists()
            elif user.role == 'reviewer':
                has_any_jobs = project_jobs.filter(worker_reviewer=user).exists()
            
            if has_any_jobs:
                status = 'Ready'
                status_class = 'text-green-700 bg-green-100'
            else:
                status = 'Not Ready'
                status_class = 'text-red-700 bg-red-100'
        
        status_list.append({
            'name': f"{user.first_name} {user.last_name}".strip() or user.email,
            'status': status,
            'status_class': status_class
        })
    
    # Real data for Assignment Stats Card
    # Calculate the same statistics as in performance view
    total_images = project_images.count()
    
    # Calculate status counts
    unannotated_count = project_images.filter(status='unannotated').count()
    in_review_count = project_images.filter(status='in_review').count()
    in_rework_count = project_images.filter(status='in_rework').count()
    finished_count = project_images.filter(status='finished').count()
    
    # Calculate assigned count (total - unannotated)
    assigned_count = total_images - unannotated_count
    
    # Prepare real assignment stats with chart height calculations
    def calculate_chart_height(count, max_count):
        if count == 0:
            return 0
        # Calculate percentage, with minimum height of 20% for visibility in charts
        percentage = (count / max_count) * 100  # Use full scale for Chart.js
        return max(20, round(percentage))  # Minimum 20% height for non-zero values
    
    # Find max count for proportional scaling
    max_count = max(assigned_count, in_review_count, in_rework_count, finished_count) if total_images > 0 else 1
    # If all values are 0 or very small, use total_images as baseline
    if max_count == 0:
        max_count = total_images if total_images > 0 else 1
    
    assignment_stats = {
        'total': total_images,
        'assign': assigned_count,
        'progress': in_review_count,
        'reviewing': in_rework_count,  # Use in_rework as "reviewing"
        'finished': finished_count,
        # Add chart data for better visualization
        'chart_data': {
            'assign': {'count': assigned_count, 'height': calculate_chart_height(assigned_count, max_count)},
            'progress': {'count': in_review_count, 'height': calculate_chart_height(in_review_count, max_count)},
            'reviewing': {'count': in_rework_count, 'height': calculate_chart_height(in_rework_count, max_count)},
            'finished': {'count': finished_count, 'height': calculate_chart_height(finished_count, max_count)}
        }
    }

    issues_count = project_images.filter(status='issue').count()
    in_progress_count = in_review_count + in_rework_count
    
    context = {
        'current_project': current_project,
        'current_project_role': current_role,
        'users': CustomUser.objects.filter(project_memberships__project=current_project).distinct(),
        'datasets': Dataset.objects.filter(project=current_project).order_by('-date_created'),
        'status_list': status_list,
        'assignment_stats': assignment_stats,
        'in_progress_count': in_progress_count,
        'issues_count': issues_count,
        'unannotated_count': unannotated_count,
        'in_review_count': in_review_count,
        'in_rework_count': in_rework_count,
        'finished_count': finished_count,
        'total_images': total_images,

        # ↓ TAMBAH ISSUE STATS ↓
    'total_issues': project_issues.count(),
    'issues_count': project_issues.count(),
    'issue_count': project_issues.count(),
    'active_issues': project_issues.exclude(status='closed').count(),
    'issues_butuh_review': project_issues.filter(status__in=['open', 'eskalasi', 'reworking']).count(),
    'issues_open': project_issues.filter(status='open').count(),
    'issues_eskalasi': project_issues.filter(status='eskalasi').count(),
    'issues_reworking': project_issues.filter(status='reworking').count(),
    'issues_closed': project_issues.filter(status='closed').count(),
    'issues_active': project_issues.exclude(status='closed').count(),
    'issues_high_priority': project_issues.filter(
        priority='high', status__in=['open', 'eskalasi', 'reworking']
    ).count(),
    }
    return render(request, 'master/home.html', context)

@master_required
def assign_roles_view(request):
    """
    Kelola role member DI DALAM project yang sedang aktif saja.
    Role yang diubah di sini adalah ProjectMember.role (per-project),
    BUKAN CustomUser.role (global) — sesuai konsep multi-tenant.
    """
    current_project, current_role, redirect_response = get_current_project_or_redirect(request)
    if redirect_response:
        return redirect_response

    memberships = (
        ProjectMember.objects
        .filter(project=current_project)
        .select_related('user')
        .order_by('role', 'user__email')
    )

    members_data = []
    for membership in memberships:
        user = membership.user
        annotator_jobs = JobProfile.objects.filter(project=current_project, worker_annotator=user).count()
        reviewer_jobs = JobProfile.objects.filter(project=current_project, worker_reviewer=user).count()

        members_data.append({
            'membership_id': membership.id,
            'user_id': user.id,
            'username': user.username,
            'email': user.email,
            'phone_number': user.phone_number or '',
            'role': membership.role,           # role DI PROJECT INI, bukan global
            'is_active': user.is_active,
            'project_count': annotator_jobs + reviewer_jobs,
        })

    return render(request, "master/assign_roles.html", {
        'current_project': current_project,
        'members': members_data,
    })

@login_required
@require_http_methods(["POST"])
def update_role(request):
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        new_role = data.get('new_role')

        if not user_id or not new_role:
            return JsonResponse({'status': 'error', 'message': 'Missing required data'}, status=400)

        user = CustomUser.objects.get(id=user_id)
        user.role = new_role
        user.save()

        return JsonResponse({'status': 'success', 'message': 'Role updated successfully'})
    except CustomUser.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'User not found'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@master_required
def job_settings_view(request):
    current_project, current_role, redirect_response = get_current_project_or_redirect(request)
    if redirect_response:
        return redirect_response

    if request.method == 'POST':
        try:
            # Create new job profile
            job = JobProfile.objects.create(
                project=current_project,
                title=request.POST.get('title'),
                description=request.POST.get('description'),
                segmentation_type=request.POST.get('segmentation'),
                shape_type=request.POST.get('shape'),
                color=request.POST.get('color'),
                start_date=request.POST.get('start_date'),
                end_date=request.POST.get('end_date')
            )
            return JsonResponse({'status': 'success', 'message': 'Job profile created successfully'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

    jobs = JobProfile.objects.filter(project=current_project).order_by('-date_created', '-id')
    return render(request, "master/job_settings.html", {
        'jobs': jobs,
        'current_project': current_project,
        'current_project_role': current_role,
    })

@login_required
def issue_detail_view(request, job_id):
    """
    Returns details about all images with issues for a specific job as JSON.
    
    Retrieves the job by ID and gathers all associated images marked with status 'Issue'. For each image, includes its absolute URL, annotator's email (or 'Unassigned'), and issue description. Returns a JSON response containing the job title and a list of issue images. On error, returns a JSON error message with status 500.
    """
    try:
        from .models import Annotation, Segmentation, SegmentationType, PolygonPoint

        current_project, current_role, redirect_response = get_current_project_or_redirect(request)
        if redirect_response:
            return JsonResponse({'error': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

        job = get_object_or_404(JobProfile, id=job_id, project=current_project)
        print("=== Debug Info ===")
        print(f"Job ID: {job_id}")
        print(f"Job Title: {job.title}")

        # Get all images for the job, not just those with issues
        job_images = JobImage.objects.filter(job=job)
        print(f"Total images found: {job_images.count()}")

        # Also log the count of images with issues for debugging
        issues_images_count = job_images.filter(status='issue').count()
        print(f"Images with issues found: {issues_images_count}")

        # Add status counts to the response
        unannotated_count = JobImage.objects.filter(job=job, status='unannotated').count()
        in_review_count = JobImage.objects.filter(job=job, status='in_review').count()
        in_rework_count = JobImage.objects.filter(job=job, status='in_rework').count()
        finished_count = JobImage.objects.filter(job=job, status='finished').count()
        issues_count = JobImage.objects.filter(job=job, status='issue').count()

        # Get all classes and segmentation types for this job
        # Fix: Segmentation.job refers to JobImage, not JobProfile
        all_segmentations = Segmentation.objects.filter(job__in=job_images)
        classes = list(set(seg.label for seg in all_segmentations))
        segmentation_types = SegmentationType.objects.filter(is_active=True)
        
        # Count annotations by class
        class_counts = {}
        for cls in classes:
            count = all_segmentations.filter(label=cls).count()
            class_counts[cls] = count

        # Count by segmentation type
        segtype_counts = {}
        for segtype in segmentation_types:
            count = all_segmentations.filter(segmentation_type=segtype).count()
            segtype_counts[segtype.name] = count

        data = {
            'job_title': job.title,
            'title': job.title,  # Keep for backward compatibility
            'status_counts': {
                'unannotated': unannotated_count,
                'in_review': in_review_count,
                'in_rework': in_rework_count,
                'finished': finished_count,
                'issues': issues_count
            },
            'classes': class_counts,
            'segmentation_types': segtype_counts,
            'images': []
        }

        # Detailed logging for each image
        for img in job_images:
            if not img.image:
                print(f"Image ID {img.id}: No image file attached")
                continue

            try:
                # Verify image file exists
                image_exists = os.path.exists(img.image.path)
                print(f"Image ID: {img.id}")
                print(f"Image URL: {img.image.url}")
                print(f"Image Path: {img.image.path}")
                print(f"Image Exists: {image_exists}")

                if not image_exists:
                    print(f"WARNING: Image file does not exist at {img.image.path}")
                    print(f"Skipping missing image file: {img.image.path}")
                    # Skip this image entirely to prevent 404 errors
                    continue
                else:
                    # Build absolute URI for the image
                    image_url = request.build_absolute_uri(img.image.url)

                print(f"Processing image ID {img.id}: {image_url}")

                # Get annotations for this image
                annotations = Annotation.objects.filter(job_image=img)
                print(f"Found {annotations.count()} annotations for image ID {img.id}")
                annotation_data = []
                
                for annotation in annotations:
                    # Calculate bbox format [x, y, width, height]
                    bbox_x = annotation.x_min if annotation.x_min is not None else annotation.x_coordinate
                    bbox_y = annotation.y_min if annotation.y_min is not None else annotation.y_coordinate
                    bbox_width = (annotation.x_max - annotation.x_min) if (annotation.x_max and annotation.x_min) else annotation.width
                    bbox_height = (annotation.y_max - annotation.y_min) if (annotation.y_max and annotation.y_min) else annotation.height
                    
                    ann_data = {
                        'id': annotation.id,
                        'class_name': annotation.segmentation.label if annotation.segmentation else getattr(annotation, 'label', f'Annotation {annotation.id}'),
                        'label': annotation.segmentation.label if annotation.segmentation else getattr(annotation, 'label', f'Annotation {annotation.id}'),
                        'bbox': [bbox_x or 0, bbox_y or 0, bbox_width or 0, bbox_height or 0],
                        'x_min': annotation.x_min,
                        'y_min': annotation.y_min,
                        'x_max': annotation.x_max,
                        'y_max': annotation.y_max,
                        'x_coordinate': annotation.x_coordinate,
                        'y_coordinate': annotation.y_coordinate,
                        'width': annotation.width,
                        'height': annotation.height,
                        'status': annotation.status,
                        'confidence_score': annotation.confidence_score,
                        'created_by_ai': getattr(annotation, 'is_auto_generated', False),
                        'is_auto_generated': getattr(annotation, 'is_auto_generated', False)
                    }
                    
                    # Add color information
                    if annotation.segmentation:
                        ann_data['segmentation'] = {
                            'name': annotation.segmentation.label,
                            'color': getattr(annotation.segmentation, 'color', '#22c55e')
                        }
                        ann_data['segmentation_color'] = getattr(annotation.segmentation, 'color', '#22c55e')
                        
                        # Get polygon points if available
                        polygon_points = PolygonPoint.objects.filter(segmentation=annotation.segmentation).order_by('order_index')
                        if polygon_points.exists():
                            ann_data['polygon_points'] = [{
                                'x': point.x,
                                'y': point.y,
                                'order': point.order_index
                            } for point in polygon_points]
                    else:
                        # Default color for annotations without segmentation
                        ann_data['annotation_color'] = '#22c55e'
                    
                    annotation_data.append(ann_data)
                    print(f"  Added annotation {annotation.id}: {ann_data['label']} at bbox {ann_data['bbox']}")

                print(f"Total annotations added for image {img.id}: {len(annotation_data)}")
                # Add image data to response
                data['images'].append({
                    'url': image_url,
                    'filename': os.path.basename(img.image.name) if img.image else f'image_{img.id}',
                    'status': img.status,
                    'annotator': img.annotator.email if img.annotator else 'Unassigned',
                    'issue_description': img.issue_description or 'No description',
                    'annotations': annotation_data
                })
            except Exception as img_error:
                print(f"Error processing image ID {img.id}: {str(img_error)}")
                # Continue with next image instead of failing completely
                continue

        # Log the number of images being returned
        print(f"Returning {len(data['images'])} images")
        print("=== End Debug Info ===")

        return JsonResponse(data)
    except Exception as e:
        print(f"Error in issue_detail_view: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@master_required
def performance_view(request):
    """
    Renders the performance page for authenticated users.
    """
    current_project, current_role, redirect_response = get_current_project_or_redirect(request)
    if redirect_response:
        return redirect_response

    # Ambil semua user dengan role annotator dan reviewer
    members = CustomUser.objects.filter(
        project_memberships__project=current_project,
        project_memberships__role__in=["annotator", "reviewer"]
    ).distinct().order_by('email')

    # Hitung jumlah project (job) yang pernah diassign ke user (sebagai annotator/reviewer)
    member_data = []
    for user in members:
        # Hitung jumlah job sebagai annotator
        project_count = JobProfile.objects.filter(project=current_project, worker_annotator=user).count()
        # Hitung jumlah job sebagai reviewer
        if user.role == 'reviewer':
            project_count = JobProfile.objects.filter(project=current_project, worker_reviewer=user).count()
        member_data.append({
            'id': user.id,
            'email': user.email,
            'phone_number': user.phone_number or '-',
            'role': user.get_role_display(),
            'project_count': project_count,
            'group': '-',
        })

    # Calculate real statistics for Card & Chart section
    # Get all job images and their status counts
    project_images = JobImage.objects.filter(job__project=current_project)
    total_images = project_images.count()
    
    # Calculate status counts
    unannotated_count = project_images.filter(status='unannotated').count()
    in_review_count = project_images.filter(status='in_review').count()
    in_rework_count = project_images.filter(status='in_rework').count()
    finished_count = project_images.filter(status='finished').count()
    issue_count = project_images.filter(status='issue').count()
    
    # Calculate assignment stats - images that are assigned (not unannotated)
    assigned_count = total_images - unannotated_count
    
    # Calculate percentage completion
    completion_percentage = round((finished_count / total_images * 100)) if total_images > 0 else 0
    
    # Prepare chart data (heights as percentages of max value for styling)
    # Use total_images as max for better proportional representation
    max_count = total_images if total_images > 0 else 1
    
    def calculate_height(count):
        if count == 0:
            return 0
        # Calculate percentage, with minimum height of 15% for visibility
        percentage = (count / max_count) * 80  # Use 80% of container height
        return max(15, round(percentage))  # Minimum 15% height for non-zero values
    
    chart_data = {
        'assign': {
            'count': assigned_count,
            'height': calculate_height(assigned_count)
        },
        'progress': {  # in_review 
            'count': in_review_count,
            'height': calculate_height(in_review_count)
        },
        'reworking': {  # in_rework
            'count': in_rework_count,
            'height': calculate_height(in_rework_count)
        },
        'finished': {
            'count': finished_count,
            'height': calculate_height(finished_count)
        }
    }
    
    # Prepare context data
    context = {
        'members': member_data,
        'current_project': current_project,
        'total_images': total_images,
        'completion_percentage': completion_percentage,
        'chart_data': chart_data,
        'status_counts': {
            'unannotated': unannotated_count,
            
            'assigned': assigned_count,
            'in_review': in_review_count,
            'in_rework': in_rework_count,
            'finished': finished_count,
            'issues': issue_count,
            
        }
    }

    return render(request, "master/performance.html", context)

@master_required
def process_validations_view(request, job_id=None):
    try:
        current_project, current_role, redirect_response = get_current_project_or_redirect(request)
        if redirect_response:
            return redirect_response

        if job_id:
            print(f"Fetching job details for job_id: {job_id}")
            
            # Get job with annotations
            job = JobProfile.objects.select_related(
                'worker_annotator',
                'worker_reviewer'
            ).get(id=job_id, project=current_project)
            
            # Get images with status, ordered by ID (ascending)
            images = job.images.all().order_by('id')
            # === LOGIC COUNT FIX ===
            # 'annotated' = SEMUA image yg udah pernah di-annotate (agregat)
            # 'Issue' = image yg punya Issue record di tabel Issue (via FK relation)
            status_counts = {
                'unannotated': images.filter(status='unannotated').count(),
                'annotated': images.filter(
                    status__in=['annotated', 'in_review', 'in_rework', 'finished']
                ).count(),
                'in_review': images.filter(status='in_review').count(),
                'in_rework': images.filter(status='in_rework').count(),
                'Issue': images.filter(issues__isnull=False).distinct().count(),
                'finished': images.filter(status='finished').count(),
            }
            
            print(f"Found {images.count()} images for job {job.title}")
            
            context = {
                'job': job,
                'images': images,
                'show_details': True,
                'current_date': timezone.now().strftime('%d %B %Y'),
                'status_counts': status_counts
            }

            return render(request, 'master/process_validations.html', context)
        else:
            # Get all jobs for list view, ordered by newest first
            jobs = JobProfile.objects.annotate(
                total_images=Count('images')
            ).select_related(
                'worker_annotator',
                'worker_reviewer'
            ).filter(project=current_project).order_by('-date_created')
            
            print(f"Found {jobs.count()} jobs")
            
            context = {
                'jobs': jobs,
                'current_project': current_project,
                'show_details': False,
                'current_date': timezone.now().strftime('%d %B %Y')
            }
            
            return render(request, 'master/process_validations.html', context)

    except Exception as e:
        print(f"Error in process_validations_view: {str(e)}")
        return render(request, 'master/process_validations.html', {
            'error': str(e),
            'show_details': False
        })

@login_required
@require_http_methods(["POST"])
def add_dataset(request):
    try:
        current_project, current_role, redirect_response = get_current_project_or_redirect(request)
        if redirect_response:
            return JsonResponse({'status': 'error', 'message': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

        name = request.POST.get('name')
        labeler_id = request.POST.get('labeler')
        dataset_file = request.FILES.get('dataset_file')

        if not all([name, labeler_id, dataset_file]):
            return JsonResponse({
                'status': 'error',
                'message': 'Missing required fields'
            }, status=400)

        # Handle file upload
        file_path = handle_dataset_upload(dataset_file)

        # Create dataset record
        dataset = Dataset.objects.create(
            project=current_project,
            name=name,
            labeler_id=labeler_id,
            file_path=file_path
        )

        return JsonResponse({
            'status': 'success',
            'message': 'Dataset added successfully',
            'id': dataset.id
        })

    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@master_required
def add_dataset_view(request):
    """
    Endpoint: POST /master/add_dataset/
    Menerima form upload dataset dari master/home.html modal Add Dataset.
    Required fields: name, labeler (user id), dataset_file (file).
    """
    if request.method == 'POST':
        try:
            current_project, current_role, redirect_response = get_current_project_or_redirect(request)
            if redirect_response:
                return JsonResponse({'status': 'error', 'message': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

            name = request.POST.get('name')
            labeler_id = request.POST.get('labeler')
            dataset_file = request.FILES.get('dataset_file')

            if not all([name, labeler_id, dataset_file]):
                return JsonResponse({
                    'status': 'error',
                    'message': 'Missing required fields (name, labeler, dataset_file)'
                }, status=400)

            # Assign file instance langsung ke FileField.
            # Django otomatis save ke MEDIA_ROOT/datasets/ sesuai upload_to di model.
            dataset = Dataset.objects.create(
                project=current_project,
                name=name,
                labeler_id=labeler_id,
                file_path=dataset_file,
                count=0,
            )

            return JsonResponse({
                'status': 'success',
                'message': 'Dataset added successfully',
                'id': dataset.id,
            })

        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)

    return JsonResponse({
        'status': 'error',
        'message': 'Method not allowed'
    }, status=405)

@login_required
@require_http_methods(["POST"])
def create_job_profile(request):
    try:
        current_project, current_role, redirect_response = get_current_project_or_redirect(request)
        if redirect_response:
            return JsonResponse({'status': 'error', 'message': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

        job = JobProfile.objects.create(
            project=current_project,
            title=request.POST.get('title'),
            description=request.POST.get('description'),
            segmentation_type=request.POST.get('segmentation'),
            shape_type=request.POST.get('shape'),
            color=request.POST.get('color'),
            start_date=request.POST.get('start_date'),
            end_date=request.POST.get('end_date'),
            priority=request.POST.get('priority', 'medium')  # Default to medium if not provided
        )
        return JsonResponse({
            'status': 'success',
            'message': 'Job profile created successfully',
            'id': job.id
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@login_required
def job_profile_detail(request, job_id):
    """
    Returns detailed information about a specific job profile as JSON.
    
    Retrieves a job by its ID and constructs a JSON response containing job details, assigned worker emails, segmentation and shape types, color, status, formatted start and end dates, the URL of the first associated image, and counts of images by various statuses. Returns an error response if the job cannot be retrieved or another exception occurs.
    """
    try:
        current_project, current_role, redirect_response = get_current_project_or_redirect(request)
        if redirect_response:
            return JsonResponse({'error': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

        job = get_object_or_404(JobProfile, id=job_id, project=current_project)
        print(f"Found job: {job.id}")  # Debug log

        data = {
            'id': job.id,
            'title': job.title,
            'description': job.description,
            'worker_annotator': job.worker_annotator.email if job.worker_annotator else None,
            'worker_reviewer': job.worker_reviewer.email if job.worker_reviewer else None,
            'segmentation_type': job.segmentation_type,
            'shape_type': job.shape_type,
            'color': job.color,
            'status': job.status,
            'start_date': job.start_date.strftime('%Y-%m-%d') if job.start_date else None,
            'end_date': job.end_date.strftime('%Y-%m-%d') if job.end_date else None,
            'first_image_url': job.get_first_image_url(),
            'image_count': JobImage.objects.filter(job=job).count(),
            'unannotated_count': JobImage.objects.filter(job=job, status='unannotated').count(),
            'in_review_count': JobImage.objects.filter(job=job, status='in_review').count(),
            'in_rework_count': JobImage.objects.filter(job=job, status='in_rework').count(),
            'finished_count': JobImage.objects.filter(job=job, status='finished').count(),
            'issues_count': JobImage.objects.filter(job=job, status='issue').count(),
        }

        print(f"Returning data: {data}")  # Debug log
        return JsonResponse(data)

    except Exception as e:
        print(f"Error in job_profile_detail: {str(e)}")  # Debug log
        return JsonResponse({'error': str(e)}, status=500)

# Dataset flow for edit and delete
@login_required
def edit_dataset_view(request, dataset_id):
    """
    Endpoint: POST /master/edit_dataset/<id>/
    Update dataset (name, labeler, optional file baru).
    """
    current_project, current_role, redirect_response = get_current_project_or_redirect(request)
    if redirect_response:
        return JsonResponse({'status': 'error', 'message': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

    dataset = get_object_or_404(Dataset, id=dataset_id, project=current_project)

    if request.method == 'POST':
        try:
            dataset.name = request.POST.get('name')
            dataset.labeler_id = request.POST.get('labeler')

            # Kalau user upload file baru, replace file_path dengan file instance.
            # Kalau ga upload file baru, file_path lama tetep.
            if 'dataset_file' in request.FILES:
                dataset.file_path = request.FILES['dataset_file']

            dataset.save()

            return JsonResponse({
                'status': 'success',
                'message': 'Dataset updated successfully'
            })
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)

    return JsonResponse({
        'status': 'error',
        'message': 'Method not allowed'
    }, status=405)

@login_required
def delete_dataset_view(request, dataset_id):
    if request.method == 'POST':
        try:
            current_project, current_role, redirect_response = get_current_project_or_redirect(request)
            if redirect_response:
                return JsonResponse({'status': 'error', 'message': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

            dataset = get_object_or_404(Dataset, id=dataset_id, project=current_project)
            dataset.delete()
            return JsonResponse({
                'status': 'success',
                'message': 'Dataset deleted successfully'
            })
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)

    return JsonResponse({
        'status': 'error',
        'message': 'Method not allowed'
    }, status=405)

@login_required
@require_http_methods(["POST"])
def upload_job_images(request):
    try:
        current_project, current_role, redirect_response = get_current_project_or_redirect(request)
        if redirect_response:
            return JsonResponse({'status': 'error', 'message': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

        job_id = request.POST.get('job_id')
        job = JobProfile.objects.get(id=job_id, project=current_project)
        files = request.FILES.getlist('images[]')

        current_count = JobImage.objects.filter(job=job).count()
        if current_count + len(files) > 150:
            return JsonResponse({
                'status': 'error',
                'message': f'Cannot add {len(files)} images. Maximum limit is 150 images.'
            }, status=400)

        # Upload new images
        uploaded_count = 0
        for file in files:
            if file.content_type.startswith('image/'):
                JobImage.objects.create(
                    job=job,
                    image=file,
                    status='unannotated'  # Default status for new uploads
                )
                uploaded_count += 1

        # Get updated counts after upload
        new_total = JobImage.objects.filter(job=job).count()
        unannotated_count = JobImage.objects.filter(job=job, status='unannotated').count()
        in_review_count = JobImage.objects.filter(job=job, status='in_review').count()
        in_rework_count = JobImage.objects.filter(job=job, status='in_rework').count()
        finished_count = JobImage.objects.filter(job=job, status='finished').count()
        issues_count = JobImage.objects.filter(job=job, status='has_issues').count()

        # Update job status and image count
        if job.status == 'not_assign' and new_total > 0:
            job.status = 'in_progress'
        job.image_count = new_total
        job.save()

        return JsonResponse({
            'status': 'success',
            'message': f'{uploaded_count} images uploaded successfully',
            'new_image_count': new_total,
            'new_status': job.status,
            'unannotated_count': unannotated_count,
            'in_review_count': in_review_count,
            'in_rework_count': in_rework_count,
            'finished_count': finished_count,
            'issues_count': issues_count
        })

    except JobProfile.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Job not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@login_required
def get_workers(request, role):
    """Get list of available workers by role"""
    try:
        current_project, current_role, redirect_response = get_current_project_or_redirect(request)
        if redirect_response:
            return JsonResponse({'status': 'error', 'message': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

        workers = CustomUser.objects.filter(
            project_memberships__project=current_project,
            project_memberships__role=role,
            is_active=True
        ).distinct()
        return JsonResponse({
            'workers': [{
                'id': worker.id,
                'email': worker.email,
                'phone': worker.phone_number,  # Make sure this matches your model field
                'name': f"{worker.first_name} {worker.last_name}".strip()
            } for worker in workers]
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@login_required
@require_http_methods(["POST"])
def assign_worker(request):
    """Assign worker to a job"""
    try:
        current_project, current_role, redirect_response = get_current_project_or_redirect(request)
        if redirect_response:
            return JsonResponse({'status': 'error', 'message': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

        data = json.loads(request.body)
        job_id = data.get('job_id')
        worker_id = data.get('worker_id')
        role = data.get('role')

        job = JobProfile.objects.get(id=job_id, project=current_project)
        worker = CustomUser.objects.get(id=worker_id)
        if not ProjectMember.objects.filter(project=current_project, user=worker, role=role).exists():
            return JsonResponse({'status': 'error', 'message': 'Worker is not a project member with that role'}, status=403)

        if role == 'annotator':
            job.worker_annotator = worker
            # Create notification for annotator
            create_job_notification(job, worker, request.user)
        elif role == 'reviewer':
            job.worker_reviewer = worker

        job.save()

        return JsonResponse({
            'status': 'success',
            'message': f'{role.title()} assigned successfully'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@login_required
@require_http_methods(["POST"])
def assign_workers(request):
    try:
        current_project, current_role, redirect_response = get_current_project_or_redirect(request)
        if redirect_response:
            return JsonResponse({'status': 'error', 'message': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

        data = json.loads(request.body)
        job_id = data.get('job_id')
        annotator_id = data.get('annotator_id')
        reviewer_id = data.get('reviewer_id')

        if not all([job_id, annotator_id, reviewer_id]):
            return JsonResponse({
                'status': 'error',
                'message': 'Missing required fields'
            }, status=400)

        job = JobProfile.objects.get(id=job_id, project=current_project)
        annotator = CustomUser.objects.get(id=annotator_id)
        reviewer = CustomUser.objects.get(id=reviewer_id)
        if not ProjectMember.objects.filter(project=current_project, user=annotator, role='annotator').exists():
            return JsonResponse({'status': 'error', 'message': 'Annotator is not a member of this project'}, status=403)
        if not ProjectMember.objects.filter(project=current_project, user=reviewer, role='reviewer').exists():
            return JsonResponse({'status': 'error', 'message': 'Reviewer is not a member of this project'}, status=403)

        # Update job with worker assignments
        job.worker_annotator = annotator
        job.worker_reviewer = reviewer
        job.status = 'in_progress'
        
        # Create notifications for both annotator and reviewer
        create_job_notification(job, annotator, request.user)
        # Optionally create notification for reviewer too
        # create_job_notification(job, reviewer, request.user)
        
        job.save()

        return JsonResponse({
            'status': 'success',
            'annotator_name': annotator.email,
            'reviewer_name': reviewer.email,
            'new_status': 'In Progress'  # Match dengan get_status_display()
        })
    except (JobProfile.DoesNotExist, CustomUser.DoesNotExist) as e:
        return JsonResponse({
            'status': 'error',
            'message': 'Job or User not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

def home(request):
    # Dummy data untuk development UI
    context = {
        'assignment_stats': {
            'total': 16765,
            'assign': 300,
            'progress': 450,
            'reviewing': 200,
            'finished': 150
        },
        'datasets': [
            {
                'name': 'dataset_kendaraan',
                'labeler': 'Andy',
                'date': '17/04/2024',
                'count': 110
            }
            # More dummy data
        ],
        'status_list': [
            {'name': 'Andy Wirawan', 'status': 'Not Ready'},
            {'name': 'Wiyoko Suprapto', 'status': 'Ready'}
        ]
    }
    return render(request, 'master/home.html', context)

def handle_dataset_upload(dataset_file):
    """
    Handle the upload of dataset files
    Returns the file path where the dataset is stored
    """
    try:
        fs = FileSystemStorage()
        # Create datasets directory if it doesn't exist
        dataset_dir = os.path.join('datasets')
        os.makedirs(os.path.join(settings.MEDIA_ROOT, dataset_dir), exist_ok=True)

        # Save file
        filename = fs.save(f'datasets/{dataset_file.name}', dataset_file)
        file_path = fs.url(filename)
        return file_path
    except Exception as e:
        raise Exception(f"Error uploading dataset file: {str(e)}")

@login_required
def get_job_profile(request, job_id):
    try:
        current_project, current_role, redirect_response = get_current_project_or_redirect(request)
        if redirect_response:
            return JsonResponse({'error': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

        job = JobProfile.objects.select_related('worker_annotator', 'worker_reviewer').get(id=job_id, project=current_project)

        # Debug logging
        print(f"Retrieved job: {job.id}, annotator: {job.worker_annotator}, reviewer: {job.worker_reviewer}")

        # Get worker information with improved error handling
        worker_annotator_email = '-'
        worker_annotator_name = '-'
        worker_reviewer_email = '-'
        worker_reviewer_name = '-'

        # Safely get annotator information
        if job.worker_annotator:
            try:
                worker_annotator_email = job.worker_annotator.email
                worker_annotator_name = f"{job.worker_annotator.first_name or ''} {job.worker_annotator.last_name or ''}".strip() or job.worker_annotator.email
            except Exception as e:
                print(f"Error accessing annotator info: {e}")

        # Safely get reviewer information
        if job.worker_reviewer:
            try:
                worker_reviewer_email = job.worker_reviewer.email
                worker_reviewer_name = f"{job.worker_reviewer.first_name or ''} {job.worker_reviewer.last_name or ''}".strip() or job.worker_reviewer.email
            except Exception as e:
                print(f"Error accessing reviewer info: {e}")

        # Get job image counts with error handling
        try:
            job_images = JobImage.objects.filter(job=job)
            image_counts = {
                'total': job_images.count(),
                'unannotated': job_images.filter(status='unannotated').count(),
                'in_review': job_images.filter(status='in_review').count(),
                'in_rework': job_images.filter(status='in_rework').count(),
                'finished': job_images.filter(status='finished').count(),
                'issues': job_images.filter(status='issues').count(),
            }
        except Exception as e:
            print(f"Error getting image counts: {e}")
            image_counts = {
                'total': 0, 'unannotated': 0, 'in_review': 0,
                'in_rework': 0, 'finished': 0, 'issues': 0
            }

        data = {
            'id': job.id,
            'title': job.title or '',
            'description': job.description or '',
            'hotkey': getattr(job, 'hotkey', '') or '',
            'worker_annotator': worker_annotator_email,
            'worker_reviewer': worker_reviewer_email,
            'worker_annotator_name': worker_annotator_name,
            'worker_reviewer_name': worker_reviewer_name,
            'segmentation_type': job.segmentation_type or '',
            'shape_type': job.shape_type or '',
            'color': job.color or '#000000',
            'status': job.get_status_display() or 'Not Assigned',
            'start_date': job.start_date.strftime('%Y-%m-%d') if job.start_date else None,
            'end_date': job.end_date.strftime('%Y-%m-%d') if job.end_date else None,
            'image_count': image_counts['total'],
            'unannotated_count': image_counts['unannotated'],
            'in_review_count': image_counts['in_review'],
            'in_rework_count': image_counts['in_rework'],
            'finished_count': image_counts['finished'],
            'issues_count': image_counts['issues'],
        }

        # Debug logging
        print("Sending response data:", data)
        return JsonResponse(data)

    except JobProfile.DoesNotExist:
        return JsonResponse({'error': 'Job not found'}, status=404)
    except Exception as e:
        import traceback
        print("Error in get_job_profile:")
        print(traceback.format_exc())
        return JsonResponse({'error': str(e)}, status=500)

@master_required
def issue_solving_view(request):
    """
    Halaman issue solving — master arbitrate eskalasi.
 
    Query params:
      ?tab=active    (default) → tampil semua selain closed
      ?tab=closed             → tampil cuma yang closed
      ?priority=high
      ?job_id=9
    """
    from master.models import Issue

    current_project, current_role, redirect_response = get_current_project_or_redirect(request)
    if redirect_response:
        return redirect_response
 
    tab = request.GET.get('tab', 'active')
    priority_filter = request.GET.get('priority', '')
    job_id = request.GET.get('job_id', '')
 
    qs = Issue.objects.select_related(
        'job', 'image', 'assigned_to', 'created_by'
    ).filter(job__project=current_project).prefetch_related('comments__created_by').order_by('-priority', '-created_at')
 
    # Tab filter
    if tab == 'closed':
        qs = qs.filter(status='closed')
    else:
        # Active = semua selain closed
        qs = qs.exclude(status='closed')
 
    if priority_filter:
        qs = qs.filter(priority=priority_filter)
    if job_id:
        qs = qs.filter(job_id=job_id)
 
    issues = list(qs)
 
    # Stats summary (global, tidak terpengaruh filter)
    project_issues = Issue.objects.filter(job__project=current_project)
    total = project_issues.count()
    closed = project_issues.filter(status='closed').count()
    stats = {
        'total': total,
        'active': total - closed,
        'eskalasi': project_issues.filter(status='eskalasi').count(),
        'open': project_issues.filter(status='open').count(),
        'reworking': project_issues.filter(status='reworking').count(),
        'closed': closed,
        'high_priority': project_issues.filter(
            priority='high', status__in=['open', 'eskalasi', 'reworking']
        ).count(),
    }
 
    jobs_with_issues = JobProfile.objects.filter(
        project=current_project,
        issues__isnull=False
    ).distinct().order_by('-date_created')
 
    context = {
        'issues': issues,
        'stats': stats,
        'jobs_with_issues': jobs_with_issues,
        'filter_tab': tab,
        'filter_priority': priority_filter,
        'filter_job_id': job_id,
        'current_date': timezone.now().strftime('%d %B %Y'),
        'current_project': current_project,
    }
 
    return render(request, 'master/Issue_solving.html', context)

@login_required
@require_http_methods(["POST"])
def finish_image(request):
    try:
        current_project, current_role, redirect_response = get_current_project_or_redirect(request)
        if redirect_response:
            return JsonResponse({'status': 'error', 'message': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

        data = json.loads(request.body)
        image_id = data.get('image_id')
        image = JobImage.objects.get(id=image_id, job__project=current_project)
        image.status = 'finished'
        image.save()
        
        # Check if all images are finished and update job status
        job = image.job
        if not job.images.exclude(status='finished').exists():
            job.status = 'finish'
            job.save()
        
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
@require_http_methods(["POST"])
def finish_job(request):
    try:
        current_project, current_role, redirect_response = get_current_project_or_redirect(request)
        if redirect_response:
            return JsonResponse({'status': 'error', 'message': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

        data = json.loads(request.body)
        job_id = data.get('job_id')
        job = JobProfile.objects.get(id=job_id, project=current_project)
        
        # Mark job as completed
        job.status = 'finish'
        job.save()
        
        # Optionally mark all images as finished if not already
        job.images.update(status='finished')
        
        return JsonResponse({'status': 'success', 'message': 'Job marked as completed successfully'})
    except JobProfile.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Job not found'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@master_required
@require_http_methods(["POST"])
def update_user_roles(request):
    """
    AJAX endpoint untuk update role member DI PROJECT YANG SEDANG AKTIF.

    Mengubah ProjectMember.role (per-project), BUKAN CustomUser.role (global).
    Hanya boleh mengubah member yang memang sudah tergabung di project ini
    (dicek lewat get_current_project_or_redirect, dan setiap update divalidasi
    membership-nya benar-benar milik project ini).
    """
    current_project, current_role, redirect_response = get_current_project_or_redirect(request)
    if redirect_response:
        return JsonResponse({
            'status': 'error',
            'message': 'Project aktif tidak ditemukan. Silakan masuk ke project dari Lobby.',
        }, status=400)

    valid_roles = {choice[0] for choice in ProjectMember.ROLE_CHOICES}

    try:
        data = json.loads(request.body)
        updates = data.get('updates', [])

        if not updates:
            return JsonResponse({
                'status': 'error',
                'message': 'No updates provided'
            }, status=400)

        success_count = 0
        errors = []

        for update in updates:
            user_id = update.get('userId')
            new_role = update.get('newRole')

            if not user_id or not new_role:
                errors.append(f'Invalid data for update: {update}')
                continue

            if new_role not in valid_roles:
                errors.append(f'Role "{new_role}" tidak valid untuk project (pilihan: {", ".join(sorted(valid_roles))})')
                continue

            try:
                # WAJIB filter by project=current_project — supaya master
                # project A tidak bisa ubah role member di project lain.
                membership = ProjectMember.objects.select_related('user').get(
                    project=current_project, user_id=user_id
                )
                old_role = membership.role
                membership.role = new_role
                membership.save(update_fields=['role'])

                success_count += 1
                print(f"Updated {membership.user.email} di project '{current_project.name}' dari {old_role} ke {new_role}")

            except ProjectMember.DoesNotExist:
                errors.append(f'User {user_id} bukan member project ini')
            except Exception as e:
                errors.append(f'Error updating user {user_id}: {str(e)}')

        if errors:
            return JsonResponse({
                'status': 'partial_success',
                'message': f'Updated {success_count} users successfully, {len(errors)} errors',
                'success_count': success_count,
                'errors': errors
            })
        else:
            return JsonResponse({
                'status': 'success',
                'message': f'Successfully updated {success_count} role member di project "{current_project.name}"',
                'success_count': success_count
            })

    except json.JSONDecodeError:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': f'Server error: {str(e)}'
        }, status=500)
    
"""
SNIPPET — Edit & Delete Job Profile
===================================
Copy 2 fungsi di bawah ini, paste ke AKHIR file master/views.py
(sebelum atau sesudah view yang udah ada, bebas)

Decorator @login_required dan @require_http_methods udah di-import di
views.py lu (dipakai oleh create_job_profile), jadi gak perlu import
tambahan.
"""


# ========================================================
# EDIT JOB PROFILE
# ========================================================
@login_required
@require_http_methods(["GET", "POST"])
def edit_job_profile(request, job_id):
    """
    GET  -> return current job data (buat prefill form edit)
    POST -> update job & return success
    """
    try:
        current_project, current_role, redirect_response = get_current_project_or_redirect(request)
        if redirect_response:
            return JsonResponse({'status': 'error', 'message': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

        job = JobProfile.objects.get(id=job_id, project=current_project)
    except JobProfile.DoesNotExist:
        return JsonResponse(
            {'status': 'error', 'message': 'Job profile tidak ditemukan'},
            status=404
        )

    if request.method == 'GET':
        return JsonResponse({
            'status': 'success',
            'data': {
                'id': job.id,
                'title': job.title,
                'description': job.description or '',
                'segmentation_type': job.segmentation_type or '',
                'shape_type': job.shape_type or '',
                'color': job.color or '#000000',
                'priority': job.priority or 'medium',
                'start_date': job.start_date.strftime('%Y-%m-%d') if job.start_date else '',
                'end_date': job.end_date.strftime('%Y-%m-%d') if job.end_date else '',
            }
        })

    # POST — update
    try:
        job.title = request.POST.get('title', job.title)
        job.description = request.POST.get('description', job.description)
        job.segmentation_type = request.POST.get('segmentation', job.segmentation_type)
        job.shape_type = request.POST.get('shape', job.shape_type)
        job.color = request.POST.get('color', job.color)
        job.priority = request.POST.get('priority', job.priority)

        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        if start_date:
            job.start_date = start_date
        if end_date:
            job.end_date = end_date

        job.save()
        return JsonResponse({
            'status': 'success',
            'message': 'Job profile berhasil di-update',
            'id': job.id,
        })
    except Exception as e:
        return JsonResponse(
            {'status': 'error', 'message': str(e)},
            status=500
        )


# ========================================================
# DELETE JOB PROFILE
# ========================================================
@login_required
@require_http_methods(["POST"])
def delete_job_profile(request, job_id):
    """
    Hard-delete job profile. Juga hapus semua JobImage, Annotation, dll
    yang berelasi (on_delete=CASCADE di model).
    """
    try:
        current_project, current_role, redirect_response = get_current_project_or_redirect(request)
        if redirect_response:
            return JsonResponse({'status': 'error', 'message': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

        job = JobProfile.objects.get(id=job_id, project=current_project)
        job_title = job.title
        job.delete()
        return JsonResponse({
            'status': 'success',
            'message': f'Job profile "{job_title}" berhasil dihapus'
        })
    except JobProfile.DoesNotExist:
        return JsonResponse(
            {'status': 'error', 'message': 'Job profile tidak ditemukan'},
            status=404
        )
    except Exception as e:
        return JsonResponse(
            {'status': 'error', 'message': str(e)},
            status=500
        )

@master_required
def guide_view(request):
    """Halaman panduan master — gak ada query DB, cuma render template static."""
    return render(request, 'master/guide.html')
 

@master_required
def performance_individual_view(request, user_id):
    """Detail performance per user (annotator/reviewer)."""
    current_project, current_role, redirect_response = get_current_project_or_redirect(request)
    if redirect_response:
        return redirect_response

    user = get_object_or_404(CustomUser, id=user_id, role__in=["annotator", "reviewer"])
    if not ProjectMember.objects.filter(project=current_project, user=user).exists():
        messages.error(request, 'User tersebut bukan member project ini.')
        return redirect('master:performance')

    # Jobs sesuai role
    if user.role == 'annotator':
        user_jobs = JobProfile.objects.filter(project=current_project, worker_annotator=user)
    else:
        user_jobs = JobProfile.objects.filter(project=current_project, worker_reviewer=user)

    user_images = JobImage.objects.filter(job__in=user_jobs)
    total_jobs = user_jobs.count()
    total_images = user_images.count()

    # Job + image counts
    job_counts = {
        'assigned':    user_jobs.filter(status='not_assign').count(),
        'in_progress': user_jobs.filter(status='in_progress').count(),
        'in_review':   user_jobs.filter(status='in_review').count(),
        'completed':   user_jobs.filter(status='finish').count(),
    }
    image_counts = {
        'unannotated': user_images.filter(status='unannotated').count(),
        'annotated':   user_images.filter(status='annotated').count(),
        'in_review':   user_images.filter(status='in_review').count(),
        'in_rework':   user_images.filter(status='in_rework').count(),
        'finished':    user_images.filter(status='finished').count(),
    }

    # Helper chart height
    def _h(count, max_count, min_h=20):
        if count == 0 or max_count == 0:
            return 0
        return max(min_h, round((count / max_count) * 80))

    max_job = max(job_counts.values()) if job_counts.values() else 1
    max_img = max(image_counts.values()) if any(image_counts.values()) else 1

    # === Bangun context sesuai template ===
    user_profile = {
        'email': user.email,
        'name': f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username,
        'role': user.role,
        'status': 'Active' if user.is_active else 'Inactive',
        'status_class': 'bg-green-500' if user.is_active else 'bg-gray-400',
    }

    user_stats = {
        'total_jobs': total_jobs,
        'total_images': total_images,
        'completion_percentage': round((image_counts['finished'] / total_images * 100)) if total_images > 0 else 0,
        'chart_data': {
            'assign':    {'count': job_counts['assigned'],    'height': _h(job_counts['assigned'], max_job)},
            'progress':  {'count': job_counts['in_progress'], 'height': _h(job_counts['in_progress'], max_job)},
            'reworking': {'count': job_counts['in_review'],   'height': _h(job_counts['in_review'], max_job)},
            'finished':  {'count': job_counts['completed'],   'height': _h(job_counts['completed'], max_job)},
        },
        'image_chart_data': {
            'unannotated': {'count': image_counts['unannotated'], 'height': _h(image_counts['unannotated'], max_img, 25)},
            'annotated':   {'count': image_counts['annotated'],   'height': _h(image_counts['annotated'],   max_img, 25)},
            'progress':    {'count': image_counts['in_review'],   'height': _h(image_counts['in_review'],   max_img, 25)},
            'rework':      {'count': image_counts['in_rework'],   'height': _h(image_counts['in_rework'],   max_img, 25)},
            'finished':    {'count': image_counts['finished'],    'height': _h(image_counts['finished'],    max_img, 25)},
        },
    }

    return render(request, "master/performance_individual.html", {
        'current_project': current_project,
        'user_profile': user_profile,
        'user_stats': user_stats,
        'user_jobs_list': user_jobs,
    })

def forgot_password_view(request):
    """Halaman web: input email buat request reset link."""
    return render(request, 'master/forgot_password.html')


def reset_password_view(request, uidb64, token):
    """Halaman web: set password baru via token."""
    return render(request, 'master/reset_password.html', {
        'uid': uidb64,
        'token': token,
    })
    
    
from django.shortcuts import render

def explore_datasets(request):
    """
    Menarik data ASLI dari model Dataset yang statusnya sudah 'published'.
    """
    # Ambil dataset dari database
    datasets = Dataset.objects.filter(status_publikasi='published').order_by('-date_created')
    
    # Fitur Pencarian (Search Bar)
    search_query = request.GET.get('q', '')
    if search_query:
        datasets = datasets.filter(name__icontains=search_query)
        
    context = {
        'datasets': datasets,
        'search_query': search_query,
    }
    
    return render(request, 'master/explore.html', context)

def dataset_detail(request, dataset_id):
    """
    View untuk menampilkan detail lengkap sebuah dataset,
    termasuk kolom komentar dan fitur tambah komentar.
    """
    # 1. Ambil dataset berdasarkan ID.
    # Jika dataset tidak ditemukan (atau mungkin ID salah), akan otomatis ke halaman 404 (Not Found).
    dataset = get_object_or_404(Dataset, id=dataset_id)
    
    # 2. Logika untuk menangani form komentar (saat user klik "Kirim Komentar")
    if request.method == 'POST':
        # Pastikan hanya user yang sudah login yang bisa komentar
        if request.user.is_authenticated:
            komentar_teks = request.POST.get('text')
            
            # Validasi agar komentar tidak kosong
            if komentar_teks and komentar_teks.strip():
                # Simpan komentar ke database
                DatasetComment.objects.create(
                    dataset=dataset,
                    user=request.user,
                    text=komentar_teks
                )
                messages.success(request, "Komentar Anda berhasil ditambahkan!")
                # Refresh halaman (Redirect) agar komentar baru langsung muncul
                return redirect('master:dataset_detail', dataset_id=dataset.id)
            else:
                messages.error(request, "Komentar tidak boleh kosong.")
        else:
            messages.error(request, "Anda harus login untuk memberikan komentar.")
            return redirect('master:login') # Arahkan ke halaman login

    # 3. Ambil semua komentar yang terkait dengan dataset ini,
    # urutkan dari yang terbaru (tanda minus '-' pada '-created_at')
    comments = dataset.comments.all().order_by('-created_at')

    context = {
        'dataset': dataset,
        'comments': comments,
    }
    
    return render(request, 'master/dataset_detail.html', context)

@login_required
@require_http_methods(["POST"])
def ajukan_publikasi_view(request):
    try:
        current_project, current_role, redirect_response = get_current_project_or_redirect(request)
        if redirect_response:
            return JsonResponse({'status': 'error', 'message': 'Pilih project dari lobby terlebih dahulu.'}, status=403)

        job_id = request.POST.get('job_id')
        name = request.POST.get('name')
        description = request.POST.get('description')
        dataset_file = request.FILES.get('dataset_file')

        if not all([job_id, name, dataset_file]):
            return JsonResponse({'status': 'error', 'message': 'Nama dan file dataset wajib diisi!'}, status=400)

        # Ambil data job terkait
        job = get_object_or_404(JobProfile, id=job_id, project=current_project)

        # Buat dataset baru dengan status pending
        Dataset.objects.create(
            project=current_project,
            name=name,
            description=description,
            labeler=request.user,  # Master yang mengajukan
            file_path=dataset_file,
            status_publikasi='pending',  # <--- Ini kuncinya agar dinilai komisi
            annotation_type=job.get_shape_type_display(), 
            count=JobImage.objects.filter(job=job).count()
        )

        return JsonResponse({
            'status': 'success', 
            'message': 'Dataset berhasil dikirim! Menunggu ulasan dari Komisi.'
        })

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)