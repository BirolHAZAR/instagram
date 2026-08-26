from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from core.decorators import api_subscription_required
from core.models import Ad, FeatureUsageLedger, Platform, PlatformAccount, PlatformSyncJob
from core.services.ad_ai_service import build_ad_detail, generate_ad_report, serialize_ad_report
from core.services.cache_service import CacheService
from core.services.agency_scope import get_agency_scope, platform_accounts_for_request, scope_queryset
from core.services.openai_usage import consume_openai_operation, refund_ai_tariff_credits
from core.tasks.ads_pipeline import sync_platform_account_ads
from core.tasks.admin_ops import generate_octo_tasks


ADS_PANEL_CACHE_TIMEOUT = 120


@login_required
def ads_panel(request):
    agency_scope = get_agency_scope(request)
    return render(request, "reklamlar/panel.html", {"agency_scope": agency_scope})


@login_required
@require_GET
def api_platform_accounts(request):
    user = request.user
    platform_code = request.GET.get("platform", "")
    agency_scope = get_agency_scope(request)
    version = CacheService.get_version("ads_panel_accounts", user.id)
    cache_key_parts = ("user", user.id, "agency_client", agency_scope.cache_key, "platform", platform_code or "all")
    cached = None if platform_code else CacheService.get("ads_panel_accounts", *cache_key_parts, version=version)
    if cached is not None:
        return JsonResponse(cached)

    data = []
    for platform in Platform.objects.filter(is_active=True).order_by("name"):
        if platform_code and getattr(platform, "code", "") != platform_code:
            continue
        accounts = platform_accounts_for_request(request, active_only=True).filter(
            platform=platform,
        ).select_related("platform", "connection")
        account_items = []
        for account in accounts:
            ad_count = Ad.objects.filter(platform_account=account, source_type="OWN").count()
            account_items.append({
                "id": account.id,
                "account_id": account.account_id,
                "account_name": account.account_name or account.account_id,
                "platform": getattr(platform, "code", platform.name),
                "platform_name": platform.name,
                "is_active": account.is_active,
                "last_sync": account.last_sync.isoformat() if account.last_sync else None,
                "ad_count": ad_count,
                "connection_status": account.connection.status if account.connection else "missing",
            })
        data.append({
            "id": platform.id,
            "code": getattr(platform, "code", platform.name),
            "name": platform.name,
            "accounts": account_items,
            "account_count": len(account_items),
        })

    payload = {"success": True, "platforms": data}
    if not platform_code:
        CacheService.set(
            "ads_panel_accounts",
            *cache_key_parts,
            value=payload,
            timeout=ADS_PANEL_CACHE_TIMEOUT,
            version=version,
        )
    return JsonResponse(payload)


