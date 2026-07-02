from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from master.models import Dataset 
import zipfile  
from django.http import JsonResponse  
from master.models import Dataset, JobImage  # <--- Pastikan JobImage sudah ada di sini

@login_required
def lobby_komisi_view(request):
    if request.user.role != 'komisi':
        return redirect('master:lobby')
    
    # Hanya tarik dataset yang berstatus 'pending'
    pending_datasets = Dataset.objects.filter(status_publikasi='pending').order_by('-date_created')
    return render(request, 'komisi/lobby_komisi.html', {'pending_datasets': pending_datasets})

@login_required
def review_komisi_view(request, dataset_id):
    dataset = get_object_or_404(Dataset, id=dataset_id)
    
    # Sinkronisasi Gambar: Tarik semua gambar dari Job yang ada di Project dataset tersebut
    # Kita pakai filter project agar akurat
    images = JobImage.objects.filter(job__project=dataset.project)[:15]

    if request.method == 'POST':
        action = request.POST.get('action')
        dataset.rating = request.POST.get('rating')
        dataset.komisi_feedback = request.POST.get('feedback')

        if action == 'approve':
            dataset.status_publikasi = 'published'
            messages.success(request, f"Dataset '{dataset.name}' dipublikasikan!")
        elif action == 'reject':
            dataset.status_publikasi = 'rejected'
            messages.error(request, f"Dataset '{dataset.name}' ditolak.")

        dataset.save()
        return redirect('komisi:lobby')

    return render(request, 'komisi/review_komisi.html', {
        'dataset': dataset,
        'images': images
    })
@login_required
def get_dataset_content(request, dataset_id):
    # Mengambil dataset berdasarkan ID
    dataset = get_object_or_404(Dataset, id=dataset_id)

    # Mengambil path file dari database
    zip_path = dataset.file_path.path

    file_list = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Mengambil daftar nama file di dalam ZIP (maksimal 10 file pertama)
            file_list = zip_ref.namelist()[:10] 
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'files': file_list})