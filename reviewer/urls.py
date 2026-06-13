# reviewer/urls.py
from django.urls import path
from . import views
from . import api_views

from rest_framework_simplejwt.views import TokenRefreshView

app_name = 'reviewer'

template_patterns = [
    path('',                          views.home_reviewer,       name='home_reviewer'),
    path('task_review/<int:id>/',     views.task_review,         name='task_review'),
    path('isu/',                      views.isu,                 name='isu'),
    path('login/',                    views.login,               name='login'),
    path('signin/',                   views.login,               name='signin'),
    path('logout/',                   views.logout,              name='logout'),
    path('isu_image/',                views.isu_image,           name='isu_image'),
    path('isu_anotasi/<int:index>/',  views.isu_anotasi,         name='isu_anotasi'),
    path('finish_review/<int:image_id>/', views.finish_review_view, name='finish_review'),
    path('accept_task/<int:profile_id>/', views.accept_task,    name='accept_task'),
    path('done_task/<int:profile_id>/',   views.done_task,      name='done_task'),
    path('drop_task/<int:profile_id>/',   views.drop_task,      name='drop_task'),
    path('make_issue/<int:image_id>/',    views.make_issue_view, name='make_issue'),
]

auth_patterns = [
    path('api/auth/login/',   api_views.api_login,   name='api_login'),
    path('api/auth/logout/',  api_views.api_logout,  name='api_logout'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='api_token_refresh'),
]

dashboard_patterns = [
    path('api/dashboard/stats/', api_views.api_dashboard_stats, name='api_dashboard_stats'),
]

job_patterns = [
    path('api/jobs/',                          api_views.api_job_list,   name='api_job_list'),
    path('api/jobs/<int:job_id>/',             api_views.api_job_detail, name='api_job_detail'),
    path('api/jobs/<int:job_id>/accept/',      api_views.api_job_accept, name='api_job_accept'),
    path('api/jobs/<int:job_id>/drop/',        api_views.api_job_drop,   name='api_job_drop'),
    path('api/jobs/<int:job_id>/done/',        api_views.api_job_done,   name='api_job_done'),
    path('api/jobs/<int:job_id>/images/',      api_views.api_image_list, name='api_image_list'),
]

image_patterns = [
    path('api/images/<int:image_id>/',         api_views.api_image_detail, name='api_image_detail'),
    path('api/images/<int:image_id>/finish/',  api_views.api_image_finish, name='api_image_finish'),
]

issue_patterns = [
    path('api/issues/',                        api_views.api_issue_list,    name='api_issue_list'),
    path('api/issues/summary/',                api_views.api_issue_summary, name='api_issue_summary'),
    path('api/issues/<int:issue_id>/',         api_views.api_issue_detail,  name='api_issue_detail'),
    path('api/issues/<int:issue_id>/update/',  api_views.api_issue_update,  name='api_issue_update'),

]

urlpatterns = (
    template_patterns
    + auth_patterns
    + dashboard_patterns
    + job_patterns
    + image_patterns
    + issue_patterns
)
