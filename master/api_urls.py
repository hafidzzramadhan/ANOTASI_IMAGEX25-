"""
URL routing untuk API endpoints mobile app.

Base URL: /api/
Semua endpoint di-mount di Anotasi_Image/urls.py via: path('api/', include('master.api_urls'))
"""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from master.api_views import (
    RegisterAPIView,
    LoginAPIView,
    LogoutAPIView,
    UserProfileAPIView,
    ChangePasswordAPIView,
    APIHealthCheckView,
)

app_name = 'api'

urlpatterns = [
    # Health check
    path('health/', APIHealthCheckView.as_view(), name='health'),

    # Authentication
    path('auth/register/', RegisterAPIView.as_view(), name='register'),
    path('auth/login/', LoginAPIView.as_view(), name='login'),
    path('auth/logout/', LogoutAPIView.as_view(), name='logout'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # User profile
    path('user/me/', UserProfileAPIView.as_view(), name='user_profile'),
    path('user/change-password/', ChangePasswordAPIView.as_view(), name='change_password'),
]