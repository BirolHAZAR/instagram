from django.urls import path

from core.views import campaign_panel as views

urlpatterns = [
    path("campaign-panel/", views.campaign_panel, name="campaign_panel"),
    path("api/campaign-panel/accounts/", views.api_campaign_panel_accounts, name="api_campaign_panel_accounts"),
    path("api/campaign-panel/campaigns/", views.api_campaigns_by_account, name="api_campaigns_by_account"),
    path("api/campaign-panel/campaign/<int:campaign_id>/", views.api_campaign_detail, name="api_campaign_detail"),
    path("api/campaign-panel/campaign/<int:campaign_id>/ai/", views.api_campaign_ai_report, name="api_campaign_ai_report"),
    path("api/campaign-panel/campaign/<int:campaign_id>/ai/pdf/", views.api_campaign_ai_pdf, name="api_campaign_ai_pdf"),
    path("api/campaign-panel/sync/<int:account_id>/", views.api_campaign_panel_sync_account, name="api_campaign_panel_sync_account"),
    path("api/campaign-panel/sync-job/<int:job_id>/", views.api_campaign_panel_sync_job_status, name="api_campaign_panel_sync_job_status"),
]
