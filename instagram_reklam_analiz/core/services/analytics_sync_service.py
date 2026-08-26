from decimal import Decimal
from django.db import transaction
from django.utils import timezone

from core.models import (
    AnalyticsProperty,
    AnalyticsDailyMetric,
    AnalyticsLandingPageMetric,
)


def _to_decimal(value, default="0"):
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _to_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except Exception:
        return default


@transaction.atomic
def upsert_analytics_property(
    user,
    platform_account,
    payload,
):
    property_obj, created = AnalyticsProperty.objects.update_or_create(
        platform_account=platform_account,
        property_id=str(payload.get("property_id")),
        defaults={
            "user": user,
            "platform_connection": getattr(
                platform_account,
                "connection",
                None,
            ),
            "property_name": payload.get("property_name"),
            "property_type": payload.get(
                "property_type",
                "GA4",
            ),
            "currency": payload.get(
                "currency",
                "TRY",
            ),
            "timezone": payload.get("timezone"),
            "raw_data": payload,
            "last_synced_at": timezone.now(),
            "is_active": True,
        },
    )

    return property_obj, created


@transaction.atomic
def save_daily_metric(
    property_obj,
    payload,
):
    metric, created = AnalyticsDailyMetric.objects.update_or_create(
        property=property_obj,
        date=payload["date"],
        defaults={
            "sessions": _to_int(payload.get("sessions")),
            "users": _to_int(payload.get("users")),
            "new_users": _to_int(payload.get("new_users")),

            "engaged_sessions": _to_int(
                payload.get("engaged_sessions")
            ),

            "engagement_rate": _to_decimal(
                payload.get("engagement_rate")
            ),

            "bounce_rate": _to_decimal(
                payload.get("bounce_rate")
            ),

            "average_session_duration": _to_decimal(
                payload.get("average_session_duration")
            ),

            "screen_page_views": _to_int(
                payload.get("screen_page_views")
            ),

            "event_count": _to_int(
                payload.get("event_count")
            ),

            "key_events": _to_decimal(
                payload.get("key_events")
            ),

            "conversions": _to_decimal(
                payload.get("conversions")
            ),

            "total_revenue": _to_decimal(
                payload.get("total_revenue")
            ),

            "purchase_revenue": _to_decimal(
                payload.get("purchase_revenue")
            ),

            "transactions": _to_decimal(
                payload.get("transactions")
            ),

            "average_purchase_revenue": _to_decimal(
                payload.get("average_purchase_revenue")
            ),

            "raw_metrics": payload,
        },
    )

    return metric, created


@transaction.atomic
def save_landing_page_metric(
    property_obj,
    payload,
):
    metric, created = AnalyticsLandingPageMetric.objects.update_or_create(
        property=property_obj,
        date=payload["date"],
        landing_page=payload["landing_page"],
        defaults={
            "landing_page_title": payload.get(
                "landing_page_title"
            ),

            "sessions": _to_int(payload.get("sessions")),
            "users": _to_int(payload.get("users")),
            "new_users": _to_int(payload.get("new_users")),

            "engaged_sessions": _to_int(
                payload.get("engaged_sessions")
            ),

            "engagement_rate": _to_decimal(
                payload.get("engagement_rate")
            ),

            "bounce_rate": _to_decimal(
                payload.get("bounce_rate")
            ),

            "conversions": _to_decimal(
                payload.get("conversions")
            ),

            "total_revenue": _to_decimal(
                payload.get("total_revenue")
            ),

            "raw_metrics": payload,
        },
    )

    return metric, created


@transaction.atomic
def sync_ga4_property(
    user,
    platform_account,
    property_payload,
    daily_metrics=None,
    landing_pages=None,
):
    property_obj, _ = upsert_analytics_property(
        user=user,
        platform_account=platform_account,
        payload=property_payload,
    )

    for item in daily_metrics or []:
        save_daily_metric(
            property_obj,
            item,
        )

    for item in landing_pages or []:
        save_landing_page_metric(
            property_obj,
            item,
        )

    return property_obj