from django.urls import path
from core.views import api

urlpatterns = [
    path('api/analyze/', api.api_analyze_instagram, name='api_analyze_instagram'),
    path('api/competitor-analysis/', api.api_competitor_analysis, name='api_competitor_analysis'),
    path('api/analyze-media/', api.api_analyze_media, name='api_analyze_media'),
    path('api/ads/<int:ad_id>/metrics/', api.ad_metrics_detail_api, name='ad_metrics_detail_api'),
    path('api/ads/<int:ad_id>/demographics/', api.ad_demographics_api, name='ad_demographics_api'),
    path('api/payment/webhook/', api.payment_webhook, name='payment_webhook'),
    path('api/reklam-tarihce-raporu/', api.api_reklam_tarihce_raporu, name='api_reklam_tarihce_raporu'),
]
