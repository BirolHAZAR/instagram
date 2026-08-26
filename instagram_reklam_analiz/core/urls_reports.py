from django.urls import path
from core.views import reports

urlpatterns = [
    path('reports/', reports.report_list, name='report_list'),
    path('reports/generate/', reports.generate_report, name='generate_report'),
    path('reports/client-campaigns/', reports.report_client_campaigns, name='report_client_campaigns'),
    path('reports/client-ads/', reports.report_client_ads, name='report_client_ads'),
    path('reports/scheduled/<int:report_id>/edit/', reports.scheduled_report_edit, name='scheduled_report_edit'),
    path('reports/scheduled/<int:report_id>/delete/', reports.scheduled_report_delete, name='scheduled_report_delete'),
    path('reports/scheduled/<int:report_id>/toggle/', reports.scheduled_report_toggle, name='scheduled_report_toggle'),
    path('reports/scheduled/<int:report_id>/send-now/', reports.scheduled_report_send_now, name='scheduled_report_send_now'),
    path('reports/scheduled/<int:report_id>/preview/', reports.scheduled_report_preview, name='scheduled_report_preview'),
    path('reports/scheduled/<int:report_id>/preview/html/', reports.scheduled_report_preview_html, name='scheduled_report_preview_html'),
    path('reports/scheduled/<int:report_id>/preview/pdf/', reports.scheduled_report_pdf, name='scheduled_report_pdf'),
    path('reports/<int:report_id>/', reports.report_detail, name='report_detail'),
    path('reports/<int:report_id>/delete/', reports.report_delete, name='report_delete'),
    path('reports/reklam-karsilastirma/', reports.reklam_karsilastirma, name='reklam_karsilastirma'),
    path('reports/rakip-reklam-karsilastirma/', reports.rakip_reklam_karsilastirma, name='rakip_reklam_karsilastirma'),
    path('reports/reklam-tarihcesi/', reports.reklam_tarihcesi, name='reports_reklam_tarihcesi'),
    path('reklam-tarihcesi/', reports.reklam_tarihcesi, name='reklam_tarihcesi'),
    path('reports/daily-budget/', reports.daily_budget_report, name='daily_budget_report'),

    path('api/reklam-listesi/', reports.api_reklam_listesi, name='api_reklam_listesi_report'),
    path('api/reklam-detay/<int:reklam_id>/', reports.api_reklam_detay, name='api_reklam_detay'),
    path('api/rakip-reklam-listesi/', reports.api_rakip_reklam_listesi, name='api_rakip_reklam_listesi'),
    path('api/rakip-reklam-detay/<int:reklam_id>/', reports.api_rakip_reklam_detay, name='api_rakip_reklam_detay'),
]
