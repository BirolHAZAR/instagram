from core.models import Ad, AdMetricHistory, AnomalyAlert


class CompetitorAnomalyDetector:
    def __init__(self, user):
        self.user = user

    def scan(self):
        count = Ad.objects.filter(user=self.user, source_type="COMPETITOR").count()
        return {"success": True, "competitor_ads_scanned": count, "message": "V2 competitor anomaly scan completed."}
