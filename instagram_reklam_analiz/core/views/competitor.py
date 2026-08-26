from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum, Avg, Q
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST
from django.utils import timezone

from core.models import Ad, AdMetricHistory, Platform, PlatformAccount, Creative
from core.services.competitor_live_sync import SUPPORTED_META_PLATFORMS


def _ad_to_json(ad):
    metrics = ad.metric_history.all().order_by('-date').first()
    return {
        "id": ad.id,
        "name": ad.name or ad.headline or f"Rakip Reklam #{ad.id}",
        "platform": ad.platform_account.platform.code if ad.platform_account and ad.platform_account.platform else "unknown",
        "platform_name": ad.platform_account.platform.name if ad.platform_account and ad.platform_account.platform else "Platform yok",
        "account_id": ad.platform_account_id,
        "account_name": ad.platform_account.account_name if ad.platform_account else "Rakip hesap",
        "status": ad.status,
        "headline": ad.headline,
        "primary_text": ad.primary_text,
        "description": ad.description,
        "preview_image_url": ad.preview_image_url or (ad.creative.thumbnail_url if ad.creative else ""),
        "landing_url": ad.landing_url,
        "last_seen_at": ad.last_seen_at.isoformat() if ad.last_seen_at else None,
        "impressions": metrics.impressions if metrics else 0,
        "clicks": metrics.clicks if metrics else 0,
        "spend": float(metrics.spend) if metrics else 0,
        "ctr": float(metrics.ctr) if metrics else 0,
        "reach": metrics.reach if metrics else 0,
    }


@login_required
def rakip_analiz(request):
    qs = Ad.objects.filter(user=request.user, source_type="COMPETITOR", platform_account__platform__code__in=SUPPORTED_META_PLATFORMS).select_related("platform_account", "platform_account__platform", "creative")
    stats = qs.aggregate(total=Count("id"), active=Count("id", filter=Q(status="ACTIVE")))
    platforms = Platform.objects.filter(is_active=True).order_by("name")
    context = {
        "competitor_ads": qs.order_by("-last_seen_at", "-created_at")[:100],
        "competitors": PlatformAccount.objects.filter(user=request.user, platform__code__in=SUPPORTED_META_PLATFORMS, ads_v2__source_type="COMPETITOR").distinct(),
        "platforms": platforms,
        "total_competitor_ads": stats.get("total") or 0,
        "active_competitor_ads": stats.get("active") or 0,
        "v2_only": True,
    }
    return render(request, "rakip/rakip_analiz.html", context)


@login_required
def rakip_reklam_raporu(request):
    ads = Ad.objects.filter(user=request.user, source_type="COMPETITOR", platform_account__platform__code__in=SUPPORTED_META_PLATFORMS).select_related("platform_account", "platform_account__platform", "creative").order_by("-last_seen_at", "-created_at")
    return render(request, "rakip/rakip_reklam_raporu.html", {"reklamlar": ads, "toplam_reklam": ads.count(), "v2_only": True})


@login_required
def api_competitors(request):
    accounts = PlatformAccount.objects.filter(user=request.user, platform__code__in=SUPPORTED_META_PLATFORMS, ads_v2__source_type="COMPETITOR").select_related("platform").distinct().order_by("platform__name", "account_name")
    data = []
    for acc in accounts:
        data.append({
            "id": acc.id,
            "name": acc.account_name or acc.account_id,
            "platform": acc.platform.code,
            "platform_name": acc.platform.name,
            "ad_count": Ad.objects.filter(user=request.user, source_type="COMPETITOR", platform_account=acc).count(),
            "is_active": acc.is_active,
        })
    return JsonResponse({"success": True, "competitors": data})


@login_required
def api_competitors_by_platform(request, platform_code):
    if platform_code not in SUPPORTED_META_PLATFORMS:
        return JsonResponse({"success": True, "competitors": []})
    accounts = PlatformAccount.objects.filter(user=request.user, platform__code=platform_code, ads_v2__source_type="COMPETITOR").select_related("platform").distinct()
    return JsonResponse({"success": True, "competitors": [{"id": a.id, "name": a.account_name or a.account_id, "platform": a.platform.code} for a in accounts]})


@login_required
def search_instagram_user(request):
    q = request.GET.get("q", "").strip()
    return JsonResponse({"success": True, "results": [] if not q else [{"username": q.lstrip('@'), "name": q.lstrip('@'), "platform": "instagram"}]})


@login_required
@require_POST
def add_competitor(request):
    platform_code = request.POST.get("platform") or request.POST.get("platform_code") or "instagram"
    if platform_code not in SUPPORTED_META_PLATFORMS:
        return JsonResponse({"success": False, "message": "Bu platform icin canli rakip reklam cekimi desteklenmiyor."}, status=400)
    username = (request.POST.get("username") or request.POST.get("platform_identifier") or request.POST.get("name") or "").strip().lstrip('@')
    display_name = request.POST.get("name") or username or "Rakip hesap"
    platform, _ = Platform.objects.get_or_create(code=platform_code, defaults={"name": platform_code.title(), "is_active": True})
    account, _ = PlatformAccount.objects.update_or_create(
        user=request.user,
        platform=platform,
        account_id=f"competitor_{platform_code}_{username or timezone.now().timestamp()}",
        defaults={"account_name": display_name, "access_token": "", "is_active": True, "extra_data": {"source_type": "COMPETITOR", "username": username}},
    )
    messages.success(request, "Rakip hesabı V2 yapıda eklendi. Reklamlar Ad(source_type=COMPETITOR) olarak tutulacak.")
    return JsonResponse({"success": True, "id": account.id, "message": "Rakip hesabı eklendi."})


@login_required
@require_POST
def delete_competitor(request, competitor_id):
    account = PlatformAccount.objects.filter(id=competitor_id, user=request.user).first()
    if not account:
        return JsonResponse({"success": False, "message": "Kayıt bulunamadı."}, status=404)
    Ad.objects.filter(user=request.user, source_type="COMPETITOR", platform_account=account).update(is_active=False, status="ARCHIVED")
    account.is_active = False
    account.save(update_fields=["is_active"])
    return JsonResponse({"success": True, "message": "Rakip hesabı pasife alındı."})


@login_required
def get_competitor_ads_api(request, competitor_id):
    ads = Ad.objects.filter(user=request.user, source_type="COMPETITOR", platform_account_id=competitor_id, platform_account__platform__code__in=SUPPORTED_META_PLATFORMS).select_related("platform_account", "platform_account__platform", "creative").prefetch_related("metric_history").order_by("-last_seen_at", "-created_at")
    return JsonResponse({"success": True, "ads": [_ad_to_json(a) for a in ads]})


@login_required
def api_competitor_detail(request, competitor_id):
    acc = PlatformAccount.objects.filter(id=competitor_id, user=request.user).select_related("platform").first()
    if not acc:
        return JsonResponse({"success": False, "message": "Kayıt bulunamadı."}, status=404)
    qs = Ad.objects.filter(user=request.user, source_type="COMPETITOR", platform_account=acc)
    return JsonResponse({"success": True, "competitor": {"id": acc.id, "name": acc.account_name or acc.account_id, "platform": acc.platform.code, "ad_count": qs.count()}})