@login_required
@require_GET
def api_ads_by_account(request):
    user = request.user
    account_id = request.GET.get("account_id")
    if not account_id:
        return JsonResponse({"success": False, "error": "account_id gerekli"}, status=400)

    account = get_object_or_404(platform_accounts_for_request(request, active_only=True), id=account_id)
    agency_scope = get_agency_scope(request)
    version = CacheService.get_version("ads_panel_account", user.id, account.id)
    cache_key_parts = ("user", user.id, "agency_client", agency_scope.cache_key, "account", account.id)
    cached = CacheService.get("ads_panel_ads", *cache_key_parts, version=version)
    if cached is not None:
        return JsonResponse(cached)

    ads = (
        scope_queryset(request, Ad.objects.filter(platform_account=account, source_type="OWN"))
        .select_related("campaign", "ad_group", "creative", "platform_account__platform")
        .order_by("-created_at")
    )
    data = []
    for ad in ads:
        latest = ad.metric_history.order_by("-date").first()
        data.append({
            "id": ad.id,
            "name": ad.name or ad.headline or f"Ad #{ad.id}",
            "platform": getattr(account.platform, "code", account.platform.name),
            "status": ad.status,
            "media_type": ad.ad_format or (ad.creative.creative_type if ad.creative else ""),
            "media_url": ad.preview_video_url or ad.preview_image_url or (ad.creative.video_url if ad.creative and ad.creative.video_url else ad.creative.image_url if ad.creative else ""),
            "thumbnail_url": ad.preview_image_url or (ad.creative.thumbnail_url if ad.creative else ""),
            "campaign": ad.campaign.name if ad.campaign else "-",
            "ad_group": ad.ad_group.name if ad.ad_group else "-",
            "headline": ad.headline or "",
            "primary_text": ad.primary_text or "",
            "preview_image_url": ad.preview_image_url or (ad.creative.image_url if ad.creative else ""),
            "preview_video_url": ad.preview_video_url or (ad.creative.video_url if ad.creative else ""),
            "impressions": latest.impressions if latest else 0,
            "clicks": latest.clicks if latest else 0,
            "spend": float(latest.spend) if latest else 0,
            "ctr": float(latest.ctr) if latest else 0,
            "cpc": float(latest.cpc) if latest else 0,
            "cpm": float(latest.cpm) if latest else 0,
            "conversions": float(latest.conversions) if latest else 0,
            "engagement": latest.engagement if latest else 0,
            "engagement_rate": float(latest.engagement_rate) if latest else 0,
            "created_at": ad.created_at.strftime("%d.%m.%Y"),
            "created_time": ad.created_at.isoformat(),
            "status_display": ad.get_status_display(),
        })

    payload = {
        "success": True,
        "account": {
            "id": account.id,
            "name": account.account_name or account.account_id,
            "platform": getattr(account.platform, "code", account.platform.name),
        },
        "ads": data,
        "reklamlar": data,
    }
    CacheService.set(
        "ads_panel_ads",
        *cache_key_parts,
        value=payload,
        timeout=ADS_PANEL_CACHE_TIMEOUT,
        version=version,
    )
    return JsonResponse(payload)


@login_required
@require_GET
def api_ad_detail(request, ad_id):
    ad = scope_queryset(
        request,
        Ad.objects.filter(source_type="OWN").select_related(
            "platform_account",
            "platform_account__platform",
            "campaign",
            "ad_group",
            "creative",
        ),
    ).filter(id=ad_id).first()
    if not ad:
        return JsonResponse({"success": False, "message": "Reklam bulunamadı."}, status=404)
    return JsonResponse({"success": True, "ad": build_ad_detail(ad)})


@login_required
@require_POST
def api_ad_rule_scan(request, ad_id):
    ad = scope_queryset(
        request,
        Ad.objects.filter(source_type="OWN").select_related("platform_account"),
    ).filter(id=ad_id).first()
    if not ad or not ad.platform_account_id:
        return JsonResponse({"success": False, "message": "Reklam veya bağlı hesap bulunamadı."}, status=404)

    task = generate_octo_tasks.apply_async(
        kwargs={
            "user_id": ad.user_id,
            "account_id": ad.platform_account_id,
            "trigger": "manual",
            "days": 7,
        },
        queue="ai",
    )
    return JsonResponse({
        "success": True,
        "status": "queued",
        "task_id": task.id,
        "message": "Kural taraması kuyruğa alındı.",
    })


