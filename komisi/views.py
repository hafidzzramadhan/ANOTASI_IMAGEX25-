from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse
from django.db.models import Prefetch
from master.forms import SignUpForm
from master.models import Dataset, DatasetComment, JobImage
from functools import wraps
import zipfile


def _komisi_access_denied_response(request):
    messages.error(request, 'Akses ditolak. Halaman ini khusus untuk Komisi yang sudah disetujui.')
    return redirect('master:index')


def komisi_required(view_func):
    """Decorator: user harus login, role komisi, dan sudah approved."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Silakan login sebagai Komisi terlebih dahulu.')
            return redirect('komisi:login')
        if request.user.role != 'komisi':
            return _komisi_access_denied_response(request)
        if getattr(request.user, 'komisi_approval_status', None) != 'approved':
            messages.error(request, 'Akun komisi Anda belum disetujui admin.')
            return redirect('master:login')
        return view_func(request, *args, **kwargs)
    return _wrapped


def login_komisi_view(request):
    error_message = None
    if request.method == 'POST':
        username_or_email = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, email=username_or_email, password=password)
        if user is None:
            user = authenticate(request, username=username_or_email, password=password)

        if user is None:
            error_message = 'Email/Username atau password salah.'
            messages.error(request, error_message)
        elif user.role != 'komisi':
            error_message = 'Akun ini bukan akun Komisi. Silakan masuk sebagai User.'
            messages.error(request, error_message)
        elif not user.is_active:
            error_message = 'Akun belum diaktifkan.'
            messages.error(request, error_message)
        elif user.komisi_approval_status == 'pending':
            error_message = 'Akun kamu masih menunggu persetujuan admin.'
            messages.error(request, error_message)
        elif user.komisi_approval_status == 'rejected':
            error_message = 'Pendaftaran akun Komisi kamu ditolak admin.'
            messages.error(request, error_message)
        elif user.komisi_approval_status == 'approved':
            login(request, user)
            messages.success(request, 'Login Komisi berhasil!')
            return redirect('komisi:dashboard')
        else:
            error_message = 'Status akun Komisi belum valid. Hubungi admin.'
            messages.error(request, error_message)

    return render(request, 'komisi/login_komisi.html', {'error_message': error_message})


def signup_komisi_view(request):
    if request.method == 'POST':
        if request.user.is_authenticated:
            messages.error(request, 'Silakan logout terlebih dahulu sebelum mendaftar akun Komisi baru.')
            return redirect('komisi:signup')

        data = {
            'username': request.POST.get('username'),
            'first_name': request.POST.get('first_name'),
            'last_name': request.POST.get('last_name'),
            'email': request.POST.get('email'),
            'phone_number': request.POST.get('phone_number'),
            'password1': request.POST.get('password1'),
            'password2': request.POST.get('password2'),
        }
        form = SignUpForm(data)

        if form.is_valid():
            user = form.save(commit=False)
            user.role = 'komisi'
            user.komisi_approval_status = 'pending'
            user.is_active = True
            user.save()
            messages.success(request, 'Pendaftaran akun Komisi berhasil dikirim. Silakan tunggu persetujuan admin.')
            return redirect('komisi:login')

        for field in form.errors:
            for error in form.errors[field]:
                messages.error(request, f'{field}: {error}')
    else:
        form = SignUpForm()

    return render(request, 'komisi/signup_komisi.html', {'form': form})


@login_required
@komisi_required
def lobby_komisi_view(request):
    pending_datasets = Dataset.objects.filter(status_publikasi='pending').order_by('-date_created')
    published_datasets = Dataset.objects.filter(status_publikasi='published').select_related('labeler').prefetch_related(
        Prefetch('comments', queryset=DatasetComment.objects.select_related('user').order_by('-created_at'))
    ).order_by('-date_created')
    review_history = Dataset.objects.filter(reviewed_by__isnull=False).select_related('reviewed_by', 'taken_down_by').order_by('-reviewed_at')
    return render(request, 'komisi/lobby_komisi.html', {
        'pending_datasets': pending_datasets,
        'published_datasets': published_datasets,
        'review_history': review_history,
    })


@login_required
@komisi_required
def takedown_dataset_view(request, dataset_id):
    dataset = get_object_or_404(Dataset, id=dataset_id, status_publikasi='published')
    if request.method == 'POST':
        reason = request.POST.get('reason', '').strip()
        if not reason:
            messages.error(request, 'Alasan take-down wajib diisi.')
            return redirect('komisi:dashboard')
        dataset.status_publikasi = 'taken_down'
        dataset.taken_down_by = request.user
        dataset.taken_down_at = timezone.now()
        dataset.takedown_reason = reason
        dataset.save()
        messages.success(request, f"Dataset '{dataset.name}' berhasil ditarik dari publik.")
    return redirect('komisi:dashboard')


@login_required
@komisi_required
def review_komisi_view(request, dataset_id):
    dataset = get_object_or_404(Dataset, id=dataset_id, status_publikasi='pending')

    images = []
    if dataset.project_id:
        images = JobImage.objects.filter(job__project=dataset.project)[:15]

    if request.method == 'POST':
        action = request.POST.get('action')
        dataset.rating = request.POST.get('rating')
        dataset.komisi_feedback = request.POST.get('feedback')
        dataset.reviewed_by = request.user
        dataset.reviewed_at = timezone.now()

        if action == 'approve':
            dataset.status_publikasi = 'published'
            messages.success(request, f"Dataset '{dataset.name}' dipublikasikan!")
        elif action == 'reject':
            dataset.status_publikasi = 'rejected'
            messages.error(request, f"Dataset '{dataset.name}' ditolak.")

        dataset.save()
        return redirect('komisi:dashboard')

    return render(request, 'komisi/review_komisi.html', {
        'dataset': dataset,
        'images': images,
    })


@login_required
@komisi_required
def get_dataset_content(request, dataset_id):
    dataset = get_object_or_404(Dataset, id=dataset_id)
    zip_path = dataset.file_path.path

    file_list = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            file_list = zip_ref.namelist()[:10]
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'files': file_list})
