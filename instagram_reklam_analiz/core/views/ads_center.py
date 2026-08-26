from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.utils import timezone

from core.models import Ad, AdMetricHistory, Platform, PlatformAccount
from core.services.agency_branding import get_report_branding
from core.services.agency_scope import get_agency_scope, platform_accounts_for_request, scope_queryset
from core.services.ad_budget import current_budget_for_ad


def _date_range_from_request(request):
    date_range = request.GET.get("date_range", "monthly")
    start_date_str = request.GET.get("start_date", "")
    end_date_str = request.GET.get("end_date", "")

    today = timezone.now().date()

    if date_range == "daily":
        return today - timedelta(days=1), today

    if date_range == "weekly":
        return today - timedelta(days=7), today

    if date_range == "monthly":
        return today - timedelta(days=30), today

    if date_range == "quarterly":
        return today - timedelta(days=90), today

    if date_range == "custom" and start_date_str and end_date_str:
        try:
            return (
                datetime.strptime(start_date_str, "%Y-%m-%d").date(),
                datetime.strptime(end_date_str, "%Y-%m-%d").date(),
            )
        except ValueError:
            return today - timedelta(days=30), today

    return today - timedelta(days=30), today


def _change_percent(series):
    if len(series) >= 2 and series[0] != 0:
        return round(((series[-1] - series[0]) / abs(series[0])) * 100, 1)
    return 0


def _calculate_performance_score(metric):
    if not metric:
        return 0

    score = 0

    if metric.ctr >= 2:
        score += 35
    elif metric.ctr >= 1:
        score += 20
    else:
        score += 8

    if metric.engagement_rate >= 3:
        score += 35
    elif metric.engagement_rate >= 1:
        score += 20
    else:
        score += 8

    if metric.conversions > 0:
        score += 30
    else:
        score += 10

    return min(score, 100)


def _get_platform_code(ad):
    if ad.platform_account and ad.platform_account.platform:
        platform = ad.platform_account.platform
        return getattr(platform, "code", None) or getattr(platform, "name", "")
    return ""


def _get_ad_name(ad):
    return ad.name or ad.headline or f"Ad #{ad.id}"


