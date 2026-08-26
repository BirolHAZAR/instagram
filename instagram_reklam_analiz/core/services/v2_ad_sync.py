from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from django.db import transaction
from django.utils import timezone

from core.models import (
    Campaign,
    AdGroup,
    Creative,
    Ad,
    AdMetricHistory,
    CampaignMetricHistory,
    AdGroupMetricHistory,
    CreativeMetricHistory,
)
from core.services.performance_metrics import normalize_metric_payload


def get_metric_date(payload: Dict[str, Any]) -> date:
    raw = payload.get("date") or payload.get("snapshot_date") or payload.get("date_start")
    if isinstance(raw, date):
        return raw
    if raw:
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            pass
    return timezone.now().date()


def normalize_status(value: Any) -> str:
    value = str(value or "ACTIVE").upper()
    mapping = {
        "ACTIVE": "ACTIVE",
        "ENABLED": "ACTIVE",
        "ACTIVITY": "ACTIVE",
        "ACTIVITE": "ACTIVE",
        "PAUSED": "PAUSED",
        "DISABLED": "PAUSED",
        "DELETED": "DELETED",
        "ARCHIVED": "ARCHIVED",
        "ENDED": "ENDED",
    }
    return mapping.get(value, "UNKNOWN")


def metric_defaults(payload: Dict[str, Any]) -> Dict[str, Any]:
    return normalize_metric_payload(payload)


def _present_budget_defaults(payload, mapping):
    """Do not erase a previously synced budget when an insights row omits it."""
    defaults = {}
    for model_field, payload_fields in mapping.items():
        for payload_field in payload_fields:
            value = payload.get(payload_field)
            if value not in (None, ""):
                defaults[model_field] = value
                break
    return defaults


