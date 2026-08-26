from decimal import Decimal
from django.utils import timezone

from core.models import Campaign, AdGroup, Ad, Creative


def _to_decimal(value, default="0"):
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def upsert_campaign(platform_account, data):
    campaign, created = Campaign.objects.update_or_create(
        platform_account=platform_account,
        platform_campaign_id=str(data.get("platform_campaign_id")),
        defaults={
            "name": data.get("name") or "İsimsiz Kampanya",
            "objective": data.get("objective") or "",
            "status": data.get("status") or "",
            "daily_budget": _to_decimal(data.get("daily_budget")),
            "lifetime_budget": _to_decimal(data.get("lifetime_budget")),
            "start_time": data.get("start_time"),
            "end_time": data.get("end_time"),
            "last_synced_at": timezone.now(),
        },
    )
    return campaign, created


def upsert_ad_group(platform_account, campaign, data):
    ad_group, created = AdGroup.objects.update_or_create(
        platform_account=platform_account,
        platform_adgroup_id=str(data.get("platform_adgroup_id")),
        defaults={
            "campaign": campaign,
            "name": data.get("name") or "İsimsiz Reklam Grubu",
            "status": data.get("status") or "",
            "optimization_goal": data.get("optimization_goal") or "",
            "billing_event": data.get("billing_event") or "",
            "bid_strategy": data.get("bid_strategy") or "",
            "daily_budget": _to_decimal(data.get("daily_budget")),
            "lifetime_budget": _to_decimal(data.get("lifetime_budget")),
            "start_time": data.get("start_time"),
            "end_time": data.get("end_time"),
            "last_synced_at": timezone.now(),
        },
    )
    return ad_group, created


def upsert_creative(platform_account, data):
    creative_id = data.get("platform_creative_id")

    if not creative_id:
        return None, False

    creative, created = Creative.objects.update_or_create(
        platform_account=platform_account,
        platform_creative_id=str(creative_id),
        defaults={
            "name": data.get("name") or "İsimsiz Kreatif",
            "creative_type": data.get("creative_type") or "",
            "title": data.get("title") or "",
            "body": data.get("body") or "",
            "image_url": data.get("image_url") or "",
            "video_url": data.get("video_url") or "",
            "thumbnail_url": data.get("thumbnail_url") or "",
            "destination_url": data.get("destination_url") or "",
            "last_synced_at": timezone.now(),
        },
    )
    return creative, created


def upsert_ad(platform_account, campaign, ad_group, data, creative=None):
    ad, created = Ad.objects.update_or_create(
        platform_account=platform_account,
        source_type=data.get("source_type") or "owned",
        platform_ad_id=str(data.get("platform_ad_id")),
        defaults={
            "campaign": campaign,
            "ad_group": ad_group,
            "creative": creative,
            "name": data.get("name") or "İsimsiz Reklam",
            "status": data.get("status") or "",
            "effective_status": data.get("effective_status") or "",
            "review_status": data.get("review_status") or "",
            "preview_url": data.get("preview_url") or "",
            "last_synced_at": timezone.now(),
        },
    )
    return ad, created


def sync_ad_entity_tree(platform_account, payload):
    campaign, campaign_created = upsert_campaign(
        platform_account,
        payload.get("campaign", {}),
    )

    ad_group, ad_group_created = upsert_ad_group(
        platform_account,
        campaign,
        payload.get("ad_group", {}),
    )

    creative, creative_created = upsert_creative(
        platform_account,
        payload.get("creative", {}),
    )

    ad, ad_created = upsert_ad(
        platform_account,
        campaign,
        ad_group,
        payload.get("ad", {}),
        creative=creative,
    )

    return {
        "campaign": campaign,
        "campaign_created": campaign_created,
        "ad_group": ad_group,
        "ad_group_created": ad_group_created,
        "creative": creative,
        "creative_created": creative_created,
        "ad": ad,
        "ad_created": ad_created,
    }