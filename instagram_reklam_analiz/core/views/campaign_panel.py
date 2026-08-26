from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.decorators import api_subscription_required
from core.models import AICreditLedger, Campaign, FeatureUsageLedger, PlatformAccount, PlatformSyncJob
from core.services.campaign_panel_service import (
    build_campaign_ai_pdf_response,
    build_campaign_ai_report,
    build_campaign_detail,
    build_campaign_list,
    build_platform_account_payload,
    get_saved_campaign_ai_report,
    normalize_date_range,
)
from core.services.cache_service import CacheService
from core.services.agency_scope import get_agency_scope, platform_accounts_for_request, scope_queryset
from core.services.entitlements import consume_ai_credits, get_access_subscription, get_active_subscription, get_limit, is_unlimited
from core.services.openai_usage import consume_openai_operation, refund_ai_tariff_credits
from core.services.ai_credit_purchase import insufficient_credit_payload


CAMPAIGN_PANEL_CACHE_TIMEOUT = 120
CAMPAIGN_AI_REFERENCE_PREFIX = "campaign_panel.ai_report"

try:
    from core.tasks.ads_pipeline import sync_platform_account_ads
except Exception:
    sync_platform_account_ads = None


@login_required
def campaign_panel(request):
    # Sayfa ile AJAX isteklerinin ayni ajans musterisi kapsaminda kalmasi icin
    # query parametresini ilk sayfa isteginde isleyip oturuma yaziyoruz.
    agency_scope = get_agency_scope(request)
    return render(request, "reports/campaign_panel.html", {"agency_scope": agency_scope})


def _ai_limit_response(message, status, **extra):
    return JsonResponse({"success": False, "error": "ai_limit", "message": message, **extra}, status=status)


def _check_campaign_ai_access(request, report_type):
    if request.user.is_staff or request.user.is_superuser:
        return None

    agency_scope = get_agency_scope(request)
    organization = agency_scope.selected_client.organization if agency_scope.selected_client else None
    subscription = get_active_subscription(request.user, organization=organization)
    if not subscription and organization is None:
        subscription = get_access_subscription(request.user)
        if subscription and subscription.organization_id:
            organization = subscription.organization
    if not subscription:
        return _ai_limit_response("Bu AI ozelligi icin aktif paket gerekli.", 402, code="subscription_required")

    limit_key = "ai_recommendation" if report_type == "recommendation" else "ai_analysis"
    weekly_limit_key = "ai_recommendation_weekly" if report_type == "recommendation" else "ai_analysis_weekly"
    reference_prefix = f"{CAMPAIGN_AI_REFERENCE_PREFIX}.{report_type}"

    monthly_limit = get_limit(request.user, limit_key, organization=organization)
    if monthly_limit is not None and not is_unlimited(monthly_limit):
        today = timezone.localdate()
        month_start = today.replace(day=1)
        used_month = AICreditLedger.objects.filter(
            user=request.user,
            organization=organization,
            action=AICreditLedger.ACTION_CONSUME,
            reference__startswith=reference_prefix,
            created_at__date__gte=month_start,
        ).count()
        if used_month >= monthly_limit:
            label = "yorum/oneri" if report_type == "recommendation" else "analiz"
            return _ai_limit_response(
                f"Bu paket aylik {monthly_limit} AI {label} hakki iceriyor. Aylik limit doldu.",
                429,
                code="monthly_ai_limit_reached",
                limit=monthly_limit,
                used=used_month,
            )

    weekly_limit = get_limit(request.user, weekly_limit_key, organization=organization)
    if weekly_limit is not None and 0 < weekly_limit < 9999:
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
        used_week = AICreditLedger.objects.filter(
            user=request.user,
            organization=organization,
            action=AICreditLedger.ACTION_CONSUME,
            reference__startswith=reference_prefix,
            created_at__date__gte=week_start,
        ).count()
        if used_week >= weekly_limit:
            label = "yorum/oneri" if report_type == "recommendation" else "analiz"
            return _ai_limit_response(
                f"Bu paket haftalik {weekly_limit} AI {label} hakki iceriyor. Haftalik limit doldu.",
                429,
                code="weekly_ai_limit_reached",
                limit=weekly_limit,
                used=used_week,
            )

    result = consume_openai_operation(
        user=request.user,
        organization=organization,
        operation=(FeatureUsageLedger.OP_OPENAI_RECOMMENDATION if report_type == "recommendation" else FeatureUsageLedger.OP_OPENAI_ANALYSIS),
        tariff_key=("campaign-panel-recommendation" if report_type == "recommendation" else "campaign-panel-analysis"),
        credit_amount=3,
        reason="Kampanya AI yorum/oneri" if report_type == "recommendation" else "Kampanya AI analizi",
        reference=f"{reference_prefix}.campaign",
    )
    if not result.allowed:
        if result.code == "insufficient_ai_credits":
            return JsonResponse(insufficient_credit_payload(
                message=result.reason,
                required_credits=result.used,
                available_credits=result.limit,
            ), status=402)
        return _ai_limit_response(
            result.reason,
            402,
            code=result.code or "ai_usage_not_allowed",
        )
    return None


