from __future__ import annotations

import random
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import (
    Ad,
    AdGroupMetricHistory,
    AdMetricHistory,
    AnomalyAlert,
    CampaignMetricHistory,
    CreativeMetricHistory,
    MarketplaceListing,
    MarketplaceListingMetricHistory,
    MarketplaceSyncRun,
    Notification,
    SocialPost,
    SocialPostMetricHistory,
)
from core.services.cache_service import CacheService


INTEGER_FIELDS = [
    "impressions",
    "reach",
    "clicks",
    "link_clicks",
    "unique_clicks",
    "landing_page_views",
    "outbound_clicks",
    "likes",
    "comments",
    "shares",
    "saves",
    "video_views",
    "engagement",
]

DECIMAL_SUM_FIELDS = [
    "spend",
    "conversions",
    "conversion_value",
    "purchases",
    "add_to_cart",
    "initiate_checkout",
    "leads",
]

DERIVED_DECIMAL_FIELDS = [
    "frequency",
    "ctr",
    "cpc",
    "cpm",
    "cost_per_conversion",
    "roas",
    "engagement_rate",
]

METRIC_FIELDS = INTEGER_FIELDS + DECIMAL_SUM_FIELDS + DERIVED_DECIMAL_FIELDS + ["currency", "raw_metrics"]


def _money(value) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _ratio(value) -> Decimal:
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _is_demo_raw(raw_data):
    return isinstance(raw_data, dict) and raw_data.get("demo") is True


def _refresh_demo_organic_metrics(demo_user, metric_date):
    if demo_user is None:
        return 0

    platform_factor = {
        "instagram": 1.35,
        "tiktok": 1.55,
        "linkedin": 0.82,
        "x": 0.72,
        "youtube": 1.45,
        "facebook": 1.05,
        "google_ads": 0.70,
    }
    type_factor = {
        "REELS": 1.45,
        "SHORTS": 1.38,
        "VIDEO": 1.25,
        "CAROUSEL": 1.12,
        "IMAGE": 0.92,
        "TEXT": 0.70,
        "LINK": 0.78,
        "UNKNOWN": 0.80,
    }
    rows = 0
    posts = (
        SocialPost.objects.filter(user=demo_user, raw_data__demo=True)
        .select_related("platform_account__platform")
        .order_by("id")
    )
    for post in posts:
        if post.posted_at and post.posted_at.date() > metric_date:
            continue

        rng = random.Random(f"demo-organic:{post.id}:{metric_date.isoformat()}")
        platform_code = (
            post.platform_account.platform.code
            if post.platform_account_id and post.platform_account
            else "instagram"
        )
        age_days = (
            max((metric_date - post.posted_at.date()).days, 1)
            if post.posted_at
            else 30
        )
        freshness = max(0.58, 1.22 - min(age_days, 120) * 0.0042)
        weekday_factor = (
            1.08
            if metric_date.weekday() in (1, 2, 3)
            else (0.91 if metric_date.weekday() in (5, 6) else 1.0)
        )
        base = (
            (1450 + (post.id % 11) * 165)
            * platform_factor.get(platform_code, 1.0)
            * type_factor.get(post.post_type, 1.0)
        )
        impressions = max(
            320,
            int(base * freshness * weekday_factor * rng.uniform(0.84, 1.18)),
        )
        reach = int(impressions * rng.uniform(0.69, 0.88))
        engagement_rate = rng.uniform(0.038, 0.082)
        if post.post_type in ("REELS", "SHORTS"):
            engagement_rate *= 1.12
        engagement_target = max(18, int(reach * engagement_rate))
        likes = int(engagement_target * rng.uniform(0.59, 0.70))
        comments = int(engagement_target * rng.uniform(0.055, 0.105))
        shares = int(engagement_target * rng.uniform(0.075, 0.145))
        saves = max(1, engagement_target - likes - comments - shares)
        engagement = likes + comments + shares + saves
        video_views = (
            int(reach * rng.uniform(0.48, 0.78))
            if post.post_type in ("VIDEO", "REELS", "SHORTS")
            else 0
        )
        profile_visits = max(1, int(reach * rng.uniform(0.012, 0.031)))
        website_clicks = max(0, int(profile_visits * rng.uniform(0.18, 0.42)))

        SocialPostMetricHistory.objects.update_or_create(
            social_post=post,
            date=metric_date,
            defaults={
                "impressions": impressions,
                "reach": reach,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "saves": saves,
                "video_views": video_views,
                "profile_visits": profile_visits,
                "website_clicks": website_clicks,
                "engagement": engagement,
                "engagement_rate": _ratio(
                    Decimal(engagement) / Decimal(max(impressions, 1)) * Decimal("100")
                ),
                "raw_metrics": {"demo": True, "daily_refresh": True},
            },
        )
        rows += 1

    CacheService.bump_version("organic_content", demo_user.id)
    return rows


