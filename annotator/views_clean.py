from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.conf import settings
from django.views.decorators.csrf import csrf_protect
from django.http import JsonResponse
from functools import wraps
from master.models import JobProfile, JobImage, CustomUser, Notification
from django.utils import timezone

def annotator_required(view_func):
    """
    Decorator untuk memastikan hanya user dengan role 'annotator' yang bisa akses view tertentu
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('annotator:signin')
        
        if request.user.role != 'annotator':
            messages.error(request, 'Anda tidak memiliki akses sebagai annotator.')
            return redirect('annotator:signin')
        
        return view_func(request, *args, **kwargs)
    return wrapper

@csrf_protect
def signin_view(request):
    """View untuk sign in khusus annotator"""
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        
        # Authenticate user
        user = authenticate(request, username=email, password=password)
        
        if user is not None and user.role == 'annotator':
            login(request, user)
            messages.success(request, f'Selamat datang, {user.username}!')
            return redirect('annotator:annotate')
        else:
            messages.error(request, 'Email, password salah, atau Anda bukan annotator.')
    
    return render(request, 'annotator/signin.html')

def signout_view(request):
    """View untuk sign out"""
    logout(request)
    messages.success(request, 'Anda telah logout.')
    return redirect('annotator:signin')

@annotator_required
def annotate_view(request):
    """Main annotator dashboard - menampilkan jobs yang di-assign ke user"""
    # Get jobs assigned to current annotator
    jobs = JobProfile.objects.filter(worker_annotator=request.user).order_by('-date_created')
    
    # Add image counts and status info for each job
    for job in jobs:
        job.total_images = job.images.count()
        job.completed_images = job.images.filter(status__in=['annotated', 'finished']).count()
        job.completion_percentage = (job.completed_images / job.total_images * 100) if job.total_images > 0 else 0
    
    context = {
        'jobs': jobs,
        'user': request.user,
    }
    return render(request, 'annotator/annotate.html', context)

@annotator_required
def job_detail_view(request, job_id):
    """Detail view untuk job tertentu dengan tabs (Data Image, Issues, Overview)"""
    job = get_object_or_404(JobProfile, id=job_id, worker_annotator=request.user)
    
    # Get all images for this job
    images = job.images.all().order_by('id')
    
    # Calculate status counts
    status_counts = {
        'unannotated': images.filter(status='unannotated').count(),
        'in_progress': images.filter(status='in_progress').count(),
        'in_review': images.filter(status='in_review').count(),
        'in_rework': images.filter(status='in_rework').count(),
        'annotated': images.filter(status='annotated').count(),
        'finished': images.filter(status='finished').count(),
    }
    
    # Filter images by status if requested
    status_filter = request.GET.get('status', 'all')
    if status_filter != 'all':
        images = images.filter(status=status_filter)
    
    # Add formatted image data
    for image in images:
        # Format image ID to match screenshot format
        image.formatted_id = f"{image.id}.jpg"
        # Add timing info if available
        image.label_time_display = image.label_time.total_seconds() if image.label_time else 0
        image.review_time_display = image.review_time.total_seconds() if image.review_time else 0
    
    context = {
        'job': job,
        'images': images,
        'status_counts': status_counts,
        'status_filter': status_filter,
        'user': request.user,
    }
    return render(request, 'annotator/job_detail.html', context)

@annotator_required
def notifications_view(request):
    """View untuk menampilkan notifications untuk annotator"""
    notifications = Notification.objects.filter(
        recipient=request.user
    ).order_by('-created_at')
    
    # Add task ID and other display info for each notification
    for notification in notifications:
        notification.task_id = notification.get_task_id()
        notification.time_display = notification.get_time_display()
    
    context = {
        'notifications': notifications,
        'user': request.user,
    }
    return render(request, 'annotator/notifications.html', context)

@annotator_required
def accept_notification_view(request, notification_id):
    """View untuk accept notification dan redirect ke job detail"""
    if request.method == 'POST':
        try:
            notification = get_object_or_404(
                Notification, 
                id=notification_id, 
                recipient=request.user
            )
            
            # Mark notification as accepted
            notification.status = 'accepted'
            notification.read_at = timezone.now()
            notification.save()
            
            # Redirect to job detail if job exists
            if notification.job:
                return JsonResponse({
                    'success': True,
                    'redirect_url': f'/annotator/job/{notification.job.id}/'
                })
            else:
                return JsonResponse({
                    'success': True,
                    'redirect_url': '/annotator/annotate/'
                })
                
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})
