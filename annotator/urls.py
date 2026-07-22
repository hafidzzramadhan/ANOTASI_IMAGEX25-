from django.urls import path
from . import views
from . import api_views
from rest_framework_simplejwt.views import TokenRefreshView

app_name = 'annotator'

urlpatterns = [
    # Main pages
    path('', views.annotate_view, name='home'),
    path('profile/', views.profile_view, name='profile'),
    path('annotate/', views.annotate_view, name='annotate'),
    path('job/<int:job_id>/', views.job_detail_view, name='job_detail'),
    path('issue/<int:issue_id>/dispute/', views.dispute_issue_view, name='dispute_issue'),

    # Notifications
    path('notifications/', views.notifications_view, name='notifications'),
    path('notification/<int:notification_id>/accept/', views.accept_notification_view, name='accept_notification'),

    # Authentication (if needed for annotator-specific auth)
    path('signup/', views.signup_view, name= 'signup'),
    path('signin/', views.signin_view, name='signin'),
    path('signout/', views.signout_view, name='signout'),

    # labeling
    path('label/<int:job_id>/<int:image_id>/', views.label_image_view, name='label_image'),

    # mengirim gambar ke web lain
    path('send-image/<int:image_id>/', views.send_image_view, name='send_image'),

    # menerima filejson
    path('result-json/<int:image_id>/', views.get_result_json, name='get_result_json'),

    # annotator/urls.py
    path('save-annotation/<int:image_id>/', views.save_annotation, name='save_annotation'),   # finish annotation
    path('finish-annotation/<int:image_id>/', views.finish_annotation_view, name='finish_annotation'),

    path('delete-annotation/<int:image_id>/', views.delete_annotation, name='delete_annotation'),

    # Mobile API
    path('api/auth/login/', api_views.api_login, name='api_login'),
    path('api/auth/logout/', api_views.api_logout, name='api_logout'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='api_token_refresh'),
    path('api/jobs/', api_views.api_job_list, name='api_job_list'),
    path('api/jobs/<int:job_id>/', api_views.api_job_detail, name='api_job_detail'),
    path('api/jobs/<int:job_id>/images/', api_views.api_image_list, name='api_image_list'),
    path('api/images/<int:image_id>/', api_views.api_image_detail, name='api_image_detail'),
    path('api/images/<int:image_id>/annotations/', api_views.api_annotation_save, name='api_annotation_save'),
    path('api/images/<int:image_id>/annotations/<int:annotation_id>/', api_views.api_annotation_delete, name='api_annotation_delete'),
    path('api/images/<int:image_id>/finish/', api_views.api_image_finish, name='api_image_finish'),
    path('api/issues/', api_views.api_issue_list, name='api_issue_list'),
    path('api/issues/<int:issue_id>/dispute/', api_views.api_issue_dispute, name='api_issue_dispute'),
    path('api/notifications/', api_views.api_notification_list, name='api_notification_list'),
    path('api/notifications/<int:notification_id>/accept/', api_views.api_notification_accept, name='api_notification_accept'),
    path('api/labels/', api_views.MasterLabelAPIView.as_view(), name='api_labels'),
]
