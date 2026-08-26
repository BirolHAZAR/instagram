from django.urls import path
from core.views import notifications

urlpatterns = [
    path('bildirimler/', notifications.notification_center, name='notification_center'),
    path('aktiviteler/', notifications.activity_log, name='activity_log'),
    path('bildirimler/tercihler/', notifications.update_notification_preferences, name='update_notification_preferences'),
    path('bildirimler/toplu-okundu/', notifications.mark_all_notifications_read, name='mark_all_notifications_read'),
    path('bildirimler/toplu-islem/', notifications.bulk_notifications_action, name='bulk_notifications_action'),
    path('bildirimler/<int:notification_id>/ac/', notifications.open_notification, name='open_notification'),
    path('bildirimler/<int:notification_id>/okundu/', notifications.mark_notification_read, name='mark_notification_read'),
    path('bildirimler/<int:notification_id>/sil/', notifications.delete_notification, name='delete_notification'),
    path('api/notifications/<int:notification_id>/read/', notifications.mark_notification_read, name='api_mark_notification_read'),
    path('api/notifications/mark-all-read/', notifications.mark_all_notifications_read, name='api_mark_all_notifications_read'),
    path('api/notifications/<int:notification_id>/delete/', notifications.delete_notification, name='api_delete_notification'),
    path('api/alerts/dismiss/', notifications.api_alert_dismiss, name='api_alert_dismiss'),
    path('api/notifications/latest/', notifications.latest_notifications_api, name='api_latest_notifications'),
]
