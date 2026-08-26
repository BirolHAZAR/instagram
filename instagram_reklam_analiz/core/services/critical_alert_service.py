from core.models import Ad, AnomalyAlert


def generate_critical_alerts(user):
    own_count = Ad.objects.filter(user=user, source_type="OWN").count()
    comp_count = Ad.objects.filter(user=user, source_type="COMPETITOR").count()
    alerts = AnomalyAlert.objects.filter(
        user=user,
        is_dismissed=False,
        severity__in=["critical", "high"],
    )
    alert_summaries = [
        {
            "id": alert.id,
            "severity": alert.severity,
            "title": alert.title,
            "detected_at": alert.detected_at.isoformat() if alert.detected_at else None,
        }
        for alert in alerts[:20]
    ]
    return {"own_ads": own_count, "competitor_ads": comp_count, "alerts": alert_summaries}


class CriticalAlertService:
    @staticmethod
    def scan_user(user):
        return AnomalyAlert.objects.filter(
            user=user,
            is_dismissed=False,
            severity__in=["critical", "high"],
        ).count()
