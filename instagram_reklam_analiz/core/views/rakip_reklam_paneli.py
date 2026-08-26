from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from core.models import Ad, AdMetricHistory, Competitor
from core.services.cache_service import CacheService
from core.services.competitor_live_sync import CompetitorSyncError, sync_competitor_live
from core.services.agency_scope import get_agency_scope, scope_client_queryset


COMPETITOR_CACHE_TIMEOUT = 300


@login_required
def rakip_reklam_paneli(request):
    return render(request, "rakip/rakip_reklam_paneli.html", {"agency_scope": get_agency_scope(request)})


def _raw(ad):
    return ad.raw_data or {}


def _latest_metric(ad):
    return AdMetricHistory.objects.filter(ad=ad).order_by("-date").first()


def _metric_value(metrics, field, default=0):
    if not metrics:
        return default
    value = getattr(metrics, field, default)
    return value if value is not None else default


def _media_type(ad):
    raw = _raw(ad)
    ad_format = (getattr(ad, "ad_format", "") or raw.get("media_type") or "image").lower()
    if "video" in ad_format:
        return "video"
    if "reels" in ad_format:
        return "reels"
    if "carousel" in ad_format:
        return "carousel"
    return "image"


def _ad_payload(ad):
    raw = _raw(ad)
    metric = _latest_metric(ad)
    media_type = _media_type(ad)

    impressions = _metric_value(metric, "impressions", raw.get("impressions", 0))
    clicks = _metric_value(metric, "clicks", raw.get("clicks", 0))
    spend = float(_metric_value(metric, "spend", raw.get("spend", 0)) or 0)
    reach = _metric_value(metric, "reach", raw.get("reach", 0))
    conversions = _metric_value(metric, "conversions", raw.get("conversions", 0))
    engagement = _metric_value(metric, "engagement", raw.get("engagement", 0))

    ctr = float(_metric_value(metric, "ctr", raw.get("ctr", 0)) or 0)
    cpc = float(_metric_value(metric, "cpc", raw.get("cpc", 0)) or 0)
    cpm = float(_metric_value(metric, "cpm", raw.get("cpm", 0)) or 0)
    frequency = float(_metric_value(metric, "frequency", raw.get("frequency", 0)) or 0)
    engagement_rate = float(_metric_value(metric, "engagement_rate", raw.get("engagement_rate", 0)) or 0)

    if ctr == 0 and impressions:
        ctr = round((clicks / impressions) * 100, 2)
    if cpc == 0 and clicks:
        cpc = round(spend / clicks, 2)
    if cpm == 0 and impressions:
        cpm = round((spend / impressions) * 1000, 2)
    if frequency == 0 and reach:
        frequency = round(impressions / reach, 2)
    if engagement_rate == 0 and impressions:
        engagement_rate = round((engagement / impressions) * 100, 2)

    conversion_rate = float(raw.get("conversion_rate", 0) or 0)
    if conversion_rate == 0 and clicks:
        conversion_rate = round((float(conversions or 0) / clicks) * 100, 2)

    performance_score = raw.get("performance_score", 0) or 0
    if not performance_score and (impressions or clicks or engagement):
        ctr_score = min(100, ctr * 12)
        eng_score = min(100, engagement_rate * 12)
        conv_score = min(100, conversion_rate * 10)
        performance_score = round((ctr_score + eng_score + conv_score) / 3)

    return {
        "id": ad.id,
        "name": ad.name or "Rakip Reklam",
        "title": ad.headline or ad.name or "Rakip Reklam",
        "description": ad.description or ad.primary_text or raw.get("description", ""),
        "primary_text": ad.primary_text or "",
        "call_to_action": ad.call_to_action or "",
        "landing_url": ad.landing_url or raw.get("snapshot_url", ""),
        "platform_name": ad.competitor.platform.name if ad.competitor and ad.competitor.platform else "",
        "status": (ad.status or "ACTIVE").lower(),
        "media_type": media_type,
        "media_url": ad.preview_video_url if media_type in ["video", "reels"] else (ad.preview_image_url or raw.get("media_url", "")),
        "thumbnail_url": ad.preview_image_url or raw.get("thumbnail_url", ""),
        "created_time": ad.created_at.isoformat() if ad.created_at else None,
        "first_seen_at": ad.first_seen_at.isoformat() if ad.first_seen_at else None,
        "last_seen_at": ad.last_seen_at.isoformat() if ad.last_seen_at else None,
        "has_live_metrics": bool(metric and (metric.impressions or metric.spend)),
        "impressions": impressions,
        "clicks": clicks,
        "ctr": ctr,
        "spend": spend,
        "budget": float(raw.get("budget", 0) or 0),
        "budget_usage_percent": float(raw.get("budget_usage_percent", 0) or 0),
        "conversions": conversions,
        "conversion_rate": conversion_rate,
        "cpc": cpc,
        "cpm": cpm,
        "roi": float(raw.get("roi", 0) or raw.get("roas", 0) or 0),
        "reach": reach,
        "frequency": frequency,
        "engagement": engagement,
        "engagement_rate": engagement_rate,
        "likes": _metric_value(metric, "likes", raw.get("likes", 0)),
        "comments": _metric_value(metric, "comments", raw.get("comments", 0)),
        "shares": _metric_value(metric, "shares", raw.get("shares", 0)),
        "saves": _metric_value(metric, "saves", raw.get("saves", 0)),
        "video_views": _metric_value(metric, "video_views", raw.get("video_views", 0)),
        "video_completion_rate": raw.get("video_completion_rate", 0),
        "performance_score": performance_score,
        "hourly_engagement": raw.get("hourly_engagement", []),
        "peak_hours": raw.get("peak_hours", []),
        "age_distribution": raw.get("age_distribution", {}),
        "gender_split": raw.get("gender_split", {}),
        "city_distribution": raw.get("city_distribution", {}),
        "device_split": raw.get("device_split", {}),
    }


