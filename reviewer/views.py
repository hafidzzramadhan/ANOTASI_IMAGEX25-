from django.shortcuts import render, redirect, get_object_or_404
import base64
from PIL import Image
import os
from datetime import datetime, time
from django.utils import timezone
from django.templatetags.static import static
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.hashers import make_password, check_password
from django.contrib import messages
from functools import wraps
from master.models import CustomUser, JobProfile, JobImage, Annotation, Segmentation, Issue, Notification
from .forms import LoginForm
import re
import json


# Create your views here.
def reviewer_required(view_func):
    """
    Custom decorator that requires user to be logged in and have reviewer or master role
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('reviewer:login')
        if request.user.role not in ['reviewer', 'master']:
            messages.error(request, f'Access denied. You are logged in as {request.user.role}. This portal is for reviewers only.')
            if request.user.role == 'annotator':
                return redirect('/annotator/annotate/')
            elif request.user.role == 'master':
                return redirect('/')
            elif request.user.role == 'guest':
                messages.error(request, 'Akun Anda masih dalam status guest. Silakan tunggu admin untuk memberikan akses.')
                return redirect('/login/')
            else:
                return redirect('reviewer:login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def get_base64_images():
    # Transparent 1x1 PNG fallback so missing assets do not crash the reviewer pages.
    transparent_png = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl9kS4AAAAASUVORK5CYII="
    )

    def load_base64_or_fallback(relative_path):
        image_path = os.path.join(settings.BASE_DIR, relative_path)
        if not os.path.exists(image_path):
            return transparent_png

        with open(image_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
            return f"data:image/png;base64,{encoded_string}"

    logo_base64 = load_base64_or_fallback("reviewer/static/reviewer/image/logo-trisakti.png")
    logo_search_base64 = load_base64_or_fallback("reviewer/static/reviewer/image/logo-search.png")
    nav_reviewer_base64 = load_base64_or_fallback("reviewer/static/reviewer/image/nav-reviewer.png")
    nav_isu_base64 = load_base64_or_fallback("reviewer/static/reviewer/image/nav-isu.png")
    nav_proses_base64 = load_base64_or_fallback("reviewer/static/reviewer/image/nav-proses.png")
    nav_notif_base64 = load_base64_or_fallback("reviewer/static/reviewer/image/nav-notif.png")
    nav_username_base64 = load_base64_or_fallback("reviewer/static/reviewer/image/nav-username.png")

    context = {
        "logo_base64": logo_base64,
        "logo_search_base64": logo_search_base64,
        "nav_reviewer_base64": nav_reviewer_base64,
        "nav_isu_base64": nav_isu_base64,
        "nav_proses_base64": nav_proses_base64,
        "nav_notif_base64": nav_notif_base64,
        "nav_username_base64": nav_username_base64,
    }
    return context


@reviewer_required
def home_reviewer(request):
    user = request.user

    username = user.username
    number_email = user.email or user.phone_number or ''
    user_id = user.id

    list_ProfileJob = JobProfile.objects.filter(worker_reviewer=user_id)

    print(f"DEBUG: Found {list_ProfileJob.count()} profiles for user {user_id}")
    for profile in list_ProfileJob:
        print(f"DEBUG: Profile ID={profile.id}, Title='{profile.title}', End Date={profile.end_date}")

    tasks = []
    now = timezone.localtime()

    for profile in list_ProfileJob:
        deadline = datetime.combine(profile.end_date, time.max)
        deadline = timezone.make_aware(deadline, now.tzinfo)

        delta = deadline - now
        total_seconds = int(delta.total_seconds())

        if total_seconds <= 0:
            tr = "Times Up"
        else:
            hours, rem = divmod(total_seconds, 3600)
            if hours > 0:
                tr = f"{hours} hours left"
            else:
                minutes, seconds = divmod(rem, 60)
                if minutes > 0:
                    tr = f"{minutes} minutes left"
                else:
                    tr = "less than 1 minute"

        job_images_count = JobImage.objects.filter(job=profile).count()

        tasks.append({
            'profile': profile,
            'job_images_count': job_images_count,
            'time_remaining': tr
        })

    # Status counts buat KPI cards di home_reviewer template baru
    status_counts = {
        'total': len(tasks),
        'in_progress': sum(1 for t in tasks if t['profile'].status == 'in_progress'),
        'in_review':   sum(1 for t in tasks if t['profile'].status == 'in_review'),
        'finish':      sum(1 for t in tasks if t['profile'].status == 'finish'),
        'urgent':      sum(
            1 for t in tasks
            if 'Times Up' in t['time_remaining'] or 'minute' in t['time_remaining']
        ),
    }

    context = {
        'username': username,
        'number_email': number_email,
        'tasks': tasks,
        'status_counts': status_counts,
        **get_base64_images(),
    }
    return render(request, "reviewer/home_reviewer.html", context)


@reviewer_required
def task_review(request, id):
    user = request.user

    username = user.username
    number_email = user.email or user.phone_number or ''
    user_id = user.id

    profile = get_object_or_404(JobProfile, id=id, worker_reviewer=user_id)

    data_job = JobImage.objects.filter(job=profile).select_related('job', 'annotator')
    total_images = data_job.count()

    context = {
        'profile_id': profile.id,
        'total_images': total_images,
        'data_job': data_job,
        'username': username,
        'number_email': number_email,
        **get_base64_images(),
    }
    return render(request, 'reviewer/task_review.html', context)


@reviewer_required
def isu(request):
    """
    Issue management list — semua issue yang dibikin oleh reviewer ini
    (atau semua issue di job yang lagi di-assign ke dia kalo dia juga master).
    """
    user = request.user
    username = user.username
    number_email = user.email or user.phone_number or ''

    # Issue list: yang dibikin oleh reviewer ini ATAU yang ada di job yang
    # ke-assign ke reviewer ini.
    issues_qs = (
        Issue.objects
        .filter(job__worker_reviewer=user)
        .select_related('job', 'image', 'assigned_to', 'created_by')
        .order_by('-created_at')
    )

    issue_counts = {
        'total':     issues_qs.count(),
        'open':      issues_qs.filter(status='open').count(),
        'eskalasi':  issues_qs.filter(status='eskalasi').count(),
        'reworking': issues_qs.filter(status='reworking').count(),
        'closed':    issues_qs.filter(status='closed').count(),
    }

    context = {
        'username': username,
        'number_email': number_email,
        'issues': issues_qs,
        'issue_counts': issue_counts,
        **get_base64_images(),
    }
    return render(request, 'reviewer/isu.html', context)


@csrf_protect
def login(request):
    print(f"Login view called - Method: {request.method}")
    print(f"CSRF token in META: {request.META.get('CSRF_COOKIE')}")
    print(f"CSRF token in POST: {request.POST.get('csrfmiddlewaretoken')}")

    if request.user.is_authenticated:
        if request.user.role in ['reviewer', 'master']:
            return redirect('reviewer:home_reviewer')
        else:
            messages.warning(request, f'You are currently logged in as {request.user.role}. To use the reviewer portal, please logout first and login with a reviewer account.')

    if request.method == 'POST':
        print(f"POST data: {request.POST}")
        form = LoginForm(request.POST)
        print(f"Form is valid: {form.is_valid()}")
        if not form.is_valid():
            print(f"Form errors: {form.errors}")

        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            print(f"Attempting login with email: {email}")

            user = authenticate(request, username=email, password=password)
            if user is not None and user.is_active:
                print(f"User authenticated: {user.username}, role: {user.role}")
                if user.role in ['reviewer', 'master']:
                    auth_login(request, user)
                    return redirect('reviewer:home_reviewer')
                else:
                    form.add_error(None, 'Access denied. This portal is for reviewers only.')
            else:
                print("Authentication failed")
                form.add_error(None, 'Invalid email or password.')

        context = {
            'form': form,
            **get_base64_images(),
        }
        return render(request, 'reviewer/login.html', context)
    else:
        form = LoginForm()
        context = {
            'form': form,
            **get_base64_images(),
        }
        return render(request, 'reviewer/login.html', context)


@reviewer_required
def isu_anotasi(request, index=0):
    user = request.user
    profile_id_raw = request.GET.get('profile_id') or request.session.get('profile_id')
    try:
        profile_id = int(profile_id_raw)
    except (TypeError, ValueError):
        return redirect('reviewer:home_reviewer')

    profile = JobProfile.objects.filter(id=profile_id, worker_reviewer=user.id).first()
    if not profile:
        return redirect('reviewer:home_reviewer')

    job_images = (
        JobImage.objects
        .filter(job_id=profile_id)
        .select_related('job')
        .order_by('id')
    )
    total = job_images.count()
    if total == 0:
        return render(request, 'reviewer/tidak_ada_gambar.html')
    if index < 0 or index >= total:
        return redirect('reviewer:isu_anotasi', index=0)

    image_sizes = []
    for img in job_images:
        try:
            path = img.image.path
            with Image.open(path) as im:
                width, height = im.size
                image_sizes.append({'width': width, 'height': height})
        except Exception:
            image_sizes.append({'width': 0, 'height': 0})

    job_image = job_images[index]
    gambar = job_image.image
    current_image_size = image_sizes[index]
    job_profile = job_image.job.id

    segmentasi_list = Segmentation.objects.filter(job=job_image)
    anotasi_list = Annotation.objects.filter(job_image=job_image)

    anotasi_semantic = anotasi_list.filter(segmentation__segmentation_type__name='semantic')
    anotasi_instance = anotasi_list.filter(segmentation__segmentation_type__name='instance')
    anotasi_panoptic = anotasi_list.filter(segmentation__segmentation_type__name='panoptic')

    polygon_semantic_list = [
        {
            'warna': a.segmentation.color,
            'label': a.segmentation.label,
            'points': " ".join(f"{p.x_coordinate},{p.y_coordinate}" for p in a.polygon_points.all().order_by('order'))
        }
        for a in anotasi_semantic if a.polygon_points.exists()
    ]

    polygon_panoptic_list = [
        {
            'warna': a.segmentation.color,
            'label': a.segmentation.label,
            'points': " ".join(f"{p.x_coordinate},{p.y_coordinate}" for p in a.polygon_points.all().order_by('order'))
        }
        for a in anotasi_panoptic if a.polygon_points.exists()
    ]

    segmentasi_anotasi_info = []
    for segmentasi in segmentasi_list:
        anotasi_terkait = anotasi_list.filter(segmentation=segmentasi)
        anotasi_items = []
        for i, anotasi in enumerate(anotasi_terkait, start=1):
            anotasi_items.append({
                'anotasi_id': anotasi.id,
                'nama': f"{segmentasi.label} {i}",
                'warna': segmentasi.color,
                'label': segmentasi.label,
                'tipe': segmentasi.segmentation_type.name.title(),
            })
        if anotasi_items:
            segmentasi_anotasi_info.extend(anotasi_items)

    # Calculate status counts
    pending_count = job_images.filter(status='pending').count()
    in_progress_count = job_images.filter(status='in_progress').count()
    annotated_count = job_images.filter(status='annotated').count()
    reviewed_count = job_images.filter(status='reviewed').count()
    unannotated_count = job_images.filter(status='unannotated').count()
    in_review_count = job_images.filter(status='in_review').count()
    in_rework_count = job_images.filter(status='in_rework').count()
    finished_count = job_images.filter(status='finished').count()

    issues_count = Issue.objects.filter(image__job_id=profile_id).count()

    annotation_data = []
    for ann in anotasi_list:
        if hasattr(ann, 'x_min') and hasattr(ann, 'y_min') and hasattr(ann, 'x_max') and hasattr(ann, 'y_max'):
            annotation_data.append({
                'label': ann.segmentation.label if ann.segmentation else 'Unknown',
                'bbox': [ann.x_min, ann.y_min, ann.x_max, ann.y_max],
                'is_auto_generated': getattr(ann, 'is_auto_generated', False)
            })

    print(f"DEBUG: Annotation data prepared for reviewer: {annotation_data}")
    print("JobImage ID:", job_image.id)
    print("Segmentasi count:", segmentasi_list.count())
    print("Anotasi count:", anotasi_list.count())
    print("Semantic annotations:", anotasi_semantic.count())
    print("Panoptic annotations:", anotasi_panoptic.count())

    context = {
        'username': user.username,
        'number_email': user.email or getattr(user, 'phone_number', '') or '',
        'profile_id': profile_id,
        'nama_profile_job': profile.title,
        'filename': gambar.name,
        'gambar': gambar,
        'gambar_id': job_image.id,
        'image_index': index + 1,
        'total_images': total,
        'pending_count': pending_count,
        'in_progress_count': in_progress_count,
        'annotated_count': annotated_count,
        'reviewed_count': reviewed_count,
        'unannotated_count': unannotated_count,
        'in_review_count': in_review_count,
        'in_rework_count': in_rework_count,
        'finished_count': finished_count,
        'issues_count': issues_count,
        'segmentasi_list': segmentasi_list,
        'anotasi_list': anotasi_list,
        'anotasi_box': anotasi_instance,
        'lebar_gambar': current_image_size['width'],
        'tinggi_gambar': current_image_size['height'],
        'image_sizes': image_sizes,
        'polygon_semantic_list': polygon_semantic_list,
        'polygon_panoptic_list': polygon_panoptic_list,
        'total_semantic': anotasi_semantic.count(),
        'total_instance': anotasi_instance.count(),
        'total_panoptic': anotasi_panoptic.count(),
        'segmentasi_anotasi_info': segmentasi_anotasi_info,
        'annotations_json': json.dumps(annotation_data),
        **get_base64_images(),
    }
    return render(request, 'reviewer/isu_anotasi.html', context)


@reviewer_required
def isu_image(request):
    """
    Image-issues view. Dua mode:
      - ?image_id=<id>  → focus mode: tampilin satu image + semua issue-nya
      - tanpa param     → grouped mode: list image yang punya >=1 issue
    """
    from collections import OrderedDict

    user = request.user
    username = user.username
    number_email = user.email or user.phone_number or ''

    image_id_raw = request.GET.get('image_id')
    focus_image = None
    image_issues = []
    grouped_images = []

    if image_id_raw:
        try:
            image_id = int(image_id_raw)
            focus_image = (
                JobImage.objects
                .select_related('job', 'annotator')
                .filter(id=image_id, job__worker_reviewer=user)
                .first()
            )
            if focus_image:
                image_issues = (
                    Issue.objects
                    .filter(image=focus_image)
                    .select_related('assigned_to', 'created_by')
                    .order_by('-created_at')
                )
        except (TypeError, ValueError):
            focus_image = None

    if not focus_image:
        # Grouped mode: kumpulin image yang punya >=1 issue
        grouped = OrderedDict()
        issues_with_image = (
            Issue.objects
            .filter(job__worker_reviewer=user, image__isnull=False)
            .select_related('image', 'image__job')
            .order_by('-created_at')
        )
        for iss in issues_with_image:
            img = iss.image
            if img.id not in grouped:
                grouped[img.id] = {'image': img, 'count': 0}
            grouped[img.id]['count'] += 1
        grouped_images = list(grouped.values())

    context = {
        'username': username,
        'number_email': number_email,
        'focus_image': focus_image,
        'image_issues': image_issues,
        'grouped_images': grouped_images,
        **get_base64_images()
    }
    return render(request, 'reviewer/isu_image.html', context)


@csrf_protect
@reviewer_required
def finish_review_view(request, image_id):
    """
    Mark review as finished and notify master
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    try:
        image_obj = get_object_or_404(JobImage, id=image_id)

        if image_obj.job.worker_reviewer != request.user:
            return JsonResponse({'success': False, 'error': 'You are not assigned to this job'}, status=403)

        image_obj.status = 'finished'
        image_obj.review_time = timezone.now()
        image_obj.save()

        job_profile = image_obj.job
        total_images = JobImage.objects.filter(job=job_profile).count()
        finished_images = JobImage.objects.filter(job=job_profile, status='finished').count()

        if total_images == finished_images:
            job_profile.status = 'finish'
            job_profile.save()

        return JsonResponse({
            'success': True,
            'message': 'Review marked as finished',
            'job_completed': total_images == finished_images
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# REVIEWER TASK FLOW (accept / done / drop / make_issue)
# Integrated from reviewer/views.py temen — fitur core review flow.
# YOLO+SAM auto_segmentation TIDAK diambil (reviewer cuma review, gak relabel).
# ─────────────────────────────────────────────────────────────────────────────

@reviewer_required
def accept_task(request, profile_id):
    """
    Reviewer menerima sebuah JobProfile untuk di-review.
    Status JobProfile: in_progress -> in_review.
    """
    profile = get_object_or_404(JobProfile, id=profile_id, worker_reviewer=request.user)
    profile.status = 'in_review'
    profile.save()
    messages.success(request, f'Task "{profile.title}" diterima. Selamat me-review!')
    return redirect('reviewer:isu')


@reviewer_required
def done_task(request, profile_id):
    """
    Reviewer menyatakan SEMUA gambar di Job ini selesai di-review.
    Set JobProfile.status = finish, dan semua JobImage yang belum finished
    di-mark finished.
    Notify master kalo job sudah selesai sepenuhnya (TODO bisa diaktifin).
    """
    profile = get_object_or_404(JobProfile, id=profile_id, worker_reviewer=request.user)
    profile.status = 'finish'
    profile.save()

    # Mark semua image yang belum finished
    JobImage.objects.filter(job=profile).exclude(status='finished').update(status='finished')

    messages.success(
        request,
        f'Job "{profile.title}" selesai dan dikirim ke Master.'
    )
    return redirect('reviewer:isu')


@reviewer_required
def drop_task(request, profile_id):
    """
    Reviewer drop task (kembalikan ke in_progress, biar reviewer lain bisa ambil
    atau annotator masih bisa kerja).
    """
    profile = get_object_or_404(JobProfile, id=profile_id, worker_reviewer=request.user)
    profile.status = 'in_progress'
    profile.save()
    messages.warning(request, f'Job "{profile.title}" telah di-drop kembali ke In Progress.')
    return redirect('reviewer:isu')


@csrf_protect
@reviewer_required
def make_issue_view(request, image_id):
    """
    Reviewer bikin issue di sebuah gambar.
    Body JSON: {"note": "...", "title": "...", "priority": "low|medium|high"}
    Side effect:
      - Create Issue(status='open', assigned_to=annotator yang ngerjain)
      - Set JobImage.status = 'in_rework'
      - Kirim Notification ke annotator (notification_type='issue_created')
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    try:
        data      = json.loads(request.body)
        note      = data.get('note', '').strip()
        title     = data.get('title', '').strip() or f"Issue on image {image_id}"
        priority  = data.get('priority', 'medium')

        if not note:
            return JsonResponse({'success': False, 'error': 'Note/description tidak boleh kosong'}, status=400)

        image_obj = get_object_or_404(JobImage, id=image_id)

        # Cek reviewer assigned ke job ini
        if image_obj.job.worker_reviewer != request.user:
            return JsonResponse({'success': False, 'error': 'You are not the reviewer for this job'}, status=403)

        # Tentukan annotator yang harus ngerjain
        target_annotator = image_obj.annotator or image_obj.job.worker_annotator
        if not target_annotator:
            return JsonResponse({'success': False, 'error': 'Tidak ada annotator yang ter-assign di gambar ini'}, status=400)

        # 1. Bikin Issue
        issue = Issue.objects.create(
            job=image_obj.job,
            image=image_obj,
            assigned_to=target_annotator,
            created_by=request.user,
            title=title,
            description=note,
            priority=priority if priority in ('low', 'medium', 'high') else 'medium',
            status='open',
        )

        # 2. Set image ke in_rework biar annotator tau harus benerin
        image_obj.status = 'in_rework'
        image_obj.save()

        # 3. Notify annotator
        Notification.objects.create(
            recipient=target_annotator,
            sender=request.user,
            notification_type='issue_created',
            title=f'Issue baru di "{image_obj.job.title}"',
            message=f'Reviewer {request.user.username} kasih feedback: {note[:140]}',
            job=image_obj.job,
            issue=issue,
        )

        return JsonResponse({
            'success': True,
            'message': 'Issue dibuat dan annotator sudah dinotifikasi',
            'issue_id': issue.id,
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def logout(request):
    """Logout view for reviewers"""
    auth_logout(request)
    return redirect('reviewer:login')