@login_required
@require_GET
def api_campaign_panel_accounts(request):
    platform_code = request.GET.get("platform", "")
    agency_scope = get_agency_scope(request)
    version = CacheService.get_version("campaign_panel_accounts", request.user.id)
    cache_key_parts = ("user", request.user.id, "agency_client", agency_scope.cache_key, "platform", platform_code or "all")
    cached = CacheService.get("campaign_panel_accounts", *cache_key_parts, version=version)
    if cached is not None:
        return JsonResponse(cached)

    payload = {
        "success": True,
        "platforms": build_platform_account_payload(
            request.user,
            platform_code=platform_code,
            accounts_queryset=platform_accounts_for_request(request),
        ),
    }
    CacheService.set(
        "campaign_panel_accounts",
        *cache_key_parts,
        value=payload,
        timeout=CAMPAIGN_PANEL_CACHE_TIMEOUT,
        version=version,
    )
    return JsonResponse({
        **payload,
    })


@login_required
@require_GET
def api_campaigns_by_account(request):
    account_id = request.GET.get("account_id")
    if not account_id:
        return JsonResponse({"success": False, "error": "account_id gerekli"}, status=400)

    account = get_object_or_404(platform_accounts_for_request(request, active_only=True), id=account_id)
    start_date, end_date = normalize_date_range(request)
    version = CacheService.get_version("campaign_panel_account", request.user.id, account.id)
    cache_key_parts = (
        "user",
        request.user.id,
        "account",
        account.id,
        "from",
        start_date.isoformat() if start_date else "all",
        "to",
        end_date.isoformat() if end_date else "all",
    )
    cached = CacheService.get("campaign_panel_campaigns", *cache_key_parts, version=version)
    if cached is not None:
        return JsonResponse(cached)

    campaigns = build_campaign_list(request.user, account, start_date=start_date, end_date=end_date)

    payload = {
        "success": True,
        "account": {
            "id": account.id,
            "name": account.account_name or account.account_id,
            "platform": getattr(account.platform, "code", account.platform.name),
            "platform_name": account.platform.name,
        },
        "date_range": {
            "date_from": start_date.isoformat() if start_date else "all",
            "date_to": end_date.isoformat() if end_date else "all",
        },
        "campaigns": campaigns,
    }
    CacheService.set(
        "campaign_panel_campaigns",
        *cache_key_parts,
        value=payload,
        timeout=CAMPAIGN_PANEL_CACHE_TIMEOUT,
        version=version,
    )
    return JsonResponse(payload)


@login_required
@require_GET
def api_campaign_detail(request, campaign_id):
    campaign = get_object_or_404(
        scope_queryset(request, Campaign.objects.select_related("platform_account", "platform_account__platform")),
        id=campaign_id,
    )
    start_date, end_date = normalize_date_range(request)
    account_id = campaign.platform_account_id or "none"
    version = CacheService.get_version("campaign_panel_account", request.user.id, account_id)
    cache_key_parts = (
        "user",
        request.user.id,
        "campaign",
        campaign.id,
        "from",
        start_date.isoformat() if start_date else "all",
        "to",
        end_date.isoformat() if end_date else "all",
    )
    cached = CacheService.get("campaign_panel_detail", *cache_key_parts, version=version)
    if cached is not None:
        return JsonResponse(cached)

    payload = {
        "success": True,
        "campaign": build_campaign_detail(request.user, campaign, start_date=start_date, end_date=end_date),
    }
    CacheService.set(
        "campaign_panel_detail",
        *cache_key_parts,
        value=payload,
        timeout=CAMPAIGN_PANEL_CACHE_TIMEOUT,
        version=version,
    )
    return JsonResponse(payload)


