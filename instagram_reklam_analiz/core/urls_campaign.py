from django.urls import path
from core.views.campaign_center import campaign_center, octo_campaign_analysis_safe

urlpatterns = [
    path("campaign-center/", campaign_center, name="campaign_center"),
    path("campaign-center/octo-analysis/<int:campaign_id>/", octo_campaign_analysis_safe, name="octo_campaign_analysis"),
]
