"""
URL routing untuk API endpoints mobile app — VERSI FULL.

REPLACE total isi master/api_urls.py lu dengan file ini.
Yang ditambahin: semua endpoint Master (jobs, users, issues, notifications, dashboard).

Base URL: /api/
Mounted di Anotasi_Image/urls.py via: path('api/', include('master.api_urls'))
"""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

# === Auth & Profile (yang udah ada) ===
from master.api_views import (
    RegisterAPIView,
    LoginAPIView,
    LogoutAPIView,
    UserProfileAPIView,
    ChangePasswordAPIView,
    APIHealthCheckView,
)

# === Master endpoints (baru) ===
from master.api_master_views import (
    MasterDashboardAPIView,
    JobListCreateAPIView,
    JobDetailAPIView,
    JobAssignAPIView,
    JobImageListUploadAPIView,
    JobImageDetailAPIView,
    UserListAPIView,
    MasterIssueListAPIView,
    MasterNotificationListAPIView,
    MasterNotificationMarkReadAPIView,
)

# === Annotator + Reviewer dashboards ===
from master.api_role_dashboards import (
    AnnotatorDashboardAPIView,
    ReviewerDashboardAPIView,
)

app_name = 'api'

urlpatterns = [
    # ============================================================
    # HEALTH & AUTH (yang udah jalan)
    # ============================================================
    path('health/', APIHealthCheckView.as_view(), name='health'),

    path('auth/register/', RegisterAPIView.as_view(), name='register'),
    path('auth/login/', LoginAPIView.as_view(), name='login'),
    path('auth/logout/', LogoutAPIView.as_view(), name='logout'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    path('user/me/', UserProfileAPIView.as_view(), name='user_profile'),
    path('user/change-password/', ChangePasswordAPIView.as_view(), name='change_password'),

    # ============================================================
    # MASTER ENDPOINTS (BARU)
    # ============================================================

    # Dashboard
    path('master/dashboard/', MasterDashboardAPIView.as_view(), name='master_dashboard'),

    # Jobs CRUD
    path('master/jobs/', JobListCreateAPIView.as_view(), name='master_jobs'),
    path('master/jobs/<int:pk>/', JobDetailAPIView.as_view(), name='master_job_detail'),
    path('master/jobs/<int:pk>/assign/', JobAssignAPIView.as_view(), name='master_job_assign'),

    # Job Images
    path('master/jobs/<int:pk>/images/', JobImageListUploadAPIView.as_view(), name='master_job_images'),
    path('master/images/<int:pk>/', JobImageDetailAPIView.as_view(), name='master_image_detail'),

    # Users
    path('master/users/', UserListAPIView.as_view(), name='master_users'),

    # Issues
    path('master/issues/', MasterIssueListAPIView.as_view(), name='master_issues'),

    # Notifications
    path('master/notifications/', MasterNotificationListAPIView.as_view(), name='master_notifications'),
    path('master/notifications/read-all/', MasterNotificationMarkReadAPIView.as_view(), name='master_notif_read_all'),
    path('master/notifications/<int:pk>/read/', MasterNotificationMarkReadAPIView.as_view(), name='master_notif_read'),

    # ============================================================
    # ANNOTATOR + REVIEWER DASHBOARDS (BARU)
    # ============================================================
    path('annotator/dashboard/', AnnotatorDashboardAPIView.as_view(), name='annotator_dashboard'),
    path('reviewer/dashboard/',  ReviewerDashboardAPIView.as_view(),  name='reviewer_dashboard'),
]