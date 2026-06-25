from django.urls import path
from .views import *

urlpatterns = [
    #dashboard
    path('dashboard/', DashboardAPIView.as_view()),

    path('jobs/', MyJobsAPIView.as_view()),
    path('jobs/<int:job_id>/images/', JobImagesAPIView.as_view()),
    path('annotations/', AnnotationAPIView.as_view()),
    
    #notifikasi
    path('notifications/', NotificationListAPIView.as_view()), #notif
    path('notifications/<int:id>/read/', MarkNotificationAsReadAPIView.as_view()), #dibaca
    path('notifications/unread/', UnreadNotificationAPIView.as_view()), #belum dibaca
    
    #label
    path('image/<int:image_id>/getlabels/', LabeledDataDetailAPIView.as_view(), name='api_get_image_annotations'),
]