from django.urls import path

from core.views.campaign_center import (
    campaign_center,
    octo_campaign_analysis_safe,
    octo_campaign_analysis_pdf,
    mark_campaign_octo_recommendation_applied,
)

urlpatterns = [
    path("campaign-center/", campaign_center, name="campaign_center"),

    path(
        "campaign-center/octo-analysis/<int:campaign_id>/",
        octo_campaign_analysis_safe,
        name="octo_campaign_analysis",
    ),

    path(
        "campaign-center/octo-analysis-safe/<int:campaign_id>/",
        octo_campaign_analysis_safe,
        name="octo_campaign_analysis_safe",
    ),

    path(
        "campaign-center/octo-analysis-pdf/<int:analysis_id>/",
        octo_campaign_analysis_pdf,
        name="octo_campaign_analysis_pdf",
    ),

    path(
        "campaign-center/octo-recommendation/<int:recommendation_id>/mark-applied/",
        mark_campaign_octo_recommendation_applied,
        name="mark_campaign_octo_recommendation_applied",
    ),
]
