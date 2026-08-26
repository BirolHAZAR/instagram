from django.db.models import Sum
from core.models import Ad, AdMetricHistory, PlatformAccount, BudgetOptimizationRule, BudgetOptimizationLog


def get_v2_summary(user):
    own = Ad.objects.filter(user=user, source_type="OWN")
    rival_ads = Ad.objects.filter(user=user, source_type="COMPETITOR")
    totals = AdMetricHistory.objects.filter(ad__user=user, ad__source_type="OWN").aggregate(spend=Sum("spend"), impressions=Sum("impressions"), clicks=Sum("clicks"))
    return {"ads": own.count(), "rivals": rival_ads.values("platform_account").distinct().count(), "rival_ads": rival_ads.count(), "spend": float(totals["spend"] or 0), "impressions": totals["impressions"] or 0, "clicks": totals["clicks"] or 0}
