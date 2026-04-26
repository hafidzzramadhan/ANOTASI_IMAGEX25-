from django.urls import path
from . import views

app_name = 'master'

urlpatterns = [
    path('', views.home_view, name='index'),  # Root URL
    path('signup/', views.signup_view, name='signup'),
    path("activate/<uidb64>/<token>/", views.activate, name="activate"),  
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('access-denied/', views.access_denied_view, name='access_denied'),
    path("home/", views.home_view, name="home"),
    path("assign_roles/", views.assign_roles_view, name="assign_roles"),
    path("job_settings/", views.job_settings_view, name="job_settings"),
    path("issue_solving/", views.issue_solving_view, name="issue_solving"),
    path("performance/", views.performance_view, name="performance"),
    path("performance/<int:user_id>/", views.performance_individual_view, name="performance_individual"),

    # Update Role
    path("update_role/", views.update_role, name="update_role"),
    path("update-user-roles/", views.update_user_roles, name="update_user_roles"),
    path("add_dataset/", views.add_dataset_view, name="add_dataset"),

    # Job Settings
    path('create_job_profile/', views.create_job_profile, name='create_job_profile'),
    path('job-profile/<int:job_id>/', views.job_profile_detail, name='job_profile_detail'),
    path('upload-job-images/', views.upload_job_images, name='upload_job_images'),

    # Home Dataset
    path('edit_dataset/<int:dataset_id>/', views.edit_dataset_view, name='edit_dataset'),
    path('delete_dataset/<int:dataset_id>/', views.delete_dataset_view, name='delete_dataset'),

    # Job Settings
    path('get-workers/<str:role>/', views.get_workers, name='get_workers'),
    path('assign-worker/', views.assign_worker, name='assign_worker'),
    path('assign-workers/', views.assign_workers, name='assign_workers'),
    
    # Issue Solving
    path('issue_solving/', views.issue_solving_view, name='issue_solving'),
    path('issue-detail/<int:job_id>/', views.issue_detail_view, name='issue_detail'),
    
    # Process Validation
    path("process_validations/", views.process_validations_view, name="process_validations"),
    path('process_validations/<int:job_id>/', views.process_validations_view, name='process_validation_detail'),
    path('finish-image/', views.finish_image, name='finish_image'),
    path('finish-job/', views.finish_job, name='finish_job'),
    
    #edit&job
    path('edit-job-profile/<int:job_id>/', views.edit_job_profile, name='edit_job_profile'),
    path('delete-job-profile/<int:job_id>/', views.delete_job_profile, name='delete_job_profile'),
]