DEMO_SCENARIOS = [
    "roas_winner",
    "roas_drop",
    "creative_fatigue",
    "campaign_scaling",
    "competitor_pressure",
]


def _demo_ads_queryset():
    return (
        Ad.objects.filter(
            Q(raw_data__demo=True)
            | Q(platform_account__extra_data__demo=True)
            | Q(platform_connection__extra_data__demo=True)
            | Q(user__username="demo")
        )
        .select_related("campaign", "ad_group", "creative", "platform_account", "platform_connection")
        .order_by("id")
    )


def _base_metrics_for_ad(ad, metric_date: date):
    latest = AdMetricHistory.objects.filter(ad=ad, date__lt=metric_date).order_by("-date").first()
    rng = random.Random(f"demo-metric:{metric_date.isoformat()}:{ad.pk}")
    scenario = _scenario_for_object("ad", ad.pk, metric_date)
    if latest:
        factor = _scenario_volume_factor(scenario, rng)
        data = {field: getattr(latest, field) for field in INTEGER_FIELDS + DECIMAL_SUM_FIELDS}
        for field in INTEGER_FIELDS:
            data[field] = max(1, int(data[field] * float(factor)))
        for field in DECIMAL_SUM_FIELDS:
            data[field] = _money(Decimal(data[field]) * factor)
    else:
        impressions = rng.randint(1800, 7200)
        clicks = max(1, int(impressions * rng.uniform(0.014, 0.045)))
        spend = _money(Decimal(impressions) / Decimal("1000") * Decimal(str(rng.uniform(32, 88))))
        conversions = _ratio(Decimal(clicks) * Decimal(str(rng.uniform(0.025, 0.075))))
        conversion_value = _money(conversions * Decimal(str(rng.uniform(650, 1650))))
        engagement = int(impressions * rng.uniform(0.025, 0.085))
        data = {
            "impressions": impressions,
            "reach": int(impressions * rng.uniform(0.62, 0.88)),
            "clicks": clicks,
            "link_clicks": int(clicks * rng.uniform(0.72, 0.92)),
            "unique_clicks": int(clicks * rng.uniform(0.62, 0.86)),
            "landing_page_views": int(clicks * rng.uniform(0.55, 0.82)),
            "outbound_clicks": int(clicks * rng.uniform(0.42, 0.77)),
            "likes": int(engagement * rng.uniform(0.42, 0.68)),
            "comments": int(engagement * rng.uniform(0.04, 0.14)),
            "shares": int(engagement * rng.uniform(0.05, 0.18)),
            "saves": int(engagement * rng.uniform(0.08, 0.22)),
            "video_views": int(impressions * rng.uniform(0.12, 0.48)),
            "engagement": engagement,
            "spend": spend,
            "conversions": conversions,
            "conversion_value": conversion_value,
            "purchases": conversions,
            "add_to_cart": _ratio(conversions * Decimal(str(rng.uniform(1.8, 4.2)))),
            "initiate_checkout": _ratio(conversions * Decimal(str(rng.uniform(1.2, 2.3)))),
            "leads": _ratio(Decimal(clicks) * Decimal(str(rng.uniform(0.02, 0.11)))),
        }
    data = _apply_demo_scenario(data, scenario, rng)
    data["currency"] = getattr(ad.campaign, "currency", None) or "TRY"
    data.update(_calculate_derived_fields(data))
    data["raw_metrics"] = {"demo": True, "daily_refresh": True, "scenario": scenario}
    return data


def _scenario_for_object(kind, object_id, metric_date: date):
    index = random.Random(f"demo-scenario:{kind}:{object_id}:{metric_date:%Y-%m-%d}").randrange(len(DEMO_SCENARIOS))
    return DEMO_SCENARIOS[index]


