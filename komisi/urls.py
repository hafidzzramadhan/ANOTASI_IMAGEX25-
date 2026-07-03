from django.urls import path
from . import views

app_name = 'komisi'

urlpatterns = [
    path('lobby/', views.lobby_komisi_view, name='lobby'),
    path('review/<int:dataset_id>/', views.review_komisi_view, name='review_komisi'),
    
    #get data
    path('get-dataset-content/<int:dataset_id>/', views.get_dataset_content, name='get_dataset_content'),
]