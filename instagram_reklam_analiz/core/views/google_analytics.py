from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, render

from core.models import (
    AnalyticsDailyMetric,
    AnalyticsLandingPageMetric,
    AnalyticsProperty,
    Platform,
    PlatformAccount,
)


def _num(value):
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _pct(value):
    return round(float(_num(value) * Decimal("100")), 1)


def _google_analytics_accounts(user):
    return (
        PlatformAccount.objects
        .filter(user=user, platform__code="google_analytics", is_active=True)
        .select_related("platform", "agency_client")
        .prefetch_related("analytics_properties")
        .order_by("agency_client__name", "account_name", "account_id")
    )


def _property_rows(user):
    properties = (
        AnalyticsProperty.objects
        .filter(user=user, is_active=True)
        .select_related("platform_account", "platform_account__agency_client")
        .order_by("platform_account__account_name", "property_name", "property_id")
    )
    rows = []
    for prop in properties:
        metrics = prop.daily_metrics.all()
        totals = metrics.aggregate(
            sessions=Sum("sessions"),
            users=Sum("users"),
            conversions=Sum("conversions"),
            revenue=Sum("total_revenue"),
            events=Sum("event_count"),
        )
        latest = metrics.order_by("-date").first()
        rows.append({
            "property": prop,
            "account": prop.platform_account,
            "sessions": totals.get("sessions") or 0,
            "users": totals.get("users") or 0,
            "conversions": totals.get("conversions") or 0,
            "revenue": totals.get("revenue") or 0,
            "events": totals.get("events") or 0,
            "latest": latest,
        })
    return rows


@login_required
def google_analytics_center(request):
    accounts = list(_google_analytics_accounts(request.user))
    rows = _property_rows(request.user)
    property_ids = [row["property"].id for row in rows]
    daily_qs = AnalyticsDailyMetric.objects.filter(property_id__in=property_ids)
    totals = daily_qs.aggregate(
        sessions=Sum("sessions"),
        users=Sum("users"),
        engaged_sessions=Sum("engaged_sessions"),
        conversions=Sum("conversions"),
        revenue=Sum("total_revenue"),
        events=Sum("event_count"),
        views=Sum("screen_page_views"),
    )
    sessions = totals.get("sessions") or 0
    engaged = totals.get("engaged_sessions") or 0
    engagement_rate = round((engaged / sessions) * 100, 1) if sessions else 0

    recent_metrics = (
        daily_qs
        .select_related("property", "property__platform_account")
        .order_by("-date", "property__property_name")[:14]
    )

    return render(request, "google_analytics/center.html", {
        "accounts": accounts,
        "property_rows": rows,
        "recent_metrics": recent_metrics,
        "totals": {
            "accounts": len(accounts),
            "properties": len(rows),
            "sessions": sessions,
            "users": totals.get("users") or 0,
            "engagement_rate": engagement_rate,
            "conversions": totals.get("conversions") or 0,
            "revenue": totals.get("revenue") or 0,
            "events": totals.get("events") or 0,
            "views": totals.get("views") or 0,
        },
    })


@login_required
def google_analytics_property_detail(request, property_id):
    property_obj = get_object_or_404(
        AnalyticsProperty.objects.select_related("platform_account", "platform_account__agency_client"),
        id=property_id,
        user=request.user,
    )
    daily_metrics = list(property_obj.daily_metrics.order_by("-date")[:30])
    chart_metrics = list(reversed(daily_metrics[:14]))
    max_sessions = max([item.sessions for item in chart_metrics] or [1])
    chart_rows = [
        {
            "date": item.date,
            "sessions": item.sessions,
            "users": item.users,
            "height": max(8, int((item.sessions / max_sessions) * 100)) if max_sessions else 8,
        }
        for item in chart_metrics
    ]
    landing_pages = property_obj.landing_page_metrics.order_by("-date", "-sessions")[:20]
    totals = property_obj.daily_metrics.aggregate(
        sessions=Sum("sessions"),
        users=Sum("users"),
        engaged_sessions=Sum("engaged_sessions"),
        conversions=Sum("conversions"),
        revenue=Sum("total_revenue"),
        views=Sum("screen_page_views"),
    )
    sessions = totals.get("sessions") or 0
    engaged = totals.get("engaged_sessions") or 0

    return render(request, "google_analytics/detail.html", {
        "property": property_obj,
        "daily_metrics": daily_metrics,
        "landing_pages": landing_pages,
        "chart_rows": chart_rows,
        "totals": {
            "sessions": sessions,
            "users": totals.get("users") or 0,
            "engagement_rate": round((engaged / sessions) * 100, 1) if sessions else 0,
            "conversions": totals.get("conversions") or 0,
            "revenue": totals.get("revenue") or 0,
            "views": totals.get("views") or 0,
        },
    })
