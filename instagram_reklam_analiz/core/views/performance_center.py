from datetime import timedelta
import json

from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.shortcuts import render
from django.utils import timezone

from core.models import AdMetricHistory, Platform, PlatformAccount
from core.services.agency_scope import get_agency_scope, platform_accounts_for_request, scope_queryset
from core.services.cache_service import CacheService
from core.services.performance_metrics import aggregate_metric_queryset


PERIODS = [7, 30, 90, 180]


def _metric_queryset(request, start_date, end_date, platform_code="", account_id=""):
    qs = AdMetricHistory.objects.filter(
        ad__source_type="OWN",
        date__gte=start_date,
        date__lte=end_date,
    ).select_related("ad", "ad__platform_account", "ad__platform_account__platform")
    qs = scope_queryset(
        request,
        qs,
        account_lookup="ad__platform_account",
        user_lookup="ad__user",
    )

    if platform_code:
        qs = qs.filter(ad__platform_account__platform__code=platform_code)

    if account_id:
        qs = qs.filter(ad__platform_account_id=account_id)

    return qs


def _float(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _period_card(days, summary):
    return {
        "days": days,
        "impressions": summary.get("impressions") or 0,
        "clicks": summary.get("clicks") or 0,
        "spend": summary.get("spend") or 0,
        "revenue": summary.get("conversion_value") or 0,
        "conversions": summary.get("conversions") or 0,
        "ctr": summary.get("ctr") or 0,
        "cpc": summary.get("cpc") or 0,
        "cpa": summary.get("cpa") or 0,
        "roas": summary.get("roas") or 0,
    }


def _platform_rows(request, today, days, platform_accounts, account_id=""):
    start = today - timedelta(days=days - 1)
    platform_map = {}
    for account in platform_accounts:
        if account.platform:
            platform_map[account.platform.code] = account.platform.name

    rows = []
    for code, name in sorted(platform_map.items(), key=lambda item: item[1].lower()):
        summary = aggregate_metric_queryset(_metric_queryset(request, start, today, code, account_id))
        rows.append(
            {
                "code": code,
                "name": name,
                "impressions": _float(summary.get("impressions")),
                "clicks": _float(summary.get("clicks")),
                "spend": _float(summary.get("spend")),
                "revenue": _float(summary.get("conversion_value")),
                "roas": round(_float(summary.get("roas")), 2),
                "ctr": round(_float(summary.get("ctr")), 2),
                "cpc": round(_float(summary.get("cpc")), 2),
                "cpa": round(_float(summary.get("cpa")), 2),
            }
        )
    return rows


@login_required
def performance_center(request):
    user = request.user
    agency_scope = get_agency_scope(request)
    today = timezone.localdate()
    platform_code = request.GET.get("platform", "").strip()
    account_id = request.GET.get("account", "").strip()
    version = CacheService.get_version("performance_center", user.id)
    cache_parts = ("user", user.id, "scope", agency_scope.cache_key, "platform", platform_code or "all", "account", account_id or "all", "day", today.isoformat())
    cached = CacheService.get("performance_center", *cache_parts, version=version)
    if cached is not None:
        cached = dict(cached)
        cached["agency_scope"] = agency_scope
        return render(request, "reports/performance_center.html", cached)

    platforms = list(Platform.objects.filter(is_active=True).order_by("name"))
    account_qs = (
        platform_accounts_for_request(request, active_only=True)
        .select_related("platform", "agency_client")
        .order_by("agency_client__name", "platform__name", "account_name", "account_id")
    )
    all_platform_accounts = list(account_qs)
    platform_accounts = account_qs
    if platform_code:
        platform_accounts = platform_accounts.filter(platform__code=platform_code)
    platform_accounts = list(platform_accounts)
    valid_account_ids = {str(account.id) for account in platform_accounts}
    if account_id and account_id not in valid_account_ids:
        account_id = ""

    account_options = [
        {
            "id": str(account.id),
            "platform_code": account.platform.code if account.platform else "",
            "label": f"{account.platform.name if account.platform else 'Platform'} - {account.account_name or account.account_id}",
        }
        for account in all_platform_accounts
    ]

    breakdown_accounts = all_platform_accounts
    if platform_code:
        breakdown_accounts = [account for account in breakdown_accounts if account.platform and account.platform.code == platform_code]
    if account_id:
        breakdown_accounts = [account for account in breakdown_accounts if str(account.id) == account_id]

    platform_breakdown = {
        str(days): _platform_rows(request, today, days, breakdown_accounts, account_id)
        for days in PERIODS
    }

    period_cards = []
    for days in PERIODS:
        start = today - timedelta(days=days - 1)
        summary = aggregate_metric_queryset(_metric_queryset(request, start, today, platform_code, account_id))
        period_cards.append(_period_card(days, summary))

    labels = []
    clicks_data = []
    impressions_data = []
    spend_data = []
    revenue_data = []
    roas_data = []

    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        summary = aggregate_metric_queryset(_metric_queryset(request, day, day, platform_code, account_id))
        labels.append(day.strftime("%d.%m"))
        clicks_data.append(_float(summary.get("clicks")))
        impressions_data.append(_float(summary.get("impressions")))
        spend_data.append(_float(summary.get("spend")))
        revenue_data.append(_float(summary.get("conversion_value")))
        roas_data.append(round(_float(summary.get("roas")), 2))

    latest_metric = (
        _metric_queryset(request, today - timedelta(days=179), today, platform_code, account_id)
        .aggregate(last_date=Max("date"))
        .get("last_date")
    )

    context = {
        "period_cards": period_cards,
        "agency_scope": agency_scope,
        "platforms": platforms,
        "platform_accounts": platform_accounts,
        "account_options": account_options,
        "platform_breakdown": platform_breakdown,
        "selected_platform": platform_code,
        "selected_account": account_id,
        "chart_labels_json": json.dumps(labels),
        "chart_clicks_json": json.dumps(clicks_data),
        "chart_impressions_json": json.dumps(impressions_data),
        "chart_spend_json": json.dumps(spend_data),
        "chart_revenue_json": json.dumps(revenue_data),
        "chart_roas_json": json.dumps(roas_data),
        "latest_metric": latest_metric,
        "empty": not any(card["impressions"] or card["clicks"] or card["spend"] for card in period_cards),
    }
    CacheService.set("performance_center", *cache_parts, value=context, timeout=180, version=version)
    return render(request, "reports/performance_center.html", context)
