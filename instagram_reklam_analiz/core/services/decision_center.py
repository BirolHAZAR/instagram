from typing import Any, Dict

from core.models import Ad, AdMetricHistory
from core.services.performance_metrics import aggregate_metric_queryset


def calculate_ad_health_score(ad: Ad) -> Dict[str, Any]:
    totals = aggregate_metric_queryset(AdMetricHistory.objects.filter(ad=ad))
    ctr = float(totals.get("ctr") or 0)
    roas = float(totals.get("roas") or 0)
    score = min(100, int(ctr * 8 + roas * 15 + 30))
    return {
        "score": score,
        "ctr": ctr,
        "roas": roas,
        "reason": "V2 AdMetricHistory uzerinden merkezi metrik servisiyle hesaplandi.",
    }


def build_decision_center(user):
    own_ads = Ad.objects.filter(user=user, source_type="OWN")
    competitor_ads = Ad.objects.filter(user=user, source_type="COMPETITOR")
    return {"own_ads": own_ads.count(), "competitor_ads": competitor_ads.count(), "actions": []}
