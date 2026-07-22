from django.shortcuts import render, redirect, get_object_or_404
import os
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib import messages
from django.conf import settings
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from django.http import JsonResponse
from functools import wraps
# --- [CATATAN: TAMBAHAN BARU 1] - Import MasterLabel, Segmentation, SegmentationType, AnnotationTool di atas agar rapi ---
from master.models import JobProfile, JobImage, Notification, Issue, IssueComment, Annotation, MasterLabel, Segmentation, SegmentationType, AnnotationTool, ProjectMember
from django.utils import timezone
from django.db.models import Count, Q
import json
from django.http import HttpResponse
import requests
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
import random
from master.auth_utils import ensure_unverified_email_address, is_email_verified
from master.email_utils import send_activation_email

# --- [CATATAN: TAMBAHAN BARU 2] - Import Serializer untuk API Dropdown ---
# Pastikan file serializers.py sudah ada dan MasterLabelSerializer sudah dibuat di dalamnya
from .serializers import MasterLabelSerializer

AI_API_URL = getattr(settings, 'AI_API_URL', 'https://hazards-root-taking-res.trycloudflare.com/api/proses-gambar/')
logger = logging.getLogger(__name__)
YOLO_TRANSLATIONS = {
    'person': 'orang', 'bicycle': 'sepeda', 'car': 'mobil', 'motorcycle': 'motor',
    'airplane': 'pesawat', 'bus': 'bus', 'train': 'kereta', 'truck': 'truk',
    'boat': 'kapal', 'traffic light': 'lampu lalu lintas', 'fire hydrant': 'hidran',
    'stop sign': 'rambu stop', 'parking meter': 'meteran parkir', 'bench': 'bangku',
    'bird': 'burung', 'cat': 'kucing', 'dog': 'anjing', 'horse': 'kuda',
    'sheep': 'domba', 'cow': 'sapi', 'elephant': 'gajah', 'bear': 'beruang',
    'zebra': 'zebra', 'giraffe': 'jerapah', 'backpack': 'ransel', 'umbrella': 'payung',
    'handbag': 'tas tangan', 'tie': 'dasi', 'suitcase': 'koper', 'frisbee': 'frisbee',
    'skis': 'ski', 'snowboard': 'papan salju', 'sports ball': 'bola', 'kite': 'layang-layang',
    'baseball bat': 'tongkat bisbol', 'baseball glove': 'sarung bisbol', 'skateboard': 'skateboard',
    'surfboard': 'papan selancar', 'tennis racket': 'raket tenis', 'bottle': 'botol',
    'wine glass': 'gelas anggur', 'cup': 'cangkir', 'fork': 'garpu', 'knife': 'pisau',
    'spoon': 'sendok', 'bowl': 'mangkuk', 'banana': 'pisang', 'apple': 'apel',
    'sandwich': 'roti lapis', 'orange': 'jeruk', 'broccoli': 'brokoli', 'carrot': 'wortel',
    'hot dog': 'hot dog', 'pizza': 'pizza', 'donut': 'donat', 'cake': 'kue',
    'chair': 'kursi', 'couch': 'sofa', 'potted plant': 'tanaman pot', 'bed': 'tempat tidur',
    'dining table': 'meja makan', 'toilet': 'toilet', 'tv': 'tv', 'laptop': 'laptop',
    'mouse': 'mouse', 'remote': 'remote', 'keyboard': 'keyboard', 'cell phone': 'hp',
    'microwave': 'microwave', 'oven': 'oven', 'toaster': 'pemanggang roti', 'sink': 'wastafel',
    'refrigerator': 'kulkas', 'book': 'buku', 'clock': 'jam', 'vase': 'vas',
    'scissors': 'gunting', 'teddy bear': 'boneka beruang', 'hair drier': 'pengering rambut',
    'toothbrush': 'sikat gigi'
}

# Create your views here.

def get_current_project_for_role(request, role):
    project_id = request.session.get('current_project_id')
    if not project_id:
        messages.error(request, 'Pilih project dari lobby terlebih dahulu.')
        return None, redirect('master:lobby')
    if not ProjectMember.objects.filter(project_id=project_id, user=request.user, role=role).exists():
        messages.error(request, 'Anda bukan member project tersebut.')
        return None, redirect('master:lobby')
    return project_id, None


@login_required
def profile_view(request):
    context = {
        'page_title': 'My Profile',
    }
    return render(request, 'annotator/profile.html', context)

