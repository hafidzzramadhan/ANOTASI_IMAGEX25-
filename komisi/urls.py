from django.urls import path
from . import views
from . import api_views
from rest_framework_simplejwt.views import TokenRefreshView

app_name = 'komisi'

urlpatterns = [
    path('', views.lobby_komisi_view, name='dashboard'),
    path('login/', views.login_komisi_view, name='login'),
    path('signup/', views.signup_komisi_view, name='signup'),
    path('lobby/', views.lobby_komisi_view, name='lobby'),
    path('review/<int:dataset_id>/', views.review_komisi_view, name='review_komisi'),
    path('takedown/<int:dataset_id>/', views.takedown_dataset_view, name='takedown_dataset'),
    
    #get data
    path('get-dataset-content/<int:dataset_id>/', views.get_dataset_content, name='get_dataset_content'),

    # Mobile API
    path('api/auth/login/', api_views.api_login, name='api_login'),
    path('api/auth/logout/', api_views.api_logout, name='api_logout'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='api_token_refresh'),
    path('api/datasets/', api_views.api_dataset_list, name='api_dataset_list'),
    path('api/datasets/<int:dataset_id>/', api_views.api_dataset_detail, name='api_dataset_detail'),
    path('api/datasets/<int:dataset_id>/review/', api_views.api_dataset_review, name='api_dataset_review'),
    path('api/datasets/<int:dataset_id>/takedown/', api_views.api_dataset_takedown, name='api_dataset_takedown'),
    path('api/datasets/<int:dataset_id>/content/', api_views.api_dataset_content, name='api_dataset_content'),
]
