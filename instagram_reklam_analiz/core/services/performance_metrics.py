from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from django.conf import settings
from django.db.models import Avg, Count, Max, Sum


ZERO = Decimal("0")
DEFAULT_ESTIMATED_CONVERSION_VALUE_PER_CONVERSION = Decimal("500")

PURCHASE_ACTION_TYPES = {
    "purchase",
    "omni_purchase",
    "onsite_conversion.purchase",
    "offsite_conversion.fb_pixel_purchase",
    "offsite_conversion.fb_pixel_custom",
    "web_in_store_purchase",
}

LEAD_ACTION_TYPES = {
    "lead",
    "omni_lead",
    "onsite_conversion.lead_grouped",
    "offsite_conversion.fb_pixel_lead",
}

CHECKOUT_ACTION_TYPES = {
    "initiate_checkout",
    "omni_initiated_checkout",
    "offsite_conversion.fb_pixel_initiate_checkout",
}

CART_ACTION_TYPES = {
    "add_to_cart",
    "omni_add_to_cart",
    "offsite_conversion.fb_pixel_add_to_cart",
}

LANDING_PAGE_VIEW_ACTION_TYPES = {
    "landing_page_view",
}

OUTBOUND_CLICK_ACTION_TYPES = {
    "outbound_click",
}

SPEND_FIELDS = (
    "spend",
    "cost",
    "amount_spent",
)

CONVERSION_FIELDS = (
    "conversions",
    "conversion",
    "all_conversions",
    "purchases",
    "orders",
    "order_count",
    "transactions",
    "sales_count",
    "leads",
)

CONVERSION_VALUE_FIELDS = (
    "conversion_value",
    "conversions_value",
    "all_conversions_value",
    "purchase_value",
    "purchase_revenue",
    "total_purchase_value",
    "revenue",
    "total_revenue",
    "sales",
    "sales_value",
    "sales_amount",
    "order_value",
    "orders_value",
    "transaction_revenue",
    "gross_revenue",
    "gmv",
    "value",
)


def safe_decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def safe_div(numerator: Any, denominator: Any, multiplier: Any = 1) -> Decimal:
    denominator_dec = safe_decimal(denominator)
    if not denominator_dec:
        return ZERO
    return safe_decimal(numerator) / denominator_dec * safe_decimal(multiplier)


def _iter_action_items(value: Any):
    if not value:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _nested_source(data: Mapping[str, Any], key: str) -> Any:
    if key in data:
        return data.get(key)
    for parent in ("metrics", "insights", "stats", "statistics"):
        nested = data.get(parent)
        if isinstance(nested, Mapping) and key in nested:
            return nested.get(key)
    return None


def _first_decimal(data: Mapping[str, Any], fields: tuple[str, ...]) -> Decimal:
    for field in fields:
        value = _nested_source(data, field)
        if value not in [None, ""]:
            decimal_value = safe_decimal(value)
            if decimal_value:
                return decimal_value
    return ZERO


def _estimated_value_per_conversion(data: Mapping[str, Any]) -> Decimal:
    configured = getattr(
        settings,
        "DEFAULT_ESTIMATED_CONVERSION_VALUE_PER_CONVERSION",
        DEFAULT_ESTIMATED_CONVERSION_VALUE_PER_CONVERSION,
    )
    return (
        safe_decimal(data.get("estimated_conversion_value_per_conversion"))
        or safe_decimal(data.get("average_order_value"))
        or safe_decimal(data.get("avg_order_value"))
        or safe_decimal(data.get("aov"))
        or safe_decimal(configured)
        or DEFAULT_ESTIMATED_CONVERSION_VALUE_PER_CONVERSION
    )


def _sum_actions(data: Mapping[str, Any], field: str, action_types: set[str]) -> Decimal:
    total = ZERO
    for item in _iter_action_items(data.get(field)):
        action_type = str(item.get("action_type") or item.get("type") or "").lower()
        if action_type in action_types:
            total += safe_decimal(item.get("value"))
    return total


def _first_roas_value(data: Mapping[str, Any]) -> Decimal:
    for field in ("roas", "purchase_roas", "website_purchase_roas"):
        value = data.get(field)
        if isinstance(value, list):
            for item in _iter_action_items(value):
                roas = safe_decimal(item.get("value"))
                if roas:
                    return roas
        else:
            roas = safe_decimal(value)
            if roas:
                return roas
    return ZERO