def annotator_required(view_func):
    """
    Custom decorator that requires user to be logged in and have annotator role
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('/annotator/signin/')
        if request.user.role != 'annotator' and request.session.get('current_project_role') != 'annotator':
            messages.error(request, f'Access denied. You are logged in as {request.user.role}. This portal is for annotators only.')
            if request.user.role == 'reviewer':
                return redirect('/reviewer/')
            elif request.user.role == 'master':
                return redirect('/')
            elif request.user.role == 'guest':
                messages.error(request, 'Akun Anda masih dalam status guest. Silakan tunggu admin untuk memberikan akses.')
                return redirect('/login/')
            else:
                return redirect('/annotator/signin/')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def signup_view(request):
    if request.user.is_authenticated:
        return redirect('annotator:annotate')

    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        nama_depan = request.POST.get('nama_depan')
        nama_belakang = request.POST.get('nama_belakang')

        User = get_user_model()

        if User.objects.filter(email=email).exists():
            messages.error(request, 'Username ini sudah digunakan')
            return redirect('annotator:signup')

        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email ini sudah terdaftar. Silakan gunakan email lain.')
            return redirect('annotator:signup')

        try:
            new_user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                is_active=False,
                first_name=nama_depan,
                last_name=nama_belakang
            )
            new_user.role = 'annotator'
            new_user.save()
            ensure_unverified_email_address(new_user)

            try:
                send_activation_email(request, new_user)
                messages.success(
                    request,
                    f'Akun untuk {username} berhasil dibuat! Silakan cek email untuk aktivasi.'
                )
            except Exception:
                logger.exception("Gagal kirim email aktivasi annotator ke %s", new_user.email)
                messages.warning(
                    request,
                    'Akun berhasil dibuat, tapi email verifikasi gagal dikirim. Hubungi admin.'
                )
            return redirect('annotator:signin')

        except Exception as e:
            messages.error(request, f'Terjadi kesalahan saat membuat akun: {e}')
            return redirect('annotator:signup')

    return render(request, 'annotator/signup.html')

@csrf_protect
def signin_view(request):
    """
    Sign in view for annotators only
    """
    if request.user.is_authenticated:
        if request.user.role == 'annotator':
            return redirect('annotator:annotate')
        else:
            messages.warning(request, f'You are currently logged in as {request.user.role}. To use the annotator portal, please logout first and login with an annotator account.')

    if request.method == 'POST':
        email = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=email, password=password)

        if user is not None:
            if user.role == 'annotator':
                if not user.is_active:
                    messages.error(request, 'Akun belum aktif.')
                    return render(request, 'annotator/signin.html')
                if not is_email_verified(user):
                    messages.error(request, 'Email belum diverifikasi. Silakan cek email verifikasi Anda.')
                    return render(request, 'annotator/signin.html')
                login(request, user)
                messages.success(request, f'See you again, {user.username}!')
                next_url = request.GET.get('next', '/annotator/annotate/')
                return redirect(next_url)
            else:
                messages.error(request, 'Access denied. This portal is for annotators only.')
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'annotator/signin.html')

@annotator_required
def annotate_view(request):
    project_id, redirect_response = get_current_project_for_role(request, 'annotator')
    if redirect_response:
        return redirect_response

    jobs = JobProfile.objects.filter(project_id=project_id, worker_annotator=request.user).annotate(
        total_images=Count('images'),
        completed_images=Count('images', filter=Q(images__status='annotated'))
    ).order_by('-date_created')

    for job in jobs:
        if job.total_images > 0:
            job.completion_percentage = round((job.completed_images / job.total_images) * 100)
        else:
            job.completion_percentage = 0

    context = {
        'current_page': 'annotate',
        'user': request.user,
        'jobs': jobs,
    }
    return render(request, 'annotator/annotate.html', context)

@annotator_required
def notifications_view(request):
    project_id, redirect_response = get_current_project_for_role(request, 'annotator')
    if redirect_response:
        return redirect_response

    current_user = request.user
    notifications = Notification.objects.filter(
        recipient=current_user
    ).select_related('sender', 'job', 'issue').order_by('-created_at')

    context = {
        'current_page': 'notifications',
        'user': request.user,
        'notifications': notifications,
    }
    return render(request, 'annotator/notifications.html', context)

@annotator_required
def dispute_issue_view(request, issue_id):
    """
    Annotator dispute issue yang di-reject reviewer (nggak setuju sama hasil review).
    Efek: issue.status 'open' -> 'eskalasi', dilempar ke master buat arbitrase.
    Cuma bisa dipanggil kalau issue itu di-assign ke annotator yang sedang login,
    dan statusnya masih 'open' (bukan yang udah eskalasi/reworking/closed).
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)

    issue = get_object_or_404(Issue, id=issue_id, assigned_to=request.user)

    if issue.status != 'open':
        return JsonResponse({
            'status': 'error',
            'message': f'Issue ini statusnya "{issue.status}". Cuma issue "open" yang bisa di-dispute.'
        }, status=400)

    reason = request.POST.get('reason', '').strip()
    if not reason:
        return JsonResponse({'status': 'error', 'message': 'Alasan dispute wajib diisi.'}, status=400)

    issue.status = 'eskalasi'
    issue.save(update_fields=['status', 'updated_at'])

    IssueComment.objects.create(
        issue=issue,
        created_by=request.user,
        message=f"[DISPUTE oleh annotator]\n\n{reason}",
    )

    # Notif ke semua master di project ini — mereka yang arbitrase
    masters = ProjectMember.objects.filter(
        project=issue.job.project, role='master'
    ).select_related('user')
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

    # Notif ke reviewer yang bikin issue-nya
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

    return JsonResponse({'status': 'success', 'message': 'Issue berhasil di-eskalasi ke master.'})