@transaction.atomic
def upsert_v2_ad_snapshot(*, user, platform_account, payload: Dict[str, Any], source_type: str = "OWN") -> Dict[str, Any]:
    """Platform API'den gelen tek reklam snapshot'ını yeni V2 mimariye yazar.

    Zorunlu mantık:
    PlatformAccount -> Campaign -> AdGroup -> Creative -> Ad -> AdMetricHistory
    Rakip reklamlar için source_type='COMPETITOR' kullanılır.
    """
    now = timezone.now()
    platform_code = getattr(getattr(platform_account, "platform", None), "code", "platform") or "platform"
    ad_platform_id = str(payload.get("platform_ad_id") or payload.get("ad_id") or payload.get("id") or "").strip()
    if not ad_platform_id:
        raise ValueError("platform_ad_id/ad_id/id zorunlu")

    campaign_id = str(payload.get("platform_campaign_id") or payload.get("campaign_id") or f"{platform_code}-default-campaign")
    campaign_name = payload.get("campaign_name") or "Varsayılan Kampanya"
    campaign_budget_defaults = _present_budget_defaults(payload, {
        "daily_budget": ("campaign_daily_budget", "daily_budget"),
        "lifetime_budget": ("campaign_lifetime_budget", "lifetime_budget"),
    })
    campaign, _ = Campaign.objects.update_or_create(
        user=user,
        platform_account=platform_account,
        platform_campaign_id=campaign_id,
        defaults={
            "platform_connection": getattr(platform_account, "connection", None),
            "name": campaign_name,
            "objective": payload.get("objective") or "UNKNOWN",
            "status": normalize_status(payload.get("campaign_status") or payload.get("status")),
            **campaign_budget_defaults,
            "currency": payload.get("currency") or "TRY",
            "raw_data": payload.get("campaign_raw") or {},
            "last_synced_at": now,
            "is_active": normalize_status(payload.get("campaign_status") or payload.get("status")) == "ACTIVE",
        },
    )

    adgroup_id = str(payload.get("platform_adgroup_id") or payload.get("adgroup_id") or payload.get("adset_id") or f"{campaign_id}-default-adgroup")
    adgroup_name = payload.get("adgroup_name") or payload.get("adset_name") or "Varsayılan Reklam Grubu"
    adgroup_budget_defaults = _present_budget_defaults(payload, {
        "daily_budget": ("adgroup_daily_budget", "adset_daily_budget"),
        "lifetime_budget": ("adgroup_lifetime_budget", "adset_lifetime_budget"),
    })
    ad_group, _ = AdGroup.objects.update_or_create(
        user=user,
        campaign=campaign,
        platform_adgroup_id=adgroup_id,
        defaults={
            "name": adgroup_name,
            "status": normalize_status(payload.get("adgroup_status") or payload.get("adset_status") or payload.get("status")),
            "optimization_goal": payload.get("optimization_goal"),
            "billing_event": payload.get("billing_event"),
            **adgroup_budget_defaults,
            "targeting": payload.get("targeting") or {},
            "placements": payload.get("placements") or {},
            "raw_data": payload.get("adgroup_raw") or payload.get("adset_raw") or {},
            "last_synced_at": now,
            "is_active": normalize_status(payload.get("adgroup_status") or payload.get("adset_status") or payload.get("status")) == "ACTIVE",
        },
    )

    creative_id = str(payload.get("platform_creative_id") or payload.get("creative_id") or f"creative-{ad_platform_id}")
    creative, _ = Creative.objects.update_or_create(
        user=user,
        platform_account=platform_account,
        platform_creative_id=creative_id,
        defaults={
            "platform_connection": getattr(platform_account, "connection", None),
            "creative_type": str(payload.get("creative_type") or payload.get("media_type") or "UNKNOWN").upper(),
            "name": payload.get("creative_name") or payload.get("name") or payload.get("ad_name"),
            "title": payload.get("title") or payload.get("headline"),
            "body_text": payload.get("primary_text") or payload.get("body_text") or payload.get("description"),
            "description": payload.get("description"),
            "call_to_action": payload.get("call_to_action") or payload.get("cta"),
            "image_url": payload.get("image_url") or payload.get("media_url") or payload.get("thumbnail_url"),
            "video_url": payload.get("video_url"),
            "thumbnail_url": payload.get("thumbnail_url"),
            "landing_url": payload.get("landing_url") or payload.get("url"),
            "raw_data": payload.get("creative_raw") or {},
            "last_seen_at": now,
        },
    )

    ad, _ = Ad.objects.update_or_create(
        user=user,
        source_type=source_type,
        platform_account=platform_account,
        platform_ad_id=ad_platform_id,
        defaults={
            "platform_connection": getattr(platform_account, "connection", None),
            "campaign": campaign,
            "ad_group": ad_group,
            "creative": creative,
            "name": payload.get("name") or payload.get("ad_name") or payload.get("title") or f"Reklam {ad_platform_id}",
            "status": normalize_status(payload.get("status")),
            "ad_format": payload.get("ad_format") or payload.get("media_type"),
            "objective": payload.get("objective"),
            "headline": payload.get("headline") or payload.get("title"),
            "primary_text": payload.get("primary_text") or payload.get("description"),
            "description": payload.get("description"),
            "call_to_action": payload.get("call_to_action") or payload.get("cta"),
            "landing_url": payload.get("landing_url") or payload.get("url"),
            "preview_image_url": payload.get("preview_image_url") or payload.get("image_url") or payload.get("thumbnail_url") or payload.get("media_url"),
            "preview_video_url": payload.get("preview_video_url") or payload.get("video_url"),
            "raw_data": payload,
            "last_seen_at": now,
            "last_synced_at": now,
            "is_active": normalize_status(payload.get("status")) == "ACTIVE",
        },
    )

    snapshot_date = get_metric_date(payload)
    md = metric_defaults(payload)
    ad_metric, _ = AdMetricHistory.objects.update_or_create(ad=ad, date=snapshot_date, defaults=md)
    CampaignMetricHistory.objects.update_or_create(campaign=campaign, date=snapshot_date, defaults=md)
    AdGroupMetricHistory.objects.update_or_create(ad_group=ad_group, date=snapshot_date, defaults=md)
    CreativeMetricHistory.objects.update_or_create(creative=creative, date=snapshot_date, defaults=md)

    return {"campaign": campaign, "ad_group": ad_group, "creative": creative, "ad": ad, "metric": ad_metric}