def normalize_metric_payload(data: Mapping[str, Any] | None) -> dict[str, Any]:
    """
    Platformdan veya manuel akistan gelen tek metrik satirini tek formulle
    normalize eder. Hesaplanan alanlar burada uretildigi icin dashboard ve raporlar
    ayni tablo degerlerini okur.
    """
    data = dict(data or {})

    impressions = safe_int(data.get("impressions"))
    reach = safe_int(data.get("reach"))
    clicks = safe_int(data.get("clicks") or data.get("link_clicks"))
    link_clicks = safe_int(data.get("link_clicks") or clicks)
    unique_clicks = safe_int(data.get("unique_clicks"))

    spend = _first_decimal(data, SPEND_FIELDS)
    if not spend and _nested_source(data, "cost_micros") not in [None, ""]:
        spend = safe_decimal(_nested_source(data, "cost_micros")) / Decimal("1000000")
    if not spend and _nested_source(data, "spend_micros") not in [None, ""]:
        spend = safe_decimal(_nested_source(data, "spend_micros")) / Decimal("1000000")
    purchases = safe_decimal(data.get("purchases")) or _sum_actions(data, "actions", PURCHASE_ACTION_TYPES)
    leads = safe_decimal(data.get("leads")) or _sum_actions(data, "actions", LEAD_ACTION_TYPES)
    add_to_cart = safe_decimal(data.get("add_to_cart")) or _sum_actions(data, "actions", CART_ACTION_TYPES)
    initiate_checkout = safe_decimal(data.get("initiate_checkout")) or _sum_actions(data, "actions", CHECKOUT_ACTION_TYPES)
    landing_page_views = safe_int(data.get("landing_page_views")) or safe_int(
        _sum_actions(data, "actions", LANDING_PAGE_VIEW_ACTION_TYPES)
    )
    outbound_clicks = safe_int(data.get("outbound_clicks")) or safe_int(
        _sum_actions(data, "actions", OUTBOUND_CLICK_ACTION_TYPES)
    )

    conversions = _first_decimal(data, CONVERSION_FIELDS) or purchases or leads
    conversion_value = _first_decimal(data, CONVERSION_VALUE_FIELDS)
    if not conversion_value and _nested_source(data, "conversions_value_micros") not in [None, ""]:
        conversion_value = safe_decimal(_nested_source(data, "conversions_value_micros")) / Decimal("1000000")
    if not conversion_value and _nested_source(data, "revenue_micros") not in [None, ""]:
        conversion_value = safe_decimal(_nested_source(data, "revenue_micros")) / Decimal("1000000")
    conversion_value = conversion_value or _sum_actions(data, "action_values", PURCHASE_ACTION_TYPES)
    if not conversion_value and safe_decimal(data.get("roi")) and spend:
        conversion_value = spend * safe_decimal(data.get("roi")) / Decimal("100")
    meta_roas = _first_roas_value(data)
    if not conversion_value and meta_roas and spend:
        conversion_value = spend * meta_roas
    if not conversion_value and conversions:
        estimated_per_conversion = _estimated_value_per_conversion(data)
        conversion_value = conversions * estimated_per_conversion
        data["conversion_value_estimated"] = True
        data["conversion_value_estimate_method"] = "conversions_x_estimated_value"
        data["estimated_conversion_value_per_conversion"] = str(estimated_per_conversion)

    likes = safe_int(data.get("likes"))
    comments = safe_int(data.get("comments"))
    shares = safe_int(data.get("shares"))
    saves = safe_int(data.get("saves"))
    video_views = safe_int(data.get("video_views"))
    engagement = safe_int(data.get("engagement")) or likes + comments + shares + saves

    ctr = safe_decimal(data.get("ctr")) or safe_div(clicks, impressions, 100)
    cpc = safe_decimal(data.get("cpc")) or safe_div(spend, clicks)
    cpm = safe_decimal(data.get("cpm")) or safe_div(spend, impressions, 1000)
    frequency = safe_decimal(data.get("frequency")) or safe_div(impressions, reach)
    cost_per_conversion = safe_decimal(data.get("cost_per_conversion") or data.get("cpa")) or safe_div(spend, conversions)
    roas = meta_roas or safe_div(conversion_value, spend)
    engagement_rate = safe_decimal(data.get("engagement_rate")) or safe_div(engagement, impressions, 100)

    return {
        "impressions": impressions,
        "reach": reach,
        "frequency": frequency,
        "clicks": clicks,
        "link_clicks": link_clicks,
        "unique_clicks": unique_clicks,
        "spend": spend,
        "currency": data.get("currency") or "TRY",
        "ctr": ctr,
        "cpc": cpc,
        "cpm": cpm,
        "conversions": conversions,
        "conversion_value": conversion_value,
        "cost_per_conversion": cost_per_conversion,
        "purchases": purchases,
        "add_to_cart": add_to_cart,
        "initiate_checkout": initiate_checkout,
        "leads": leads,
        "landing_page_views": landing_page_views,
        "outbound_clicks": outbound_clicks,
        "roas": roas,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "saves": saves,
        "video_views": video_views,
        "engagement": engagement,
        "engagement_rate": engagement_rate,
        "raw_metrics": data.get("raw_metrics") or data,
    }