def _scenario_volume_factor(scenario, rng):
    ranges = {
        "roas_winner": (Decimal("1.05"), Decimal("1.22")),
        "roas_drop": (Decimal("0.84"), Decimal("1.03")),
        "creative_fatigue": (Decimal("0.90"), Decimal("1.08")),
        "campaign_scaling": (Decimal("1.18"), Decimal("1.42")),
        "competitor_pressure": (Decimal("0.94"), Decimal("1.14")),
    }
    low, high = ranges.get(scenario, (Decimal("0.88"), Decimal("1.16")))
    return Decimal(str(round(rng.uniform(float(low), float(high)), 4)))


def _apply_demo_scenario(data, scenario, rng):
    data = dict(data)
    if scenario == "roas_winner":
        data["conversion_value"] = _money(Decimal(data["conversion_value"]) * Decimal(str(rng.uniform(1.25, 1.75))))
        data["conversions"] = _ratio(Decimal(data["conversions"]) * Decimal(str(rng.uniform(1.08, 1.28))))
    elif scenario == "roas_drop":
        data["spend"] = _money(Decimal(data["spend"]) * Decimal(str(rng.uniform(1.08, 1.35))))
        data["conversion_value"] = _money(Decimal(data["conversion_value"]) * Decimal(str(rng.uniform(0.52, 0.78))))
        data["conversions"] = _ratio(Decimal(data["conversions"]) * Decimal(str(rng.uniform(0.62, 0.84))))
    elif scenario == "creative_fatigue":
        data["clicks"] = max(1, int(data["clicks"] * rng.uniform(0.55, 0.78)))
        data["link_clicks"] = max(1, int(data["link_clicks"] * rng.uniform(0.55, 0.78)))
        data["engagement"] = max(1, int(data["engagement"] * rng.uniform(0.50, 0.74)))
    elif scenario == "campaign_scaling":
        data["spend"] = _money(Decimal(data["spend"]) * Decimal(str(rng.uniform(1.22, 1.55))))
        data["impressions"] = max(1, int(data["impressions"] * rng.uniform(1.18, 1.44)))
        data["reach"] = max(1, int(data["reach"] * rng.uniform(1.12, 1.32)))
        data["conversion_value"] = _money(Decimal(data["conversion_value"]) * Decimal(str(rng.uniform(1.10, 1.36))))
    elif scenario == "competitor_pressure":
        data["cpc"] = _ratio(Decimal(data.get("cpc") or 0) * Decimal(str(rng.uniform(1.12, 1.35))))
        data["spend"] = _money(Decimal(data["spend"]) * Decimal(str(rng.uniform(1.06, 1.24))))
        data["clicks"] = max(1, int(data["clicks"] * rng.uniform(0.82, 0.96)))
    return data


def _calculate_derived_fields(data):
    impressions = max(int(data.get("impressions") or 0), 1)
    reach = max(int(data.get("reach") or 0), 1)
    clicks = max(int(data.get("clicks") or 0), 1)
    spend = Decimal(data.get("spend") or 0)
    conversions = Decimal(data.get("conversions") or 0)
    conversion_value = Decimal(data.get("conversion_value") or 0)
    engagement = int(data.get("engagement") or 0)
    return {
        "frequency": _ratio(Decimal(impressions) / Decimal(reach)),
        "ctr": _ratio(Decimal(clicks) / Decimal(impressions) * Decimal("100")),
        "cpc": _ratio(spend / Decimal(clicks)),
        "cpm": _ratio(spend / Decimal(impressions) * Decimal("1000")),
        "cost_per_conversion": _ratio(spend / max(conversions, Decimal("1"))),
        "roas": _ratio(conversion_value / max(spend, Decimal("1"))),
        "engagement_rate": _ratio(Decimal(engagement) / Decimal(impressions) * Decimal("100")),
    }


def _copy_metric_fields(metric):
    return {field: getattr(metric, field) for field in METRIC_FIELDS}


def _rollup_rows(rows):
    data = {field: sum(int(row[field]) for row in rows) for field in INTEGER_FIELDS}
    data.update({field: sum((Decimal(row[field]) for row in rows), Decimal("0")) for field in DECIMAL_SUM_FIELDS})
    data["currency"] = rows[0].get("currency") or "TRY"
    data.update(_calculate_derived_fields(data))
    data["raw_metrics"] = {"demo": True, "daily_refresh": True, "rolled_up": True}
    return data


def _demo_marketplace_listings_queryset():
    return (
        MarketplaceListing.objects.filter(
            Q(product__user__username="demo")
            | Q(raw_payload__demo=True)
            | Q(marketplace_account__extra_credentials__demo=True)
        )
        .select_related("marketplace_account", "marketplace", "product", "variant")
        .order_by("id")
    )


