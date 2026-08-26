from django.urls import path
from core.views.competitor_intelligence import (
    competitor_ad_ai_analysis_api,
    competitor_ad_detail_api,
    competitor_ads_api,
    competitor_intelligence,
)

urlpatterns = [
    path("competitor-intelligence/", competitor_intelligence, name="competitor_intelligence"),
    path("competitor-intelligence/api/competitor/<int:competitor_id>/ads/", competitor_ads_api, name="competitor_intelligence_ads_api"),
    path("competitor-intelligence/api/ad/<int:ad_id>/", competitor_ad_detail_api, name="competitor_intelligence_ad_detail_api"),
    path("competitor-intelligence/api/ad/<int:ad_id>/analysis/", competitor_ad_ai_analysis_api, name="competitor_intelligence_ad_analysis_api"),
    
]
