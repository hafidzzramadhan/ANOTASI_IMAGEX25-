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
from functools import wraps
from django.utils import timezone
import json
from .tokens import account_activation_token
from .models import CustomUser, Dataset, JobProfile, JobImage, Notification
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
        if request.user.role != 'master':
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

        # First try to authenticate with email
        user = authenticate(request, email=username_or_email, password=password)
        if user is None:
            # If email auth fails, try with username
            user = authenticate(request, username=username_or_email, password=password)

        if user is not None:
            if user.is_active:
                # Check role BEFORE logging in
                if user.role == 'guest':
                    messages.info(request, "Akun Anda masih dalam status guest. Akun akan dapat digunakan setelah mendapat akses dari admin. Anda akan mendapat notifikasi melalui email ketika akun sudah diaktifkan.")
                    return redirect("master:login")
                
                # Only log in non-guest users
                login(request, user)
                messages.success(request, "Login berhasil!")
                
                # Redirect based on user role
                if user.role == 'master':
                    return redirect("master:home")
                elif user.role == 'annotator':
                    return redirect("/annotator/")
                elif user.role == 'reviewer':
                    return redirect("/reviewer/")
                else:
                    messages.warning(request, "Role tidak dikenal. Silakan hubungi administrator.")
                    logout(request)  # Logout if unknown role
                    return redirect("master:login")
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
    # Real data for Status Section - get users with job assignments
    annotators_reviewers = CustomUser.objects.filter(role__in=['annotator', 'reviewer']).order_by('email')
    
    # Real status data - determine user status based on job assignments
    status_list = []
    for user in annotators_reviewers:
        # Check if user has active job assignments
        has_active_jobs = False
        if user.role == 'annotator':
            has_active_jobs = JobProfile.objects.filter(
                worker_annotator=user, 
                status__in=['in_progress']
            ).exists()
        elif user.role == 'reviewer':
            has_active_jobs = JobProfile.objects.filter(
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
                has_any_jobs = JobProfile.objects.filter(worker_annotator=user).exists()
            elif user.role == 'reviewer':
                has_any_jobs = JobProfile.objects.filter(worker_reviewer=user).exists()
            
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
    total_images = JobImage.objects.count()
    
    # Calculate status counts
    unannotated_count = JobImage.objects.filter(status='unannotated').count()
    in_review_count = JobImage.objects.filter(status='in_review').count()
    in_rework_count = JobImage.objects.filter(status='in_rework').count()
    finished_count = JobImage.objects.filter(status='finished').count()
    
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

    issues_count = JobImage.objects.filter(status='Issue').count()
    in_progress_count = in_review_count + in_rework_count
    
    context = {
        'users': CustomUser.objects.all(),
        'datasets': Dataset.objects.all().order_by('-date_created'),
        'status_list': status_list,
        'assignment_stats': assignment_stats,
        'in_progress_count': in_progress_count,
        'issues_count': issues_count,
    }
    return render(request, 'master/home.html', context)

@master_required
def assign_roles_view(request):
    # Get new members (guests) with project count
    new_members = CustomUser.objects.filter(role='guest')
    new_members_data = []
    
    for user in new_members:
        # Calculate project count based on job assignments
        annotator_jobs = JobProfile.objects.filter(worker_annotator=user).count()
        reviewer_jobs = JobProfile.objects.filter(worker_reviewer=user).count()
        total_projects = annotator_jobs + reviewer_jobs
        
        new_members_data.append({
            'id': user.id,
            'email': user.email,
            'phone_number': user.phone_number or '',
            'role': user.role,
            'project_count': total_projects
        })
    
    # Get existing members (non-guests) with project count
    members = CustomUser.objects.exclude(role='guest')
    members_data = []
    
    for user in members:
        # Calculate project count based on job assignments
        annotator_jobs = JobProfile.objects.filter(worker_annotator=user).count()
        reviewer_jobs = JobProfile.objects.filter(worker_reviewer=user).count()
        total_projects = annotator_jobs + reviewer_jobs
        
        members_data.append({
            'id': user.id,
            'email': user.email,
            'phone_number': user.phone_number or '',
            'role': user.role,
            'project_count': total_projects
        })
    
    return render(request, "master/assign_roles.html", {
        'new_members': new_members_data, 
        'members': members_data
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
    if request.method == 'POST':
        try:
            # Create new job profile
            job = JobProfile.objects.create(
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

    jobs = JobProfile.objects.all().order_by('-date_created', '-id')
    return render(request, "master/job_settings.html", {'jobs': jobs})

@login_required
def issue_detail_view(request, job_id):
    """
    Returns details about all images with issues for a specific job as JSON.
    
    Retrieves the job by ID and gathers all associated images marked with status 'Issue'. For each image, includes its absolute URL, annotator's email (or 'Unassigned'), and issue description. Returns a JSON response containing the job title and a list of issue images. On error, returns a JSON error message with status 500.
    """
    try:
        from .models import Annotation, Segmentation, SegmentationType, PolygonPoint
        
        job = get_object_or_404(JobProfile, id=job_id)
        print("=== Debug Info ===")
        print(f"Job ID: {job_id}")
        print(f"Job Title: {job.title}")

        # Get all images for the job, not just those with issues
        job_images = JobImage.objects.filter(job=job)
        print(f"Total images found: {job_images.count()}")

        # Also log the count of images with issues for debugging
        issues_images_count = job_images.filter(status='Issue').count()
        print(f"Images with issues found: {issues_images_count}")

        # Add status counts to the response
        unannotated_count = JobImage.objects.filter(job=job, status='unannotated').count()
        in_review_count = JobImage.objects.filter(job=job, status='in_review').count()
        in_rework_count = JobImage.objects.filter(job=job, status='in_rework').count()
        finished_count = JobImage.objects.filter(job=job, status='finished').count()
        issues_count = JobImage.objects.filter(job=job, status='Issue').count()

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
    # Ambil semua user dengan role annotator dan reviewer
    members = CustomUser.objects.filter(role__in=["annotator", "reviewer"]).order_by('role', 'email')

    # Hitung jumlah project (job) yang pernah diassign ke user (sebagai annotator/reviewer)
    member_data = []
    for user in members:
        # Hitung jumlah job sebagai annotator
        project_count = JobProfile.objects.filter(worker_annotator=user).count()
        # Hitung jumlah job sebagai reviewer
        if user.role == 'reviewer':
            project_count = JobProfile.objects.filter(worker_reviewer=user).count()
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
    total_images = JobImage.objects.count()
    
    # Calculate status counts
    unannotated_count = JobImage.objects.filter(status='unannotated').count()
    in_review_count = JobImage.objects.filter(status='in_review').count()
    in_rework_count = JobImage.objects.filter(status='in_rework').count()
    finished_count = JobImage.objects.filter(status='finished').count()
    issue_count = JobImage.objects.filter(status='Issue').count()
    
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
        if job_id:
            print(f"Fetching job details for job_id: {job_id}")
            
            # Get job with annotations
            job = JobProfile.objects.select_related(
                'worker_annotator',
                'worker_reviewer'
            ).get(id=job_id)
            
            # Get images with status, ordered by ID (ascending)
            images = job.images.all().order_by('id')
            status_counts = {
                'unannotated': images.filter(status='unannotated').count(),
                'annotated': images.filter(status='annotated').count(),
                'in_review': images.filter(status='in_review').count(),
                'in_rework': images.filter(status='in_rework').count(),
                'Issue': images.filter(status='Issue').count(),
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
            ).order_by('-date_created')
            
            print(f"Found {jobs.count()} jobs")
            
            context = {
                'jobs': jobs,
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
        job = JobProfile.objects.create(
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
        job = get_object_or_404(JobProfile, id=job_id)
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
            'issues_count': JobImage.objects.filter(job=job, status='Issue').count(),
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
    dataset = get_object_or_404(Dataset, id=dataset_id)

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
            dataset = get_object_or_404(Dataset, id=dataset_id)
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
        job_id = request.POST.get('job_id')
        job = JobProfile.objects.get(id=job_id)
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
        workers = CustomUser.objects.filter(role=role, is_active=True)
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
        data = json.loads(request.body)
        job_id = data.get('job_id')
        worker_id = data.get('worker_id')
        role = data.get('role')

        job = JobProfile.objects.get(id=job_id)
        worker = CustomUser.objects.get(id=worker_id)

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
        data = json.loads(request.body)
        job_id = data.get('job_id')
        annotator_id = data.get('annotator_id')
        reviewer_id = data.get('reviewer_id')

        if not all([job_id, annotator_id, reviewer_id]):
            return JsonResponse({
                'status': 'error',
                'message': 'Missing required fields'
            }, status=400)

        job = JobProfile.objects.get(id=job_id)
        annotator = CustomUser.objects.get(id=annotator_id)
        reviewer = CustomUser.objects.get(id=reviewer_id)

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
        job = JobProfile.objects.select_related('worker_annotator', 'worker_reviewer').get(id=job_id)

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
    """View for handling issue solving page"""
    try:
        # Get all jobs with their image counts and issues, ordered by newest first
        jobs = JobProfile.objects.all().order_by('-date_created')

        # Add additional data for each job
        for job in jobs:
            # Get total images count
            total_images = job.images.count()

            # Get finished images count
            finished_count = job.images.filter(status='finished').count()

            # Calculate progress percentage
            job.progress_percentage = int((finished_count / total_images * 100) if total_images > 0 else 0)

            # Get issues count
            job.issues_count = job.images.filter(status='Issue').count()

            # Get first image for display
            job.first_image_url = job.get_first_image_url()

        context = {
            'jobs': jobs,
            'current_date': timezone.now().strftime('%d %B %Y')
        }

        return render(request, 'master/Issue_solving.html', context)

    except Exception as e:
        print(f"Error in issue_solving_view: {e}")
        return render(request, 'master/Issue_solving.html', {
            'jobs': [],
            'current_date': timezone.now().strftime('%d %B %Y'),
            'error': str(e)
        })

@login_required
@require_http_methods(["POST"])
def finish_image(request):
    try:
        data = json.loads(request.body)
        image_id = data.get('image_id')
        image = JobImage.objects.get(id=image_id)
        image.status = 'finished'
        image.save()
        
        # Check if all images are finished and update job status
        job = image.job
        if not job.images.exclude(status='finished').exists():
            job.status = 'completed'
            job.save()
        
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
@require_http_methods(["POST"])
def finish_job(request):
    try:
        data = json.loads(request.body)
        job_id = data.get('job_id')
        job = JobProfile.objects.get(id=job_id)
        
        # Mark job as completed
        job.status = 'completed'
        job.save()
        
        # Optionally mark all images as finished if not already
        job.images.update(status='finished')
        
        return JsonResponse({'status': 'success', 'message': 'Job marked as completed successfully'})
    except JobProfile.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Job not found'}, status=404)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@master_required
def performance_individual_view(request, user_id):
    """
    Renders the individual performance page for a specific user.
    """
    # Get the user
    user = get_object_or_404(CustomUser, id=user_id, role__in=["annotator", "reviewer"])
    
    # Calculate job statistics based on user role
    if user.role == 'annotator':
        user_jobs = JobProfile.objects.filter(worker_annotator=user)
    else:  # reviewer
        user_jobs = JobProfile.objects.filter(worker_reviewer=user)
    
    total_jobs = user_jobs.count()
    
    # Get all images assigned to this user's jobs
    user_images = JobImage.objects.filter(job__in=user_jobs)
    total_images = user_images.count()
    
    # Calculate job status statistics
    job_status_counts = {
        'assigned': user_jobs.filter(status='assigned').count(),
        'in_progress': user_jobs.filter(status='in_progress').count(),
        'in_review': user_jobs.filter(status='in_review').count(),
        'completed': user_jobs.filter(status='completed').count(),
    }
    
    # Calculate image status statistics
    image_status_counts = {
        'unannotated': user_images.filter(status='unannotated').count(),
        'annotated': user_images.filter(status='annotated').count(),
        'in_review': user_images.filter(status='in_review').count(),
        'in_rework': user_images.filter(status='in_rework').count(),
        'finished': user_images.filter(status='finished').count(),
    }
    
    # Calculate height percentages for job chart
    max_job_count = max(job_status_counts.values()) if job_status_counts.values() else 1
    
    def calculate_job_height(count):
        if count == 0:
            return 0
        if max_job_count == 0:
            return 0
        percentage = (count / max_job_count) * 80
        return max(20, round(percentage))  # Minimum height increased to 20 for better visibility
    
    job_chart_data = {
        'assign': {
            'count': job_status_counts['assigned'],
            'height': calculate_job_height(job_status_counts['assigned'])
        },
        'progress': {
            'count': job_status_counts['in_progress'],
            'height': calculate_job_height(job_status_counts['in_progress'])
        },
        'reworking': {
            'count': job_status_counts['in_review'],
            'height': calculate_job_height(job_status_counts['in_review'])
        },
        'finished': {
            'count': job_status_counts['completed'],
            'height': calculate_job_height(job_status_counts['completed'])
        }
    }
    
    # Calculate height percentages for image chart
    max_image_count = max([
        image_status_counts['unannotated'],
        image_status_counts['annotated'],
        image_status_counts['in_review'],
        image_status_counts['in_rework'],
        image_status_counts['finished']
    ]) if any(image_status_counts.values()) else 1
    
    def calculate_image_height(count):
        if count == 0:
            return 0
        if max_image_count == 0:
            return 0
        percentage = (count / max_image_count) * 75  # Reduced from 80 to leave room for empty bars
        return max(25, round(percentage))  # Minimum height increased to 25 for better visibility
    
    image_chart_data = {
        'unannotated': {
            'count': image_status_counts['unannotated'],
            'height': calculate_image_height(image_status_counts['unannotated'])
        },
        'annotated': {
            'count': image_status_counts['annotated'],
            'height': calculate_image_height(image_status_counts['annotated'])
        },
        'progress': {
            'count': image_status_counts['in_review'],
            'height': calculate_image_height(image_status_counts['in_review'])
        },
        'rework': {
            'count': image_status_counts['in_rework'],
            'height': calculate_image_height(image_status_counts['in_rework'])
        },
        'finished': {
            'count': image_status_counts['finished'],
            'height': calculate_image_height(image_status_counts['finished'])
        }
    }
    
    # Determine user status based on current job assignments
    if user_jobs.filter(status='in_progress').exists():
        user_status = "In Job"
        status_class = "bg-green-500"
    elif user_jobs.exists():
        user_status = "Ready"
        status_class = "bg-blue-500"
    else:
        user_status = "Not Ready"
        status_class = "bg-gray-500"

# === BUILD JOB LIST dengan progress percentage per job ===
    user_jobs_list = []
    for job in user_jobs.order_by('-date_created'):
        # Hitung progress per job (finished / total images)
        job_images_qs = JobImage.objects.filter(job=job)
        total_img = job_images_qs.count()
        finished_img = job_images_qs.filter(status='finished').count()
        progress = round((finished_img / total_img * 100)) if total_img > 0 else 0
 
        # Ambil URL first image (buat thumbnail di template)
        first_image = job_images_qs.first()
        first_image_url = None
        if first_image and first_image.image:
            try:
                first_image_url = first_image.image.url
            except Exception:
                first_image_url = None
 
        user_jobs_list.append({
            'id': job.id,
            'title': job.title,
            'description': job.description or '',
            'status': job.status,
            'image_count': total_img,
            'progress_percentage': progress,
            'first_image_url': first_image_url,
        })

    # Prepare context data
    context = {
        'user_profile': {
            'name': f"{user.first_name} {user.last_name}".strip() or user.username,
            'email': user.email,
            'role': user.role,
            'status': user_status,
            'status_class': status_class,
        },
        'user_stats': {
            'total_jobs': total_jobs,
            'total_images': total_images,
            'chart_data': job_chart_data,
            'image_chart_data': image_chart_data,
            'user_jobs_list': user_jobs_list,
        }
    }
    
    return render(request, "master/performance_individual.html", context)

@master_required
@require_http_methods(["POST"])
def update_user_roles(request):
    """
    AJAX endpoint to update user roles
    """
    try:
        # Parse JSON data from the request
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
                
            try:
                user = CustomUser.objects.get(id=user_id)
                old_role = user.role
                user.role = new_role
                user.save()
                
                success_count += 1
                print(f"Updated user {user.email} from {old_role} to {new_role}")
                
            except CustomUser.DoesNotExist:
                errors.append(f'User with ID {user_id} not found')
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
                'message': f'Successfully updated {success_count} user roles',
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
        job = JobProfile.objects.get(id=job_id)
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
        job = JobProfile.objects.get(id=job_id)
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
    
