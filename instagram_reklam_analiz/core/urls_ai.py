from django.urls import path
from core.views import ai

urlpatterns = [
    path('ai/', ai.ai_dashboard, name='ai_dashboard'),
    path('ai/dashboard/', ai.ai_dashboard, name='ai_dashboard_alt'),
    path('ai/analyze/<int:campaign_id>/', ai.ai_analyze_campaign, name='ai_analyze_campaign'),
    path('ai/analyze-account/<int:account_id>/', ai.ai_analyze_account, name='ai_analyze_account'),
    path('api/ai/suggestions/', ai.ai_suggestions_api, name='ai_suggestions_api'),
    path('api/ai/analyze-ad/<int:ad_id>/', ai.start_ad_ai_analysis, name='start_ad_ai_analysis'),
    path('api/ai/analysis-status/<int:analysis_id>/', ai.get_ad_analysis_status, name='get_ad_analysis_status'),
    path('api/ai/save-analysis/', ai.save_ai_analysis, name='save_ai_analysis'),
    path('api/save-ai-analysis/', ai.save_ai_analysis, name='save_ai_analysis_legacy'),
    path('api/ai/send-email/', ai.send_analysis_email, name='send_analysis_email'),
    path('api/ai/task-status/<str:task_id>/', ai.get_ai_task_status, name='ai_task_status'),
]
