from django.urls import path
from core.views import anomaly_detector

urlpatterns = [
    path('anomaly-detector/', anomaly_detector.anomaly_dashboard, name='anomaly_dashboard'),
    path('api/anomaly/scan/', anomaly_detector.trigger_scan, name='trigger_scan'),
    path('api/anomaly/trigger-scan/', anomaly_detector.trigger_scan, name='trigger_anomaly_scan'),
    path('anomaly/trigger-scan/', anomaly_detector.trigger_scan, name='trigger_scan_legacy'),
    path('api/anomaly/<int:alert_id>/dismiss/', anomaly_detector.dismiss_anomaly_alert, name='dismiss_alert'),
    path('anomaly/dismiss/<int:alert_id>/', anomaly_detector.dismiss_anomaly_alert, name='dismiss_anomaly_alert'),
    path('api/anomaly/mark-all-read/', anomaly_detector.mark_all_alerts_read, name='mark_all_read'),
    path('anomaly/mark-all-read/', anomaly_detector.mark_all_alerts_read, name='mark_all_alerts_read'),
    path('api/opportunity/<int:opp_id>/take/', anomaly_detector.take_opportunity_action, name='take_opportunity'),
    path('anomaly/take-action/<int:opp_id>/', anomaly_detector.take_opportunity_action, name='take_opportunity_action'),
    path('api/anomaly/count/', anomaly_detector.anomaly_count_api, name='anomaly_count'),
]