@annotator_required
def job_detail_view(request, job_id):
    project_id, redirect_response = get_current_project_for_role(request, 'annotator')
    if redirect_response:
        return redirect_response

    job = get_object_or_404(JobProfile, id=job_id, project_id=project_id, worker_annotator=request.user)
    all_images = job.images.all().order_by('id')

    current_tab = request.GET.get('tab', 'data')
    current_status = request.GET.get('status', '')
    issue_filter = request.GET.get('issue_status', 'all')

    if current_status and current_status in ['unannotated', 'in_progress', 'in_review', 'in_rework', 'annotated', 'finished']:
        images = all_images.filter(status=current_status)
    else:
        images = all_images

    status_counts = {
        'unannotated': all_images.filter(status='unannotated').count(),
        'in_progress': all_images.filter(status='in_progress').count(),
        'in_review': all_images.filter(status='in_review').count(),
        'in_rework': all_images.filter(status='in_rework').count(),
        'annotated': all_images.filter(status='annotated').count(),
        'finished': all_images.filter(status='finished').count(),
    }

    all_issues = Issue.objects.filter(job=job, assigned_to=request.user).select_related('created_by', 'image')

    if issue_filter == 'open':
        issues = all_issues.filter(status='open')
    elif issue_filter == 'eskalasi':
        issues = all_issues.filter(status='eskalasi')
    elif issue_filter == 'reworking':
        issues = all_issues.filter(status='reworking')
    elif issue_filter == 'closed':
        issues = all_issues.filter(status='closed')
    else:
        issues = all_issues

    issue_counts = {
        'open': all_issues.filter(status='open').count(),
        'eskalasi': all_issues.filter(status='eskalasi').count(),
        'reworking': all_issues.filter(status='reworking').count(),
        'closed': all_issues.filter(status='closed').count(),
    }

    context = {
        'current_page': 'annotate',
        'user': request.user,
        'job': job,
        'images': images,
        'all_images': all_images,
        'status_counts': status_counts,
        'current_tab': current_tab,
        'current_status': current_status,
        'issues': issues,
        'issue_counts': issue_counts,
        'issue_filter': issue_filter,
    }
    return render(request, 'annotator/job_detail.html', context)

def signout_view(request):
    logout(request)
    messages.success(request, 'You have been signed out successfully.')
    return redirect('annotator:signin')

