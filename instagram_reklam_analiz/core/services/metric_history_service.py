from django.utils import timezone

from core.models import CampaignMetricHistory, AdGroupMetricHistory, AdMetricHistory
from core.services.performance_metrics import normalize_metric_payload, safe_decimal, safe_int


def _to_decimal(value, default="0"):
    return safe_decimal(value, safe_decimal(default))


def _to_int(value, default=0):
    return safe_int(value, default)


def _metric_defaults(data):
    """
    Ortak metrik alanlarını tek yerden hazırlar.
    OWN reklamlar için performans verilerini,
    COMPETITOR reklamlar için platformların izin verdiği gözlem verilerini destekler.
    """
    return normalize_metric_payload(data)


def save_campaign_metrics(campaign, data):
    return CampaignMetricHistory.objects.update_or_create(
        campaign=campaign,
        date=(data or {}).get("date") or timezone.now().date(),
        defaults=_metric_defaults(data),
    )


def save_ad_group_metrics(ad_group, data):
    return AdGroupMetricHistory.objects.update_or_create(
        ad_group=ad_group,
        date=(data or {}).get("date") or timezone.now().date(),
        defaults=_metric_defaults(data),
    )


def save_ad_metrics(ad, data):
    defaults = _metric_defaults(data)

    if data is None:
        data = {}

    defaults.update({
        "estimated_engagement": _to_int(data.get("estimated_engagement")),
        "estimated_reach_min": (
            _to_int(data.get("estimated_reach_min"))
            if data.get("estimated_reach_min") not in [None, ""]
            else None
        ),
        "estimated_reach_max": (
            _to_int(data.get("estimated_reach_max"))
            if data.get("estimated_reach_max") not in [None, ""]
            else None
        ),
        "is_competitor_snapshot": bool(data.get("is_competitor_snapshot", False)),
    })

    return AdMetricHistory.objects.update_or_create(
        ad=ad,
        date=data.get("date") or timezone.now().date(),
        defaults=defaults,
    )


def save_metric_tree(entity_result, payload):
    campaign_metrics = None
    ad_group_metrics = None
    ad_metrics = None

    if entity_result.get("campaign"):
        campaign_metrics = save_campaign_metrics(
            entity_result["campaign"],
            payload.get("campaign_metrics", {}),
        )

    if entity_result.get("ad_group"):
        ad_group_metrics = save_ad_group_metrics(
            entity_result["ad_group"],
            payload.get("ad_group_metrics", {}),
        )

    if entity_result.get("ad"):
        ad_metrics = save_ad_metrics(
            entity_result["ad"],
            payload.get("ad_metrics", {}),
        )

    return {
        "campaign_metrics": campaign_metrics,
        "ad_group_metrics": ad_group_metrics,
        "ad_metrics": ad_metrics,
    }
