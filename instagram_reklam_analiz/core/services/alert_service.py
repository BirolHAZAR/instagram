from django.db.models import Count, Q

from core.models import AnomalyAlert
from core.models.notification import Notification


class AlertService:
    def __init__(self, user):
        self.user = user

    @staticmethod
    def get_alerts(user, limit=None):
        notifications = Notification.objects.filter(user=user, is_read=False).order_by("-created_at")
        if limit:
            notifications = notifications[:limit]
        alerts = []
        for n in notifications:
            alerts.append({
                "id": f"notification_{n.id}",
                "db_id": n.id,
                "type": "notification",
                "title": n.title,
                "message": n.message,
                "level": n.level,
                "icon": n.icon or "🔔",
                "link": n.link or "#",
                "time": n.created_at,
            })
        return alerts

    @staticmethod
    def get_unread_count(user):
        base = Notification.objects.filter(user=user, is_read=False)
        return {
            "total": base.count(),
            "critical": base.filter(level="critical").count(),
            "warning": base.filter(level="warning").count(),
            "info": base.filter(level="info").count(),
        }

    @staticmethod
    def refresh_all_alerts(user):
        notification_qs = Notification.objects.filter(user=user, is_read=False)
        anomaly_qs = AnomalyAlert.objects.filter(user=user, is_dismissed=False)
        return {
            "notifications": notification_qs.count(),
            "anomalies": anomaly_qs.count(),
            "critical": anomaly_qs.filter(severity__in=["critical", "high"]).count(),
        }

    def get_alerts_for_user(self):
        return self.get_alerts(self.user)

    def get_anomaly_alerts(self):
        return AnomalyAlert.objects.filter(user=self.user, is_dismissed=False).order_by('-detected_at')

    def competitor_suggestion(self):
        try:
            from core.models import Ad
            exists = Ad.objects.filter(user=self.user, source_type="COMPETITOR").exists()
        except Exception:
            exists = True
        if exists:
            return None
        return {"title": "Rakip reklam ekleyin", "message": "Rakip reklamları artık Ad(source_type=COMPETITOR) tablosunda izlenir."}