def aggregate_metric_queryset(qs):
    """
    Bir metrik queryset'i icin tek dogru ozet hesaplama.
    Oran metrikleri satir ortalamasi olarak degil, toplamlardan hesaplanir.
    """
    data = qs.aggregate(
        impressions=Sum("impressions"),
        reach=Sum("reach"),
        clicks=Sum("clicks"),
        link_clicks=Sum("link_clicks"),
        unique_clicks=Sum("unique_clicks"),
        spend=Sum("spend"),
        conversions=Sum("conversions"),
        conversion_value=Sum("conversion_value"),
        purchases=Sum("purchases"),
        add_to_cart=Sum("add_to_cart"),
        initiate_checkout=Sum("initiate_checkout"),
        leads=Sum("leads"),
        landing_page_views=Sum("landing_page_views"),
        outbound_clicks=Sum("outbound_clicks"),
        likes=Sum("likes"),
        comments=Sum("comments"),
        shares=Sum("shares"),
        saves=Sum("saves"),
        video_views=Sum("video_views"),
        engagement=Sum("engagement"),
        avg_frequency=Avg("frequency"),
        avg_engagement_rate=Avg("engagement_rate"),
        last_date=Max("date"),
        rows=Count("id"),
    )

    impressions = data.get("impressions") or 0
    clicks = data.get("clicks") or 0
    spend = safe_decimal(data.get("spend"))
    conversions = safe_decimal(data.get("conversions"))
    revenue = safe_decimal(data.get("conversion_value"))
    engagement = data.get("engagement") or 0
    reach = data.get("reach") or 0

    data.update({
        "impressions": impressions,
        "reach": reach,
        "clicks": clicks,
        "spend": spend,
        "conversions": conversions,
        "conversion_value": revenue,
        "ctr": safe_div(clicks, impressions, 100),
        "cpc": safe_div(spend, clicks),
        "cpm": safe_div(spend, impressions, 1000),
        "roas": safe_div(revenue, spend),
        "cpa": safe_div(spend, conversions),
        "conversion_rate": safe_div(conversions, clicks, 100),
        "engagement_rate": safe_div(engagement, impressions, 100),
        "frequency": safe_div(impressions, reach),
    })
    return data


def user_performance_queryset(user, start_date, end_date, *, prefer_campaign: bool = True):
    """
    Kullanici performansi icin standart metrik kaynagi.
    Kampanya metrikleri varsa once onlar kullanilir; yoksa reklam metriklerine duser.
    """
    from core.models import AdMetricHistory, CampaignMetricHistory

    if prefer_campaign:
        campaign_qs = CampaignMetricHistory.objects.filter(
            campaign__user=user,
            date__gte=start_date,
            date__lte=end_date,
        )
        if campaign_qs.exists():
            return campaign_qs, "campaign"

    return (
        AdMetricHistory.objects.filter(
            ad__user=user,
            ad__source_type="OWN",
            date__gte=start_date,
            date__lte=end_date,
        ),
        "ad",
    )