@csrf_protect
@annotator_required
def accept_notification_view(request, notification_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)

    try:
        if not request.user.is_authenticated:
            return JsonResponse({'status': 'error', 'message': 'Authentication required'}, status=401)

        notification = get_object_or_404(Notification, id=notification_id, recipient=request.user)
        notification.status = 'accepted'
        notification.read_at = timezone.now()
        notification.save()

        return JsonResponse({'status': 'success', 'message': 'Notification accepted successfully'})

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@annotator_required
def label_image_view(request, job_id, image_id):
    project_id, redirect_response = get_current_project_for_role(request, 'annotator')
    if redirect_response:
        return redirect_response

    job = get_object_or_404(JobProfile, id=job_id, project_id=project_id, worker_annotator=request.user)
    image = get_object_or_404(JobImage, id=image_id, job=job)

    all_images= job.images.all()
    image_list = list(all_images.order_by('id'))
    try:
        current_index = image_list.index(image) + 1
        current_list_index = image_list.index(image)
    except ValueError:
        current_index = 1
        current_list_index = 0

    prev_image_id = None
    next_image_id = None
    if current_list_index > 0:
        prev_image_id = image_list[current_list_index - 1].id
    if current_list_index < len(image_list) - 1:
        next_image_id = image_list[current_list_index + 1].id

    # [CATATAN: Nanti bagian classes manual ini akan dihapus jika frontend sudah pakai API (sudah nyoba pake api skrg)]

    # Mengambil semua nama label dari Bank Label (MasterLabel)

    classes = list(MasterLabel.objects.values_list('name', flat=True))

    annotations_qs = image.annotations.all()

    annotation_data = []
    for ann in annotations_qs:
        annotation_data.append({
            'id': ann.id,  # Wajib ada agar pas ditarik/edit nggak error
            'label': ann.label,

            # --- [INI TAMBAHAN SUPER PENTINGNYA] ---
            'type': getattr(ann, 'type', 'box'),
            'points': getattr(ann, 'points', None),
            # ---------------------------------------

            'bbox': [ann.x_min, ann.y_min, ann.x_max, ann.y_max],
            'is_auto_generated': ann.is_auto_generated
        })

    context = {
         'current_page': 'annotate',
        'user': request.user,
        'job': job,
        'image': image,
        'classes': classes,
        'status_counts': {
            'unannotated': all_images.filter(status='unannotated').count(),
            'in_progress': all_images.filter(status='in_progress').count(),
            'in_review': all_images.filter(status='in_review').count(),
            'in_rework': all_images.filter(status='in_rework').count(),
            'annotated': all_images.filter(status='annotated').count(),
            'finished': all_images.filter(status='finished').count(),
        },
        'total_images': all_images.count(),
        'current_image_index': current_index,
        'total_image': len(image_list),
        'prev_image_id': prev_image_id,
        'next_image_id': next_image_id,
        'annotations_json': json.dumps(annotation_data)
    }

    return render(request, 'annotator/label_image.html', context)



@csrf_exempt
def send_image_view(request, image_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)

    project_id = request.session.get('current_project_id')
    if not project_id:
        return JsonResponse({'success': False, 'error': 'Pilih project dari lobby terlebih dahulu'}, status=403)

    image_obj = get_object_or_404(JobImage, id=image_id, job__project_id=project_id, job__worker_annotator=request.user)
    image_file = image_obj.image

    # 1. CEK SETTINGAN DARI JOB PROFILE [PENTING]

    # # Kita ambil tipe (box/polygon) langsung dari Job terkait

    job_type_setting = getattr(image_obj.job, 'shape_type', 'box').lower()
    # job_type_setting = 'polygon'

    # DEBUG: Cek di terminal/cmd kamu, apa yang terbaca oleh sistem?
    print(f"DEBUG: Tipe Job yang terbaca adalah: '{job_type_setting}'")

    try:
        files = {'file': (image_file.name, image_file.open('rb'))}
        response = requests.post(AI_API_URL, files=files, timeout=60)
        response.raise_for_status()

        annotation_data = response.json()
        detections = annotation_data.get('detections', [])

        saved_count = 0

        for i, ann in enumerate(detections):
            box = ann.get('bbox')
            raw_label = ann.get('label_vgg16')
            confidence = ann.get('confidence')

            if box and raw_label and len(box) == 4:
                try:
                    raw_label_lower = raw_label.lower()
                    translated_label_name = YOLO_TRANSLATIONS.get(raw_label_lower, raw_label_lower)

                    master_label, _ = MasterLabel.objects.get_or_create(
                        name=translated_label_name,
                        defaults={'color': "#{:06x}".format(random.randint(0, 0xFFFFFF))}
                    )

                    # 2. LOGIKA KONVERSI BOX KE POLYGON [PENTING]
                    if job_type_setting == 'polygon':
                        poly_points = [
                            {'x': box[0], 'y': box[1]},
                            {'x': box[2], 'y': box[1]},
                            {'x': box[2], 'y': box[3]},
                            {'x': box[0], 'y': box[3]}
                        ]
                        final_type = 'polygon'
                    else:
                        poly_points = None
                        final_type = 'box'

                    segmentation_type, _ = SegmentationType.objects.get_or_create(name='instance')
                    annotation_tool, _ = AnnotationTool.objects.get_or_create(name='AI Detection')

                    segmentation, _ = Segmentation.objects.get_or_create(
                        job=image_obj,
                        label=master_label.name,
                        defaults={
                            'segmentation_type': segmentation_type,
                            'color': master_label.color,
                        }
                    )

                    # 3. SIMPAN KE DATABASE [WAJIB ADA type DAN points]
                    Annotation.objects.create(
                        job_image=image_obj,
                        image=image_obj,
                        segmentation=segmentation,
                        tool=annotation_tool,
                        label=master_label.name,

                        # INI YANG BIKIN JADI POLYGON:
                        type=final_type,
                        points=poly_points,

                        # Data koordinat box (tetap disimpan)
                        x_min=box[0], y_min=box[1],
                        x_max=box[2], y_max=box[3],
                        x_coordinate=box[0], y_coordinate=box[1],
                        width=box[2] - box[0],
                        height=box[3] - box[1],
                        confidence_score=confidence,
                        is_auto_generated=True,
                        annotator=request.user,
                        created_by=request.user,
                        notes='AI Generated'
                    )

                    saved_count += 1
                except Exception as e:
                    print(f"Error saving: {e}")

        if saved_count > 0:
            image_obj.status = 'annotated'
            image_obj.save()

        return JsonResponse({'success': True, 'message': f'{saved_count} objek dideteksi sebagai {job_type_setting}.'})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