def _refresh_demo_marketplace_metrics(metric_date, now):
    listing_count = 0
    sync_runs = {}

    for listing in _demo_marketplace_listings_queryset():
        account = listing.marketplace_account
        if account_id := account.id:
            sync_run = sync_runs.get(account_id)
            if sync_run is None:
                sync_run = (
                    MarketplaceSyncRun.objects.filter(
                        marketplace_account=account,
                        sync_type=MarketplaceSyncRun.SYNC_TYPE_PRICE_STOCK,
                        status=MarketplaceSyncRun.STATUS_SUCCESS,
                        filters__demo=True,
                        filters__date=metric_date.isoformat(),
                    )
                    .order_by("-created_at")
                    .first()
                )
                if sync_run is None:
                    sync_run = MarketplaceSyncRun.objects.create(
                        marketplace_account=account,
                        sync_type=MarketplaceSyncRun.SYNC_TYPE_PRICE_STOCK,
                        status=MarketplaceSyncRun.STATUS_SUCCESS,
                        product_limit=account.sync_product_limit,
                        filters={"demo": True, "daily_refresh": True, "date": metric_date.isoformat()},
                        started_at=now,
                        finished_at=now,
                    )
                    marketplace_sync_created = True
                else:
                    marketplace_sync_created = False
                    sync_run.finished_at = now
                    sync_run.fetched_count = sync_run.fetched_count + 1
                    sync_run.updated_count = sync_run.updated_count + 1
                    sync_run.save(
                        update_fields=["finished_at", "fetched_count", "updated_count"]
                    )
                sync_runs[account_id] = (
                    sync_run,
                    marketplace_sync_created,
                )
            else:
                sync_run, marketplace_sync_created = sync_run
        else:
            sync_run = None
            marketplace_sync_created = False

        rng = random.Random(f"demo-marketplace:{metric_date.isoformat()}:{listing.pk}")
        scenario = _scenario_for_object("listing", listing.pk, metric_date)
        previous = listing.metric_history.filter(date__lt=metric_date).order_by("-date").first()
        base_price = Decimal(previous.discounted_price or previous.sale_price) if previous else Decimal(listing.effective_sale_price or listing.sale_price or 0)
        if base_price <= 0:
            base_price = Decimal("299.90")

        price_factor = Decimal(str(round(rng.uniform(0.97, 1.04), 4)))
        if scenario == "roas_winner":
            stock_delta = -rng.randint(4, 14)
            order_factor = rng.uniform(1.25, 1.8)
        elif scenario == "roas_drop":
            stock_delta = -rng.randint(0, 3)
            order_factor = rng.uniform(0.45, 0.85)
        elif scenario == "competitor_pressure":
            price_factor = Decimal(str(round(rng.uniform(0.92, 0.98), 4)))
            stock_delta = -rng.randint(1, 6)
            order_factor = rng.uniform(0.75, 1.05)
        else:
            stock_delta = -rng.randint(1, 9)
            order_factor = rng.uniform(0.85, 1.3)

        sale_price = _money(base_price * price_factor)
        discounted_price = _money(sale_price * Decimal(str(rng.uniform(0.86, 0.98))))
        stock = max(0, int((previous.stock if previous else listing.stock) + stock_delta + rng.randint(0, 5)))
        views = max(20, int((previous.view_count if previous else listing.view_count or 120) * rng.uniform(0.9, 1.22)))
        orders = max(0, int((views * rng.uniform(0.008, 0.038)) * order_factor))
        units_sold = max(orders, orders + rng.randint(0, max(1, orders // 3 + 1)))
        revenue = _money(discounted_price * Decimal(units_sold))
        purchase_price = Decimal(listing.purchase_price or 0)
        gross_profit = _money(discounted_price - purchase_price)
        gross_margin = _ratio((gross_profit / discounted_price) * Decimal("100")) if discounted_price else Decimal("0")

        MarketplaceListingMetricHistory.objects.update_or_create(
            listing=listing,
            date=metric_date,
            defaults={
                "marketplace_account": account,
                "marketplace": listing.marketplace,
                "product": listing.product,
                "variant": listing.variant,
                "sale_price": sale_price,
                "discounted_price": discounted_price,
                "purchase_price": purchase_price,
                "commission_rate": listing.commission_rate,
                "stock": stock,
                "status": listing.status,
                "gross_profit": gross_profit,
                "gross_margin_rate": gross_margin,
                "orders": orders,
                "units_sold": units_sold,
                "revenue": revenue,
                "view_count": views,
                "favorite_count": max(0, int((previous.favorite_count if previous else listing.favorite_count) + rng.randint(0, 12))),
                "review_count": max(0, int((previous.review_count if previous else listing.review_count) + rng.choice([0, 0, 1]))),
                "return_count": rng.randint(0, max(1, orders // 12 + 1)),
                "buybox_rank": max(1, int(listing.buybox_rank or rng.randint(1, 8))),
                "raw_metrics": {"demo": True, "daily_refresh": True, "scenario": scenario},
                "sync_run": sync_run,
            },
        )
        listing.sale_price = sale_price
        listing.discounted_price = discounted_price
        listing.stock = stock
        listing.view_count = views
        listing.last_synced_at = now
        listing.raw_payload = {**(listing.raw_payload or {}), "demo": True, "last_demo_scenario": scenario}
        listing.save(update_fields=["sale_price", "discounted_price", "stock", "view_count", "last_synced_at", "raw_payload", "updated_at"])
        account.last_sync_at = now
        account.save(update_fields=["last_sync_at", "updated_at"])
        listing_count += 1

    return listing_count, sum(1 for _, created in sync_runs.values() if created)


def _create_daily_demo_signal(user, metric_date):
    if not user:
        return {"alerts": 0, "notifications": 0}

    date_text = metric_date.isoformat()
    best = (
        AdMetricHistory.objects.filter(ad__user=user, date=metric_date, ad__source_type="OWN")
        .select_related("ad")
        .order_by("-roas")
        .first()
    )
    weak = (
        AdMetricHistory.objects.filter(ad__user=user, date=metric_date, ad__source_type="OWN", spend__gt=0)
        .select_related("ad")
        .order_by("roas")
        .first()
    )
    competitor = (
        AdMetricHistory.objects.filter(ad__user=user, date=metric_date, ad__source_type="COMPETITOR")
        .select_related("ad")
        .order_by("-impressions")
        .first()
    )

    candidates = []
    if best and best.roas >= Decimal("3.2"):
        candidates.append({
            "type": "opportunity",
            "severity": "medium",
            "level": "success",
            "ad": best.ad,
            "title": "Demo ROAS firsati",
            "description": f"{best.ad.name or best.ad.headline or 'Demo reklam'} bugun {best.roas} ROAS uretti. Butce artirimi senaryosu icin iyi aday.",
            "old_value": None,
            "new_value": float(best.roas),
            "change_percent": None,
            "action": "Kazanan kampanyanin butcesini kontrollu artir ve benzer kreatif varyasyonlari uret.",
        })
    if weak and weak.roas <= Decimal("1.4"):
        candidates.append({
            "type": "ctr_change",
            "severity": "high",
            "level": "warning",
            "ad": weak.ad,
            "title": "Demo dusuk ROAS uyarisi",
            "description": f"{weak.ad.name or weak.ad.headline or 'Demo reklam'} bugun {weak.roas} ROAS seviyesine dustu. Kreatif veya hedef kitle yorgunlugu senaryosu olustu.",
            "old_value": None,
            "new_value": float(weak.roas),
            "change_percent": None,
            "action": "Kreatifi yenile, hedef kitleyi daralt ve harcamayi gecici olarak sinirla.",
        })
    if competitor:
        candidates.append({
            "type": "impression_spike",
            "severity": "medium",
            "level": "info",
            "ad": competitor.ad,
            "title": "Demo rakip baskisi",
            "description": f"{competitor.ad.name or competitor.ad.headline or 'Rakip reklam'} gorunurlugu yukseldi. Rakip takip senaryosu guncellendi.",
            "old_value": None,
            "new_value": float(competitor.impressions),
            "change_percent": None,
            "action": "Rakip mesajini incele, teklif ve kreatif ayrismasini guclendir.",
        })

    alerts = 0
    notifications = 0
    for candidate in candidates[:2]:
        alert = AnomalyAlert.objects.filter(
            user=user,
            title=candidate["title"],
            detected_at__date=metric_date,
        ).first()
        if alert is None:
            alert = AnomalyAlert.objects.create(
                user=user,
                rakip=candidate["ad"],
                alert_type=candidate["type"],
                severity=candidate["severity"],
                title=candidate["title"],
                description=candidate["description"],
                old_value=candidate["old_value"],
                new_value=candidate["new_value"],
                change_percent=candidate["change_percent"],
                suggested_action=candidate["action"],
                action_link="/dashboard/",
            )
            alerts += 1
        if not Notification.objects.filter(user=user, title=candidate["title"], created_at__date=metric_date).exists():
            from core.services.activity_service import object_activity_link

            Notification.objects.create(
                user=user,
                title=candidate["title"],
                message=f"{candidate['description']} ({date_text})",
                level=candidate["level"],
                icon="chart-line",
                link=object_activity_link(candidate["ad"]) or object_activity_link(alert) or "/dashboard/",
            )
            notifications += 1
    return {"alerts": alerts, "notifications": notifications}


def refresh_demo_metrics_for_date(metric_date=None):
    from django.contrib.auth import get_user_model

    metric_date = metric_date or timezone.localdate()
    now = timezone.now()
    ad_count = 0
    competitor_ad_count = 0
    creative_count = 0
    ads_by_campaign = {}
    ads_by_ad_group = {}
    demo_user = get_user_model().objects.filter(username="demo").first()

    with transaction.atomic():
        for ad in _demo_ads_queryset():
            metrics = _base_metrics_for_ad(ad, metric_date)
            ad_metric, _ = AdMetricHistory.objects.update_or_create(
                ad=ad,
                date=metric_date,
                defaults={
                    **metrics,
                    "is_competitor_snapshot": ad.source_type == "COMPETITOR",
                },
            )
            if ad.source_type == "COMPETITOR":
                competitor_ad_count += 1
            else:
                ad_count += 1

            if ad.creative_id:
                creative_defaults = _copy_metric_fields(ad_metric)
                rng = random.Random(f"demo-creative:{metric_date.isoformat()}:{ad.creative_id}")
                creative_defaults.update({
                    "thumbstop_rate": _ratio(Decimal(str(rng.uniform(0.22, 0.58)))),
                    "hook_rate": _ratio(Decimal(str(rng.uniform(0.18, 0.46)))),
                    "hold_rate": _ratio(Decimal(str(rng.uniform(0.12, 0.38)))),
                })
                CreativeMetricHistory.objects.update_or_create(
                    creative=ad.creative,
                    date=metric_date,
                    defaults=creative_defaults,
                )
                ad.creative.last_seen_at = now
                ad.creative.save(update_fields=["last_seen_at", "updated_at"])
                creative_count += 1

            if ad.campaign_id:
                ads_by_campaign.setdefault(ad.campaign_id, []).append(_copy_metric_fields(ad_metric))
                ad.campaign.last_synced_at = now
                ad.campaign.save(update_fields=["last_synced_at", "updated_at"])
            if ad.ad_group_id:
                ads_by_ad_group.setdefault(ad.ad_group_id, []).append(_copy_metric_fields(ad_metric))
                ad.ad_group.last_synced_at = now
                ad.ad_group.save(update_fields=["last_synced_at", "updated_at"])

            ad.last_seen_at = now
            ad.last_synced_at = now
            ad.save(update_fields=["last_seen_at", "last_synced_at", "updated_at"])
            if ad.platform_account_id:
                ad.platform_account.last_sync = now
                ad.platform_account.save(update_fields=["last_sync"])

        campaign_count = 0
        for campaign_id, rows in ads_by_campaign.items():
            CampaignMetricHistory.objects.update_or_create(
                campaign_id=campaign_id,
                date=metric_date,
                defaults=_rollup_rows(rows),
            )
            campaign_count += 1

        ad_group_count = 0
        for ad_group_id, rows in ads_by_ad_group.items():
            AdGroupMetricHistory.objects.update_or_create(
                ad_group_id=ad_group_id,
                date=metric_date,
                defaults=_rollup_rows(rows),
            )
            ad_group_count += 1

        marketplace_listing_count, marketplace_sync_count = _refresh_demo_marketplace_metrics(metric_date, now)
        organic_metric_count = _refresh_demo_organic_metrics(demo_user, metric_date)
        signal_counts = _create_daily_demo_signal(demo_user, metric_date)

    return {
        "success": True,
        "date": metric_date.isoformat(),
        "ads": ad_count,
        "competitor_ads": competitor_ad_count,
        "creatives": creative_count,
        "campaigns": campaign_count,
        "ad_groups": ad_group_count,
        "marketplace_listings": marketplace_listing_count,
        "marketplace_sync_runs": marketplace_sync_count,
        "organic_metrics": organic_metric_count,
        **signal_counts,
    }
