from core.models import Ad, AdMetricHistory
from core.services.organic_content_service import organic_summary_for_user


class ReportGenerator:
    def __init__(self, user):
        self.user = user

    def generate(self, *args, **kwargs):
        organic = organic_summary_for_user(self.user)
        return {
            "success": True,
            "message": "V2 rapor uretimi Ad + AdMetricHistory + organik icerik metrikleri ile calisir.",
            "own_ads": Ad.objects.filter(user=self.user, source_type="OWN").count(),
            "competitor_ads": Ad.objects.filter(user=self.user, source_type="COMPETITOR").count(),
            "ad_metric_rows": AdMetricHistory.objects.filter(ad__user=self.user).count(),
            "organic_posts": organic["total_posts"],
            "organic_reach": organic["reach"],
            "organic_engagement": organic["engagement"],
        }