@login_required
def ads_center(request):
    """
    Ads Center ana ekranı.
    Kendi reklamlarını yeni V2 Ad / AdMetricHistory yapısından okur.
    """
    user = request.user
    agency_scope = get_agency_scope(request)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        platform_code = request.GET.get("platform", "")
        account_id = request.GET.get("hesap", "")
        selected_ad_id = (
            request.GET.get("reklam_id")
            or request.GET.get("ad_id")
            or request.GET.get("open_ad")
            or ""
        )

        start_date, end_date = _date_range_from_request(request)

        ads = scope_queryset(
            request,
            Ad.objects.filter(source_type="OWN"),
        )
        ads = (
            ads
            .select_related(
                "platform_account",
                "platform_account__platform",
                "campaign",
                "ad_group",
                "creative",
            )
            .distinct()
        )

        if platform_code:
            ads = ads.filter(platform_account__platform__code=platform_code)

        if account_id:
            ads = ads.filter(platform_account_id=account_id)

        ads = ads.order_by("-created_at")

        ad_list_data = []

        for ad in ads:
            latest_metric = ad.metric_history.order_by("-date").first()
            score = _calculate_performance_score(latest_metric)

            ad_list_data.append({
                "id": ad.id,
                "name": _get_ad_name(ad),
                "platform": _get_platform_code(ad),
                "platform_icon": _get_platform_code(ad),
                "performance_score": score,
                "active": False,
            })

        selected_ad = None

        if selected_ad_id:
            try:
                selected_ad = ads.get(id=selected_ad_id)
            except Ad.DoesNotExist:
                selected_ad = ads.first()
        else:
            selected_ad = ads.first()

        chart_labels = []
        chart_impressions = []
        chart_clicks = []
        chart_spend = []
        chart_budget = []
        chart_ctr = []
        chart_engagement = []

        if selected_ad:
            history = (
                AdMetricHistory.objects
                .filter(
                    ad=selected_ad,
                    date__gte=start_date,
                    date__lte=end_date,
                )
                .order_by("date")
            )

            daily_data = {}

            for h in history:
                date_key = h.date.isoformat()

                if date_key not in daily_data:
                    daily_data[date_key] = {
                        "impressions": 0,
                        "clicks": 0,
                        "spend": 0.0,
                        "budget": float(current_budget_for_ad(selected_ad)[0]),
                        "ctr_total": 0.0,
                        "ctr_count": 0,
                        "engagement": 0,
                    }

                daily_data[date_key]["impressions"] += h.impressions or 0
                daily_data[date_key]["clicks"] += h.clicks or 0
                daily_data[date_key]["spend"] += float(h.spend or 0)
                daily_data[date_key]["engagement"] += h.engagement or 0

                if h.ctr:
                    daily_data[date_key]["ctr_total"] += float(h.ctr)
                    daily_data[date_key]["ctr_count"] += 1

            sorted_dates = sorted(daily_data.keys())

            chart_labels = sorted_dates
            chart_impressions = [daily_data[d]["impressions"] for d in sorted_dates]
            chart_clicks = [daily_data[d]["clicks"] for d in sorted_dates]
            chart_spend = [round(daily_data[d]["spend"], 2) for d in sorted_dates]
            chart_budget = [daily_data[d]["budget"] for d in sorted_dates]
            chart_ctr = [
                round(daily_data[d]["ctr_total"] / daily_data[d]["ctr_count"], 2)
                if daily_data[d]["ctr_count"]
                else 0
                for d in sorted_dates
            ]
            chart_engagement = [daily_data[d]["engagement"] for d in sorted_dates]

        total_impressions = sum(chart_impressions)
        total_clicks = sum(chart_clicks)
        total_spend = sum(chart_spend)
        total_engagement = sum(chart_engagement)
        avg_ctr = round((total_clicks / total_impressions) * 100, 2) if total_impressions else 0

        selected_ad_data = None

        if selected_ad:
            latest_metric = selected_ad.metric_history.order_by("-date").first()

            selected_ad_data = {
                "id": selected_ad.id,
                "name": _get_ad_name(selected_ad),
                "platform": _get_platform_code(selected_ad),
                "created_at": selected_ad.created_at.strftime("%d.%m.%Y"),
                "media_type": selected_ad.ad_format or (
                    selected_ad.creative.creative_type if selected_ad.creative else ""
                ),
                "performance_score": _calculate_performance_score(latest_metric),
                "budget": float(
                    selected_ad.campaign.daily_budget
                    if selected_ad.campaign and selected_ad.campaign.daily_budget
                    else 0
                ),
                "spend": float(latest_metric.spend or 0) if latest_metric else 0,
            }

        return JsonResponse({
            "success": True,

            # Eski template bozulmasın diye reklamlar ismini koruyoruz.
            "reklamlar": ad_list_data,
            "selected_reklam": selected_ad_data,

            # Yeni isimler.
            "ads": ad_list_data,
            "selected_ad": selected_ad_data,

            "chart_labels": chart_labels,
            "chart_impressions": chart_impressions,
            "chart_clicks": chart_clicks,
            "chart_spend": chart_spend,
            "chart_budget": chart_budget,
            "chart_ctr": chart_ctr,
            "chart_engagement": chart_engagement,

            "total_impressions": total_impressions,
            "total_clicks": total_clicks,
            "total_spend": round(total_spend, 2),
            "total_engagement": total_engagement,
            "avg_ctr": avg_ctr,

            "impressions_change": _change_percent(chart_impressions),
            "clicks_change": _change_percent(chart_clicks),
            "spend_change": _change_percent(chart_spend),
        })

    platform_accounts = platform_accounts_for_request(request, active_only=True).select_related(
        "platform", "connection", "agency_client"
    )
    platforms = Platform.objects.filter(
        is_active=True,
        accounts__in=platform_accounts,
    ).distinct().order_by("name")

    report_branding = get_report_branding(user, agency_client=agency_scope.selected_client)
    report_logo_url = static("images/logo2.png")
    if agency_scope.selected_client and agency_scope.selected_client.logo:
        report_logo_url = agency_scope.selected_client.logo.url
    elif not agency_scope.selected_client and agency_scope.organization_ids:
        organization = agency_scope.clients[0].organization if agency_scope.clients else None
        if organization and organization.use_logo_on_reports and organization.logo:
            report_logo_url = organization.logo.url

    context = {
        "platforms": platforms,

        # Eski template uyumu.
        "all_platform_accounts": platform_accounts,

        # Yeni isim.
        "platform_accounts": platform_accounts,
        "agency_scope": agency_scope,
        "report_branding": report_branding,
        "report_logo_url": report_logo_url,
    }

    return render(request, "reklamlar/reklam_hareketleri.html", context)