@login_required
def api_rakip_reklamlar(request, competitor_id):
    agency_scope = get_agency_scope(request)
    competitor = get_object_or_404(scope_client_queryset(request, Competitor.objects.all()), id=competitor_id)
    version = CacheService.get_version("competitor_ads", request.user.id, competitor.id)
    cache_key_parts = ("user", request.user.id, "scope", agency_scope.cache_key, "competitor", competitor.id)
    cached = CacheService.get("competitor_ads", *cache_key_parts, version=version)
    if cached is not None:
        return JsonResponse(cached)

    ads = (
        Ad.objects
        .filter(source_type="COMPETITOR", competitor=competitor)
        .select_related("creative", "competitor")
        .order_by("-last_seen_at", "-created_at")
    )
    payload = [_ad_payload(ad) for ad in ads]
    response_payload = {"success": True, "ads": payload, "count": len(payload)}
    CacheService.set(
        "competitor_ads",
        *cache_key_parts,
        value=response_payload,
        timeout=COMPETITOR_CACHE_TIMEOUT,
        version=version,
    )
    return JsonResponse(response_payload)


@login_required
@require_http_methods(["POST"])
def api_rakip_reklam_sync(request, competitor_id):
    competitor = get_object_or_404(scope_client_queryset(request, Competitor.objects.all()), id=competitor_id)
    try:
        result = sync_competitor_live(competitor)
    except CompetitorSyncError as exc:
        total = Ad.objects.filter(source_type="COMPETITOR", competitor=competitor).count()
        return JsonResponse({
            "success": False,
            "created": 0,
            "updated": 0,
            "total": total,
            "message": str(exc),
        }, status=400)

    CacheService.bump_version("competitors", request.user.id)
    CacheService.bump_version("competitor_ads", request.user.id, competitor.id)
    CacheService.bump_version("competitor_movements", request.user.id)
    CacheService.bump_version("competitor_intelligence", request.user.id)
    return JsonResponse({
        "success": True,
        "created": result["created"],
        "updated": result["updated"],
        "total": result["total"],
        "fetched": result["fetched"],
        "provider": result["provider"],
        "message": f"{result['fetched']} kayit cekildi, {result['created']} yeni reklam yazildi, {result['updated']} reklam guncellendi.",
    })
