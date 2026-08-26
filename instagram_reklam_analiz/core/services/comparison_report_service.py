from django.db.models import Sum
from core.models import Ad, AdMetricHistory


class ComparisonReportService:
    def __init__(self, user):
        self.user = user

    def own_vs_competitor(self):
        own = Ad.objects.filter(user=self.user, source_type="OWN").count()
        competitor = Ad.objects.filter(user=self.user, source_type="COMPETITOR").count()
        return {"own_ads": own, "competitor_ads": competitor}

    def ad_history(self, ad_id):
        return AdMetricHistory.objects.filter(ad_id=ad_id, ad__user=self.user).order_by("date")