def get_result_json(request, image_id):
    project_id = request.session.get('current_project_id')
    image_obj = get_object_or_404(JobImage, id=image_id, job__project_id=project_id, job__worker_annotator=request.user)
    # Tambahkan 'id', 'type', dan 'points' di dalam .values()
    annotations = Annotation.objects.filter(job_image=image_obj).values(
        'id', 'label', 'type', 'points', 'x_min', 'y_min', 'x_max', 'y_max', 'is_auto_generated'
    )
    return JsonResponse(list(annotations), safe=False)

@csrf_protect
@annotator_required
def finish_annotation_view(request, image_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    try:
        project_id, redirect_response = get_current_project_for_role(request, 'annotator')
        if redirect_response:
            return JsonResponse({'success': False, 'error': 'Pilih project dari lobby terlebih dahulu'}, status=403)

        image_obj = get_object_or_404(JobImage, id=image_id, job__project_id=project_id)
        if image_obj.job.worker_annotator != request.user:
            return JsonResponse({'success': False, 'error': 'You are not assigned to this job'}, status=403)

        image_obj.status = 'in_review'
        image_obj.save()

        return JsonResponse({'success': True, 'message': 'Annotation marked as finished and sent for review'})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@csrf_exempt
def save_annotation(request, image_id):
    if request.method == 'POST':
        project_id = request.session.get('current_project_id')
        if not project_id:
            return JsonResponse({'error': 'Pilih project dari lobby terlebih dahulu'}, status=403)

        data = json.loads(request.body)
        image = get_object_or_404(JobImage, id=image_id, job__project_id=project_id, job__worker_annotator=request.user)

        ann_id = data.get('id')

        # JIKA ADA ID = UPDATE (Fitur Drag Point)
        if ann_id:
            ann = Annotation.objects.get(id=ann_id, job_image=image)
        # JIKA TIDAK ADA ID = BIKIN BARU (Fitur Draw biasa)
        else:
            ann = Annotation(job_image=image, image=image, annotator=request.user, created_by=request.user)

        # Simpan Label, Type, dan Points
        ann.label = data.get('label')
        ann.type = data.get('type', 'box')
        ann.points = data.get('points', None)

        # Tetap simpan fallback Bounding Box
        ann.x_min = data.get('x_min')
        ann.y_min = data.get('y_min')
        ann.x_max = data.get('x_max')
        ann.y_max = data.get('y_max')
        ann.x_coordinate = data.get('x_min')
        ann.y_coordinate = data.get('y_min')

        if data.get('x_max') is not None and data.get('x_min') is not None:
            ann.width = data.get('x_max') - data.get('x_min')
            ann.height = data.get('y_max') - data.get('y_min')

        ann.is_auto_generated = False
        ann.notes = 'manual'

        ann.save()

        image.status = 'in_progress'
        image.save()
        return JsonResponse({'status': 'success'})

    return JsonResponse({'error': 'invalid'})

@csrf_exempt
def delete_annotation(request, image_id):
    if request.method == 'POST':
        project_id = request.session.get('current_project_id')
        if not project_id:
            return JsonResponse({'error': 'Pilih project dari lobby terlebih dahulu'}, status=403)

        image = get_object_or_404(JobImage, id=image_id, job__project_id=project_id, job__worker_annotator=request.user)
        data = json.loads(request.body)
        ann_id = data.get('id')

        # Hapus berdasarkan ID agar jauh lebih akurat
        if ann_id:
            Annotation.objects.filter(id=ann_id, job_image=image).delete()
        else:
            # Fallback jika hapus kotak yang belum punya ID
            Annotation.objects.filter(
                job_image=image,
                x_min=data.get('x_min'),
                y_min=data.get('y_min'),
                label=data.get('label')
            ).delete()

        return JsonResponse({'status': 'deleted'})
    return JsonResponse({'error': 'invalid'})
