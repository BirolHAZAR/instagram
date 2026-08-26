from datetime import date

from core.models import Ad
from core.services.performance_metrics import aggregate_metric_queryset, user_performance_queryset


class DashboardService:
    
    def __init__(self, user):
        self.user = user
        self.my_ads = Ad.objects.filter(user=user, source_type="OWN")
        self.competitor_ads = Ad.objects.filter(user=user, source_type="COMPETITOR")

    def get_summary(self):
        qs, _source = user_performance_queryset(self.user, date(1900, 1, 1), date(2999, 12, 31))
        totals = aggregate_metric_queryset(qs)
        return {
            "ads": self.my_ads.count(),
            "rivals": self.competitor_ads.values("platform_account").distinct().count(),
            "competitor_ads": self.competitor_ads.count(),
            "spend": float(totals.get("spend") or 0),
            "roas": float(totals.get("roas") or 0),
            "ctr": float(totals.get("ctr") or 0),
        }

    def get_dashboard_data(self):
        summary = self.get_summary()
        return {"summary": summary, "cards": [], "events": [], "recommendations": []}