@login_required
@require_GET
def api_campaign_ai_report(request, campaign_id):
    charged_tariff_key = ""
    try:
        campaign = get_object_or_404(
            scope_queryset(request, Campaign.objects.select_related("platform_account", "platform_account__platform")),
            id=campaign_id,
        )
        report_type = request.GET.get("type") or "analysis"
        if report_type not in {"analysis", "recommendation"}:
            report_type = "analysis"
        refresh = request.GET.get("refresh") in {"1", "true", "yes"}
        if not refresh:
            saved_report = get_saved_campaign_ai_report(request.user, campaign, report_type=report_type)
            if saved_report is not None:
                return JsonResponse(saved_report)
        access_error = _check_campaign_ai_access(request, report_type)
        if access_error is not None:
            return access_error
        if not (request.user.is_staff or request.user.is_superuser):
            charged_tariff_key = "campaign-panel-recommendation" if report_type == "recommendation" else "campaign-panel-analysis"
        start_date, end_date = normalize_date_range(request)
        agency_scope = get_agency_scope(request)
        organization = agency_scope.selected_client.organization if agency_scope.selected_client else None
        report = build_campaign_ai_report(
            request.user,
            campaign,
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            persist=True,
            organization=organization,
        )
        return JsonResponse(report)
    except Exception as exc:
        if charged_tariff_key:
            refund_ai_tariff_credits(
                user=request.user, tariff_key=charged_tariff_key, reason=str(exc),
                organization=locals().get("organization"),
                reference=f"{CAMPAIGN_AI_REFERENCE_PREFIX}.{report_type}.campaign",
            )
        return JsonResponse({"success": False, "error": str(exc) or "AI raporu üretilemedi."}, status=500)


@login_required
@require_GET
def api_campaign_ai_pdf(request, campaign_id):
    try:
        campaign = get_object_or_404(
            scope_queryset(request, Campaign.objects.select_related("platform_account", "platform_account__platform")),
            id=campaign_id,
        )
        report_type = request.GET.get("type") or "analysis"
        if report_type not in {"analysis", "recommendation"}:
            report_type = "analysis"
        saved_report = get_saved_campaign_ai_report(request.user, campaign, report_type=report_type)
        if saved_report is not None:
            return build_campaign_ai_pdf_response(saved_report)
        start_date, end_date = normalize_date_range(request)
        report = build_campaign_ai_report(
            request.user,
            campaign,
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            persist=False,
            allow_openai=False,
        )
        return build_campaign_ai_pdf_response(report)
    except Exception as exc:
        return HttpResponse(str(exc) or "PDF üretilemedi.", status=500, content_type="text/plain; charset=utf-8")


@login_required
@api_subscription_required
@require_POST
def api_campaign_panel_sync_account(request, account_id):
    account = get_object_or_404(platform_accounts_for_request(request, active_only=True), id=account_id)
    days_back = request.POST.get("days_back") or request.GET.get("days_back") or 365
    try:
        days_back = max(1, min(int(days_back), 3650))
    except ValueError:
        days_back = 365

    job = PlatformSyncJob.objects.create(
        user=request.user,
        platform_account=account,
        days_back=days_back,
        status="pending",
        progress=0,
        message="Octo kampanya, reklam grubu, reklam, kreatif ve metrikleri çekmeye hazırlanıyor...",
    )

    if sync_platform_account_ads is not None:
        CacheService.bump_version("campaign_panel_accounts", request.user.id)
        CacheService.bump_version("campaign_panel_account", request.user.id, account.id)
        CacheService.bump_version("ads_panel_accounts", request.user.id)
        CacheService.bump_version("ads_panel_account", request.user.id, account.id)
        CacheService.bump_version("dashboard", request.user.id)
        CacheService.bump_version("control_tower", request.user.id)
        CacheService.bump_version("reports_center", request.user.id)
        CacheService.bump_version("health_center", request.user.id)
        sync_platform_account_ads.delay(job.id)
    else:
        job.status = "failed"
        job.message = "Senkronizasyon görevi yüklenemedi."
        job.error_message = "core.tasks.ads_pipeline.sync_platform_account_ads import edilemedi."
        job.save(update_fields=["status", "message", "error_message"])

    return JsonResponse({
        "success": True,
        "job_id": job.id,
        "message": "Octo kampanya verilerini çekmeye başladı.",
    })
@login_required
@require_GET
def api_campaign_panel_sync_job_status(request, job_id):
    job = get_object_or_404(
        PlatformSyncJob,
        id=job_id,
        user=request.user,
    )

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
