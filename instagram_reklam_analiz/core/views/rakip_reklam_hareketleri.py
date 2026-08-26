# core/views/rakip_reklam_hareketleri.py
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Avg
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from core.models import Ad, AdMetricHistory, Competitor, Platform
from core.services.agency_scope import get_agency_scope, scope_client_queryset, scope_queryset
from core.services.cache_service import CacheService
from core.services.competitor_live_sync import SUPPORTED_META_PLATFORMS


COMPETITOR_MOVEMENTS_CACHE_TIMEOUT = 300


def _platform_code(platform):
    if not platform:
        return "other"
    return getattr(platform, "code", None) or getattr(platform, "slug", None) or platform.name.lower().replace(" ", "_")


def _date_bounds(date_range, start_date=None, end_date=None):
    today = timezone.now().date()

    if date_range == "daily":
        return today, today

    if date_range == "monthly":
        return today - timedelta(days=30), today

    if date_range == "quarterly":
        return today - timedelta(days=90), today

    if date_range == "custom" and start_date and end_date:
        try:
            from datetime import datetime
            s = datetime.strptime(start_date, "%Y-%m-%d").date()
            e = datetime.strptime(end_date, "%Y-%m-%d").date()
            return s, e
        except Exception:
            return today - timedelta(days=7), today

    return today - timedelta(days=7), today


def _safe_float(v):
    try:
        return float(v or 0)
    except Exception:
        return 0


def _change_percent(current, previous):
    current = _safe_float(current)
    previous = _safe_float(previous)

    if previous == 0:
        return 0 if current == 0 else 100

    return round(((current - previous) / previous) * 100, 1)


def _ad_short_payload(ad):
    raw = ad.raw_data or {}
    platform = ad.competitor.platform if getattr(ad, "competitor_id", None) and ad.competitor else getattr(ad, "platform", None)

    latest = (
        AdMetricHistory.objects
        .filter(ad=ad)
        .order_by("-date")
        .first()
    )

    impressions = latest.impressions if latest else raw.get("impressions", 0)
    clicks = latest.clicks if latest else raw.get("clicks", 0)
    engagement = latest.engagement if latest else raw.get("engagement", 0)
    ctr = latest.ctr if latest else raw.get("ctr", 0)

    score = raw.get("performance_score")
    if not score:
        ctr_score = min(100, _safe_float(ctr) * 12)
        engagement_rate = _safe_float(raw.get("engagement_rate"))
        eng_score = min(100, engagement_rate * 12)
        score = round((ctr_score + eng_score) / 2) if (ctr_score or eng_score) else 0

    return {
        "id": ad.id,
        "name": ad.name or "Rakip Reklam",
        "platform": _platform_code(platform),
        "created_at": ad.created_at.strftime("%d.%m.%Y") if ad.created_at else "",
        "media_type": raw.get("media_type") or (ad.ad_format or "image"),
        "performance_score": score,
        "impressions": impressions,
        "clicks": clicks,
        "engagement": engagement,
    }


def _selected_ad_payload(ad):
    p = _ad_short_payload(ad)
    raw = ad.raw_data or {}
    p.update({
        "budget": raw.get("budget", 0),
        "spend": raw.get("spend", 0),
        "ctr": raw.get("ctr", 0),
    })
    return p


@login_required
def rakip_reklam_hareketleri(request):
    """
    Rakip Reklam Hareketleri sayfası.
    Rakip reklamların tarih bazlı AdMetricHistory hareketlerini gösterir.
    """
    agency_scope = get_agency_scope(request)
    version = CacheService.get_version("competitor_movements_page", request.user.id)
    cached_context = CacheService.get(
        "competitor_movements_page", "user", request.user.id, "scope", agency_scope.cache_key, version=version
    )
    if cached_context is not None and cached_context.get("supported_live_only"):
        return render(request, "rakip/rakip_reklam_hareketleri.html", {**cached_context, "agency_scope": agency_scope})

    platforms = list(Platform.objects.filter(is_active=True, code__in=SUPPORTED_META_PLATFORMS).order_by("name"))
    rakip_accounts = list(
        scope_client_queryset(
            request,
            Competitor.objects.filter(platform__code__in=SUPPORTED_META_PLATFORMS),
        )
        .select_related("platform", "platform_account")
        .order_by("platform__name", "name")
    )
    context = {
        "platforms": platforms,
        "rakip_accounts": rakip_accounts,
        "agency_scope": agency_scope,
        "supported_live_only": True,
    }
    CacheService.set(
        "competitor_movements_page",
        "user",
        request.user.id,
        "scope",
        agency_scope.cache_key,
        value={key: value for key, value in context.items() if key != "agency_scope"},
        timeout=COMPETITOR_MOVEMENTS_CACHE_TIMEOUT,
        version=version,
    )

    return render(
        request,
        "rakip/rakip_reklam_hareketleri.html",
        context,
    )