@login_required
@require_POST
def api_ad_ai_report(request, ad_id, report_type):
    if report_type not in {"analysis", "recommendation"}:
        return JsonResponse({"success": False, "message": "Geçersiz rapor türü."}, status=400)
    ad = scope_queryset(
        request,
        Ad.objects.filter(source_type="OWN").select_related(
            "platform_account",
            "platform_account__platform",
            "campaign",
            "ad_group",
            "creative",
        ),
    ).filter(id=ad_id).first()
    if not ad:
        return JsonResponse({"success": False, "message": "Reklam bulunamadı."}, status=404)

    usage = None
    if not (request.user.is_staff or request.user.is_superuser):
        agency_scope = get_agency_scope(request)
        operation = (
            FeatureUsageLedger.OP_OPENAI_ANALYSIS
            if report_type == "analysis"
            else FeatureUsageLedger.OP_OPENAI_RECOMMENDATION
        )
        usage = consume_openai_operation(
            user=request.user,
            operation=operation,
            organization=agency_scope.selected_client.organization if agency_scope.selected_client else None,
            tariff_key=("ad-report-card-analysis" if report_type == "analysis" else "ad-report-card-recommendation"),
            credit_amount=3,
            reference=f"ads_panel.{report_type}.ad.{ad.id}",
            reason=f"Reklam AI {'analizi' if report_type == 'analysis' else 'önerisi'}",
            metadata={"ad_id": ad.id, "agency_client_id": ad.platform_account.agency_client_id if ad.platform_account else None},
        )
        if not usage.allowed:
            return JsonResponse({
                "success": False,
                "message": usage.reason,
                "code": usage.code,
                "limit": usage.limit,
                "used": usage.used,
                "remaining": usage.remaining,
            }, status=429 if "limit" in (usage.code or "") else 402)

    tariff_key = "ad-report-card-analysis" if report_type == "analysis" else "ad-report-card-recommendation"
    try:
        report = generate_ad_report(
            ad, request.user, report_type,
            organization=(agency_scope.selected_client.organization if usage is not None and agency_scope.selected_client else None),
        )
    except Exception as exc:
        if usage is not None:
            agency_scope = get_agency_scope(request)
            refund_ai_tariff_credits(
                user=request.user,
                organization=agency_scope.selected_client.organization if agency_scope.selected_client else None,
                tariff_key=tariff_key,
                reason=str(exc),
                reference=f"ads_panel.{report_type}.ad.{ad.id}",
            )
        return JsonResponse({"success": False, "message": str(exc)}, status=502)
    return JsonResponse({
        "success": True,
        "report": serialize_ad_report(report),
        "usage": {
            "used": usage.used + 1 if usage else None,
            "remaining": usage.remaining - 1 if usage and usage.remaining is not None else None,
        },
    })


@login_required
@api_subscription_required
@require_POST
def api_sync_account(request, account_id):
    account = get_object_or_404(platform_accounts_for_request(request, active_only=True), id=account_id)
    days_back = request.POST.get("days_back") or request.GET.get("days_back") or 30
    try:
        days_back = int(days_back)
    except ValueError:
        days_back = 30
    days_back = max(1, min(days_back, 365))

    job = PlatformSyncJob.objects.create(
        user=request.user,
        platform_account=account,
        days_back=days_back,
        status="pending",
        progress=0,
        message="Octo senkronizasyonu baslatiyor...",
    )

    CacheService.bump_version("ads_panel_accounts", request.user.id)
    CacheService.bump_version("ads_panel_account", request.user.id, account.id)
    CacheService.bump_version("dashboard", request.user.id)
    CacheService.bump_version("control_tower", request.user.id)
    CacheService.bump_version("reports_center", request.user.id)
    CacheService.bump_version("health_center", request.user.id)
    sync_platform_account_ads.delay(job.id)

    return JsonResponse({"success": True, "job_id": job.id, "message": "Octo reklamlari cekmeye basladi."})


@login_required
@require_GET
def api_sync_job_status(request, job_id):
    job = get_object_or_404(PlatformSyncJob, id=job_id, user=request.user)
    return JsonResponse({
        "success": True,
        "job": {
            "id": job.id,
            "status": job.status,
            "progress": job.progress,
            "message": job.message,
            "campaigns_count": job.campaigns_count,
            "adgroups_count": job.adgroups_count,
            "ads_count": job.ads_count,
            "creatives_count": job.creatives_count,
            "metrics_count": job.metrics_count,
            "days_back": job.days_back,
            "error_message": job.error_message,
            "result": job.result,
        },
    })
