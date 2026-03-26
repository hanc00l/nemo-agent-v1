from django.urls import path
from . import dashboard_views
from . import jupyter_views
from . import notes_views

urlpatterns = [
    # 页面路由
    path('', dashboard_views.dashboard_page, name='dashboard'),
    path('challenge/<str:challenge_code>/', dashboard_views.challenge_detail_page, name='challenge_detail'),

    # Jupyter Session 页面路由
    path('jupyter/', jupyter_views.jupyter_list_page, name='jupyter_list'),
    path('jupyter/<str:filename>/', jupyter_views.jupyter_detail_page, name='jupyter_detail'),

    # Notes 页面路由
    path('notes/', notes_views.notes_list_page, name='notes_list'),
    path('notes/<str:challenge_code>/', notes_views.notes_challenge_page, name='notes_challenge'),
    path('notes/<str:challenge_code>/<str:note_type>/', notes_views.notes_detail_page, name='notes_detail'),

    # API 路由 - 仪表板
    path('api/dashboard/stats/', dashboard_views.api_dashboard_stats, name='api_dashboard_stats'),
    path('api/challenges/', dashboard_views.api_challenges_list, name='api_challenges_list'),
    path('api/challenges/<str:challenge_code>/', dashboard_views.api_challenge_detail, name='api_challenge_detail'),
    path('api/challenges/<str:challenge_code>/logs/', dashboard_views.api_challenge_logs, name='api_challenge_logs'),
    path('api/challenges/<str:challenge_code>/notes/', dashboard_views.api_challenge_notes, name='api_challenge_notes'),

    # SSE 路由 - 实时更新
    path('api/sse/dashboard', dashboard_views.sse_dashboard_updates, name='sse_dashboard'),
    path('api/sse/challenge/<str:challenge_code>', dashboard_views.sse_challenge_updates, name='sse_challenge'),
    path('api/sse/logs/<str:challenge_code>', dashboard_views.sse_logs_stream, name='sse_logs'),
    path('api/sse/procs/<str:challenge_code>', dashboard_views.sse_challenge_procs, name='sse_challenge_procs'),

    # API 路由 - Agent 解题进度
    path('api/challenges/<str:challenge_code>/procs/', dashboard_views.api_challenge_procs, name='api_challenge_procs'),
    path('api/challenges/<str:challenge_code>/procs/since/<int:last_id>/', dashboard_views.api_challenge_procs_since, name='api_challenge_procs_since'),

    # API 路由 - Jupyter Sessions
    path('api/jupyter/', jupyter_views.api_jupyter_list, name='api_jupyter_list'),
    path('api/jupyter/<str:filename>/', jupyter_views.api_jupyter_detail, name='api_jupyter_detail'),

    # API 路由 - Notes
    path('api/notes/', notes_views.api_notes_list, name='api_notes_list'),
    path('api/notes/<str:challenge_code>/<str:note_type>/', notes_views.api_note_detail, name='api_note_detail'),
]
