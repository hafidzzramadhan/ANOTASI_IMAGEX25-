from django.shortcuts import render, redirect, get_object_or_404
import os
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib import messages
from django.conf import settings
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from django.http import JsonResponse
from functools import wraps
from master.models import JobProfile, JobImage, Notification, Issue, Annotation
from django.utils import timezone
from django.db.models import Count, Q
import json
from django.http import HttpResponse
import requests

AI_API_URL = "https://pursue-various-engineer-corporate.trycloudflare.com/api/proses-gambar/"


# Create your views here.

def annotator_required(view_func):
    """
    Custom decorator that requires user to be logged in and have annotator role
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('/annotator/signin/')
        if request.user.role != 'annotator':
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

        if User.objects.filter(username=username).exists():
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
                first_name=nama_depan,
                last_name=nama_belakang
            )
            new_user.role = 'annotator'
            new_user.save()

            messages.success(request, f'Akun untuk {username} berhasil dibuat! Silakan masuk untuk melanjutkan.')
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
    """
    View for the main annotation page - shows jobs assigned to current annotator
    """
    jobs = JobProfile.objects.filter(worker_annotator=request.user).annotate(
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
    """
    View for the notifications page
    """
    current_user = request.user
    print(f"DEBUG: Current user = {current_user.username} (ID: {current_user.id})")
    
    notifications = Notification.objects.filter(
        recipient=current_user
    ).select_related('sender', 'job', 'issue').order_by('-created_at')
    
    print(f"DEBUG: Query result count = {notifications.count()}")
    
    context = {
        'current_page': 'notifications',
        'user': request.user,
        'notifications': notifications,
    }
    return render(request, 'annotator/notifications.html', context)


@annotator_required
def job_detail_view(request, job_id):
    """
    View for displaying the details of a specific job
    """
    job = get_object_or_404(JobProfile, id=job_id, worker_annotator=request.user)
    
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
    """
    Sign out view for annotators
    """
    logout(request)
    messages.success(request, 'You have been signed out successfully.')
    return redirect('annotator:signin')


@csrf_protect
@annotator_required
def accept_notification_view(request, notification_id):
    """
    Accept notification and update status to 'accepted'
    """
    if request.method != 'POST':
        return JsonResponse({
            'status': 'error',
            'message': 'Method not allowed'
        }, status=405)
        
    try:
        if not request.user.is_authenticated:
            return JsonResponse({
                'status': 'error',
                'message': 'Authentication required'
            }, status=401)
        
        notification = get_object_or_404(
            Notification, 
            id=notification_id, 
            recipient=request.user
        )
        
        notification.status = 'accepted'
        notification.read_at = timezone.now()
        notification.save()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Notification accepted successfully'
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=400)


@annotator_required
def label_image_view(request, job_id, image_id):

    job = get_object_or_404(JobProfile, id=job_id, worker_annotator=request.user)
    image = get_object_or_404(JobImage, id=image_id, job=job)

    all_images = job.images.all()
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

    status_counts = {
        'unannotated': all_images.filter(status='unannotated').count(),
        'in_progress': all_images.filter(status='in_progress').count(),
        'annotated': all_images.filter(status='annotated').count(),
        'in_review': all_images.filter(status='in_review').count(),
        'in_rework': all_images.filter(status='in_rework').count(),
        'finished': all_images.filter(status='finished').count(),
        'issue': all_images.filter(status__in=['issue', 'Issue']).count(),
    }

    annotations_qs = image.annotations.all()
    print(f"DEBUG: Total annotations found for image {image_id}: {annotations_qs.count()}")

    classes = list(set(ann.label for ann in annotations_qs if ann.label))
    classes.sort()
    print(f"DEBUG: Classes found: {classes}")

    annotation_data = []
    for ann in annotations_qs:
        annotation_data.append({
            'label': ann.label,
            'bbox': [ann.x_min, ann.y_min, ann.x_max, ann.y_max],
            'is_auto_generated': ann.is_auto_generated
        })

    print(f"DEBUG: Annotation data prepared: {annotation_data}")

    context = {
        'current_page': 'annotate',
        'user': request.user,
        'job': job,
        'image': image,
        'classes': classes,
        'status_counts': status_counts,
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
    
    image_obj = get_object_or_404(JobImage, id=image_id)
    image_file = image_obj.image

    try:
        files = {'file': (image_file.name, image_file.open('rb'))}
        response = requests.post(AI_API_URL, files=files, timeout=60)
        response.raise_for_status()

        annotation_data = response.json()
        print("--- MULAI DEBUG PROSES SIMPAN ---")
        print("Debug: Data mentah diterima ->", annotation_data)

        detections = annotation_data.get('detections', [])
        print(f"Debug: Ditemukan total {len(detections)} deteksi dari AI.")
        
        saved_count = 0
        for i, ann in enumerate(detections):
            box = ann.get('bbox')
            label = ann.get('label_vgg16')
            confidence = ann.get('confidence')

            print(f"\nDebug [{i+1}/{len(detections)}]: Memproses label '{label}' dengan box {box}, confidence: {confidence}")

            if box and label and len(box) == 4:
                try:
                    Annotation.objects.create(
                        job_image=image_obj,
                        label=label,
                        x_min=box[0],
                        y_min=box[1],
                        x_max=box[2],
                        y_max=box[3],
                        x_coordinate=box[0],
                        y_coordinate=box[1],
                        width=box[2] - box[0],
                        height=box[3] - box[1],
                        confidence_score=confidence,
                        is_auto_generated=True,
                        annotator=request.user,
                        created_by=request.user,
                        notes='',
                        is_verified=False
                    )
                    saved_count += 1
                    print(f"Debug: Anotasi untuk '{label}' BERHASIL disimpan.")

                except Exception as e:
                    print(f"!!! DEBUG: GAGAL menyimpan anotasi untuk '{label}'. Error: {e}")
            else:
                print(f"Debug: Data untuk '{label}' tidak valid atau tidak lengkap, dilewati.")
        
        print(f"\n--- SELESAI DEBUG ---")
        print(f"Debug: Total anotasi yang berhasil disimpan: {saved_count} dari {len(detections)}")

        if saved_count > 0:
            image_obj.status = 'annotated'
            image_obj.save()
            print(f"Debug: Status gambar diubah menjadi 'annotated'")
        else:
            print(f"Debug: Tidak ada anotasi yang disimpan, status tetap {image_obj.status}")

        return JsonResponse({'success': True, 'message': 'Gambar berhasil dikirim dan anotasi diterima.'})

    except requests.exceptions.RequestException as e:
        return JsonResponse({'success': False, 'error': f'Gagal menghubungi sistem cerdas: {e}'}, status=500)
    except json.JSONDecodeError:
        error_msg = 'Gagal mem-parsing JSON dari sistem cerdas. Respons: ' + response.text
        return JsonResponse({'success': False, 'error': error_msg}, status=500)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def get_result_json(request, image_id):
    image_obj = get_object_or_404(JobImage, id=image_id)

    annotations = Annotation.objects.filter(job_image=image_obj).values(
        'label', 'x_min', 'y_min', 'x_max', 'y_max', 'is_auto_generated'
    )
    return JsonResponse(list(annotations), safe=False)


@csrf_protect
@annotator_required
def finish_annotation_view(request, image_id):
    """
    Mark annotation as finished and send to reviewer
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)
    
    try:
        image_obj = get_object_or_404(JobImage, id=image_id)
        
        if image_obj.job.worker_annotator != request.user:
            return JsonResponse({'success': False, 'error': 'You are not assigned to this job'}, status=403)
        
        image_obj.status = 'in_review'
        image_obj.save()
        
        return JsonResponse({
            'success': True, 
            'message': 'Annotation marked as finished and sent for review'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)