@login_required
def api_rakip_reklam_hareketleri(request):
    agency_scope = get_agency_scope(request)
    platform_code = request.GET.get("platform") or ""
    if platform_code and platform_code not in SUPPORTED_META_PLATFORMS:
        platform_code = ""
    rakip_id = request.GET.get("rakip_id") or ""
    reklam_id = request.GET.get("reklam_id") or ""
    date_range = request.GET.get("date_range") or "weekly"
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

    start, end = _date_bounds(date_range, start_date, end_date)
    version = CacheService.get_version("competitor_movements", request.user.id)
    cache_key_parts = (
        "user",
        request.user.id,
        "scope",
        agency_scope.cache_key,
        "platform",
        platform_code or "all",
        "rakip",
        rakip_id or "all",
        "reklam",
        reklam_id or "auto",
        "range",
        date_range,
        "start",
        start.isoformat(),
        "end",
        end.isoformat(),
    )
    cached = CacheService.get("competitor_movements", *cache_key_parts, version=version)
    if cached is not None:
        return JsonResponse(cached)

    allowed_competitors = scope_client_queryset(
        request,
        Competitor.objects.filter(platform__code__in=SUPPORTED_META_PLATFORMS),
    )
    ads = (
        Ad.objects.filter(
            source_type="COMPETITOR",
            competitor__in=allowed_competitors,
            competitor__platform__code__in=SUPPORTED_META_PLATFORMS,
        )
        .select_related("competitor", "competitor__platform")
        .order_by("-created_at")
    )

    if platform_code:
        ads = ads.filter(competitor__platform__code=platform_code)

    if rakip_id:
        ads = ads.filter(competitor_id=rakip_id)

    reklamlar = [_ad_short_payload(ad) for ad in ads]

    selected_ad = None
    if reklam_id:
        selected_ad = ads.filter(id=reklam_id).first()

    if selected_ad is None:
        selected_ad = ads.first()

    if selected_ad is None:
        response_payload = {
            "success": True,
            "reklamlar": [],
            "selected_reklam": None,
            "chart_labels": [],
            "chart_impressions": [],
            "chart_clicks": [],
            "chart_spend": [],
            "chart_budget": [],
            "chart_ctr": [],
            "chart_engagement": [],
            "total_impressions": 0,
            "total_clicks": 0,
            "total_spend": 0,
            "total_engagement": 0,
            "avg_ctr": 0,
            "impressions_change": 0,
            "clicks_change": 0,
            "spend_change": 0,
        }
        CacheService.set(
            "competitor_movements",
            *cache_key_parts,
            value=response_payload,
            timeout=COMPETITOR_MOVEMENTS_CACHE_TIMEOUT,
            version=version,
        )
        return JsonResponse(response_payload)

    history = (
        AdMetricHistory.objects
        .filter(ad=selected_ad, date__gte=start, date__lte=end)
        .order_by("date")
    )

    # Eğer seçilen aralıkta veri yoksa en son kayıtları göster.
    if not history.exists():
        history = (
            AdMetricHistory.objects
            .filter(ad=selected_ad)
            .order_by("date")
        )

    labels = []
    impressions = []
    clicks = []
    spend = []
    budget = []
    ctr = []
    engagement = []

    raw = selected_ad.raw_data or {}
    raw_budget = _safe_float(raw.get("budget"))

    for h in history:
        labels.append(h.date.isoformat())
        impressions.append(int(h.impressions or 0))
        clicks.append(int(h.clicks or 0))
        spend.append(float(h.spend or 0))
        budget.append(raw_budget)
        ctr.append(float(h.ctr or 0))
        engagement.append(int(h.engagement or 0))

    total_impressions = sum(impressions)
    total_clicks = sum(clicks)
    total_spend = round(sum(spend), 2)
    total_engagement = sum(engagement)
    avg_ctr = round((total_clicks / total_impressions) * 100, 2) if total_impressions else 0

    midpoint = max(len(labels) // 2, 1)
    prev_impressions = sum(impressions[:midpoint])
    cur_impressions = sum(impressions[midpoint:])
    prev_clicks = sum(clicks[:midpoint])
    cur_clicks = sum(clicks[midpoint:])
    prev_spend = sum(spend[:midpoint])
    cur_spend = sum(spend[midpoint:])

    response_payload = {
        "success": True,
        "reklamlar": reklamlar,
        "selected_reklam": _selected_ad_payload(selected_ad),
        "chart_labels": labels,
        "chart_impressions": impressions,
        "chart_clicks": clicks,
        "chart_spend": spend,
        "chart_budget": budget,
        "chart_ctr": ctr,
        "chart_engagement": engagement,
        "total_impressions": total_impressions,
        "total_clicks": total_clicks,
        "total_spend": total_spend,
        "total_engagement": total_engagement,
        "avg_ctr": avg_ctr,
        "impressions_change": _change_percent(cur_impressions, prev_impressions),
        "clicks_change": _change_percent(cur_clicks, prev_clicks),
        "spend_change": _change_percent(cur_spend, prev_spend),
    }
    CacheService.set(
        "competitor_movements",
        *cache_key_parts,
        value=response_payload,
        timeout=COMPETITOR_MOVEMENTS_CACHE_TIMEOUT,
        version=version,
    )
    return JsonResponse(response_payload)
