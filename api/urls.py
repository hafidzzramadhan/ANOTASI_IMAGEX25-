from django.urls import path, include

urlpatterns = [
    path('master/', include('api.master.urls')),
    path('annotator/', include('api.annotator.urls')),
]