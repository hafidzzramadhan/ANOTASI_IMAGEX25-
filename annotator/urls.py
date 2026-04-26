from django.urls import path
from . import views

app_name = 'annotator'

urlpatterns = [
    # Main pages
    path('', views.annotate_view, name='home'),
    path('annotate/', views.annotate_view, name='annotate'),
    path('job/<int:job_id>/', views.job_detail_view, name='job_detail'),
    
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
]


