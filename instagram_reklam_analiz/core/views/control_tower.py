from datetime import timedelta
import csv
import hashlib
import json
import math
from collections import Counter
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponse, JsonResponse, HttpResponseRedirect
from django.utils.dateparse import parse_date

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Max, Sum, Q
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.core.paginator import Paginator
from django.utils import timezone
from django.urls import reverse, NoReverseMatch

from core.models import (
    Ad,
    AdGroup,
    AdMetricHistory,
    CreativeMetricHistory,
    CampaignMetricHistory,
    Campaign,
    Creative,
    OctoScoreHistory,
    PlatformAccount,
    PlatformConnection,
    PlatformSyncJob,
    AIOperationTariff,
)

try:
    from core.models import Notification
except Exception:
    Notification = None

try:
    from core.models import AnomalyAlert
except Exception:
    AnomalyAlert = None

try:
    from core.models import OctoTaskInstance
except Exception:
    OctoTaskInstance = None



try:
    from core.models import ControlTowerSnapshot
except Exception:
    ControlTowerSnapshot = None

try:
    from core.models import ControlTowerAIAnalysis
except Exception:
    ControlTowerAIAnalysis = None


try:
    from celery.result import AsyncResult
except Exception:
    AsyncResult = None

try:
    from core.tasks.control_tower_ai import generate_control_tower_ai_report_task
except Exception:
    generate_control_tower_ai_report_task = None

try:
    from core.services.control_tower_pdf import build_control_tower_screenshot_pdf
except Exception:
    build_control_tower_screenshot_pdf = None

try:
    from core.services.control_tower_snapshot import build_decision_center_from_context, build_lightweight_snapshot_for_user, save_snapshot_from_context
except Exception:
    build_decision_center_from_context = None
    build_lightweight_snapshot_for_user = None
    save_snapshot_from_context = None



from core.services.control_tower_context import (
    _aggregate_performance,
    _analysis_model_field_names,
    _archive_analysis_to_row,
    _bar_heights,
    _build_competitor_intelligence,
    _build_executive_summary_from_context,
    _build_octo_ai_analysis_pdf,
    _build_octo_ai_report_from_latest_snapshot,
    _campaign_ai_summary,
    _campaign_expected_gain,
    _campaign_health_score_engine,
    _campaign_metric_queryset,
    _competitor_pressure_score,
    _control_tower_refresh_meta,
    _delta_class,
    _delta_text,
    _ensure_numbered_report_items,
    _executive_opportunity_items,
    _executive_risk_items,
    _fmt_money,
    _fmt_percent,
    _fmt_ratio,
    _format_dashboard_number,
    _inverse_score,
    _label,
    _level,
    _model_has_field,
    _num,
    _octo_ai_score_engine,
    _pct_change,
    _performance_queryset,
    _period_days,
    _period_label,
    _polyline,
    _radar_polygon,
    _radar_state,
    _safe_aware_datetime,
    _safe_create_ai_analysis,
    _safe_div,
    _save_executive_summary_ai_record,
    _score,
    _score_from_roas_ctr,
    _score_level_class,
    _strategic_items,
    _trend_signal,
    _weighted_avg,
)
from core.services.agency_branding import get_report_branding
from core.services.agency_scope import get_agency_scope, platform_accounts_for_request, scope_queryset
from core.services.cache_service import CacheService
from core.services.entitlements import get_access_subscription
from core.services.openai_usage import consume_openai_operation, refund_ai_tariff_credits
from core.services.ai_credit_purchase import ai_credit_purchase_url, insufficient_credit_payload
from core.services.ai_agent_ecosystem import run_sixteen_agent_orchestration
from core.services.rate_limit import check_rate_limit, identity_for_request
from core.utils.html_translations import repair_mojibake, translate_html_to_english


CONTROL_TOWER_CACHE_TIMEOUT = 180
CONTROL_TOWER_AI_CREDIT_COST = 5


def _request_language(request):
    language = request.session.get("preferred_language")
    if language in {"tr", "en"}:
        return language
    profile = getattr(request.user, "profile", None)
    language = getattr(profile, "preferred_language", None)
    return language if language in {"tr", "en"} else "tr"


def _localize_control_tower_text(value, language):
    if isinstance(value, str):
        return translate_html_to_english(value) if language == "en" else repair_mojibake(value)
    if isinstance(value, list):
        return [_localize_control_tower_text(item, language) for item in value]
    if isinstance(value, tuple):
        return tuple(_localize_control_tower_text(item, language) for item in value)
    if isinstance(value, dict):
        return {
            key: _localize_control_tower_text(item, language)
            for key, item in value.items()
        }
    return value


def _localize_control_tower_context(context, language):
    """Normalize generated Control Tower copy before it reaches the template."""
    for key in (
        "octo_ai_report",
        "executive_summary",
        "competitor_intelligence",
        "control_alert_center",
        "decision_center",
    ):
        if context.get(key):
            context[key] = _localize_control_tower_text(context[key], language)

    for key in (
        "campaign_health_segment_cards",
        "octo_task_center_sections",
        "radar",
        "today_summary",
        "creative_wall_segment_cards",
        "refresh_meta",
    ):
        if context.get(key):
            context[key] = _localize_control_tower_text(context[key], language)

    return context


def _control_tower_ai_guard(request, *, amount=CONTROL_TOWER_AI_CREDIT_COST, consume_credit=True):
    if request.user.is_staff or request.user.is_superuser:
        return None

    rate = check_rate_limit(
        namespace="control_tower_ai",
        identity=identity_for_request(request, "user_or_ip"),
        rate=getattr(settings, "RATE_LIMIT_CONTROL_TOWER_AI", "6/h"),
    )
    if not rate.allowed:
        return {
            "payload": {
                "ok": False,
                "success": False,
                "error": "rate_limited",
                "message": "Cok fazla AI analiz istegi gonderildi. Lutfen kisa bir sure sonra tekrar deneyin.",
                "retry_after": rate.retry_after,
            },
            "status": 429,
        }

    if not getattr(settings, "AI_CREDITS_ENFORCED", True):
        return None

    subscription = get_access_subscription(request.user)
    if not subscription:
        return {
            "payload": {
                "ok": False,
                "success": False,
                "error": "subscription_required",
                "message": "Octo AI analizi icin aktif paket gerekli.",
            },
            "status": 402,
        }

    if not consume_credit:
        return None

    agency_scope = get_agency_scope(request)
    organization = (
        agency_scope.selected_client.organization
        if agency_scope.selected_client
        else subscription.organization
    )
    result = consume_openai_operation(
        user=request.user,
        organization=organization,
        tariff_key="control-tower-analysis",
        credit_amount=amount,
        reason="Control Tower Octo AI analizi",
        reference="control_tower.ai_analysis",
    )
    if not result.allowed:
        return {
            "payload": {"ok": False, **insufficient_credit_payload(
                message=result.reason,
                required_credits=result.used or amount,
                available_credits=result.limit,
            )},
            "status": 402,
        }
    return None


def _control_tower_ai_organization(request, agency_scope=None):
    agency_scope = agency_scope or get_agency_scope(request)
    if agency_scope.selected_client:
        return agency_scope.selected_client.organization
    subscription = get_access_subscription(request.user)
    return subscription.organization if subscription else None


def _control_tower_deep_ai_context(context):
    """Roll up every page row into a TPM-safe evidence pack for all 16 agents."""
    keys = (
        "filters",
        "summary",
        "live_performance",
        "radar",
        "trend",
        "today_summary",
        "platform_strip_cards",
        "refresh_meta",
        "decision_center",
        "campaign_health",
        "campaign_health_segments",
        "critical_alerts",
        "control_alert_center",
        "octo_task_center_tasks",
        "octo_task_center_sections",
        "octo_task_center_stats",
        "competitor_rows",
        "competitor_ad_groups",
        "competitor_intelligence",
        "creative_wall",
        "creative_wall_segment_cards",
        "creative_wall_stats",
    )
    complete_source = {key: context.get(key) for key in keys}

    def row_rollup(rows, *, numeric_fields=(), highlight_fields=()):
        rows = list(rows or [])
        states = Counter()
        numeric = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            state = row.get("status_key") or row.get("state") or row.get("status") or row.get("level")
            if state:
                states[str(state)] += 1
            for field in numeric_fields:
                value = _num(row.get(field))
                bucket = numeric.setdefault(field, {"sum": 0.0, "min": None, "max": None})
                bucket["sum"] += value
                bucket["min"] = value if bucket["min"] is None else min(bucket["min"], value)
                bucket["max"] = value if bucket["max"] is None else max(bucket["max"], value)
        for field, bucket in numeric.items():
            bucket["sum"] = round(bucket["sum"], 2)
            bucket["avg"] = round(bucket["sum"] / len(rows), 2) if rows else 0

        return {"count": len(rows), "states": dict(states), "numeric": numeric}

    campaign_rows = context.get("campaign_health") or []
    creative_rows = context.get("creative_wall") or []
    competitor_rows = context.get("competitor_rows") or []
    alert_rows = context.get("critical_alerts") or []
    task_rows = context.get("octo_task_center_tasks") or []
    platform_rows = context.get("platform_strip_cards") or []
    competitor_groups = context.get("competitor_ad_groups") or []
    competitor_ads = [ad for group in competitor_groups if isinstance(group, dict) for ad in (group.get("rows") or [])]

    summary = context.get("summary") or {}
    core_summary_keys = (
        "octo_score", "campaigns", "ad_groups", "creatives", "own_ads", "active_ads", "competitor_ads",
        "total_impressions", "total_clicks", "total_spend", "total_revenue", "total_conversions",
        "avg_roas", "avg_ctr", "avg_cpc", "avg_cpm", "conversion_rate", "roas_delta", "ctr_delta", "cpc_delta",
    )
    payload = {
        "filters": context.get("filters") or {},
        "summary": {key: summary.get(key) for key in core_summary_keys},
        # These compact KPI blocks represent the page-wide time/radar/decision
        # signals without repeating their presentation metadata 16 times.
        "page_signals": {
            "live": context.get("live_performance") or {},
            "today": context.get("today_summary") or {},
            "trend": context.get("trend") or {},
        },
        "campaigns": row_rollup(
            campaign_rows,
            numeric_fields=("score", "spend", "revenue", "roas", "ctr", "conversions"),
            highlight_fields=("status_label", "score", "roas", "ctr", "recommended_action"),
        ),
        "creatives": row_rollup(
            creative_rows,
            numeric_fields=("score", "impressions", "clicks", "spend", "revenue", "conversions", "ctr", "roas", "fatigue"),
            highlight_fields=("status_label", "score", "roas", "ctr", "fatigue", "recommended_action"),
        ),
        "competitors": row_rollup(
            competitor_rows,
            numeric_fields=("threat_score", "activity", "estimated_impressions", "estimated_engagement", "avg_ctr"),
            highlight_fields=("threat_score", "activity", "share", "platform_name"),
        ),
        "competitor_ads": row_rollup(
            competitor_ads,
            highlight_fields=("platform", "format", "seen_label", "text"),
        ),
        "alerts": row_rollup(alert_rows, highlight_fields=("severity", "message", "target_name")),
        "tasks": row_rollup(task_rows, numeric_fields=("priority",), highlight_fields=("status", "priority", "detail")),
        "platforms": row_rollup(platform_rows, highlight_fields=("status", "accounts", "sync")),
        "competitor_intelligence": {
            key: (context.get("competitor_intelligence") or {}).get(key)
            for key in ("pressure_score", "growth_label", "new_ads_label", "share_of_voice_label")
        },
        "creative_wall_stats": context.get("creative_wall_stats") or {},
        "octo_task_center_stats": context.get("octo_task_center_stats") or {},
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    payload["data_coverage"] = {
        "campaigns": len(campaign_rows),
        "creatives": len(creative_rows),
        "competitors": len(competitor_rows),
        "competitor_groups": len(competitor_groups),
        "competitor_ads": len(competitor_ads),
        "alerts": len(alert_rows),
        "tasks": len(task_rows),
        "platforms": len(platform_rows),
        "complete_page_dataset": True,
        "source_digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20],
    }
    return payload


def control_tower(request):
    user = request.user
    agency_scope = get_agency_scope(request)
    current_language = _request_language(request)

    today_real = timezone.localdate()
    active_period = request.GET.get("period", "monthly")
    allowed_periods = {"daily", "weekly", "monthly", "quarterly", "custom"}
    if active_period not in allowed_periods:
        active_period = "monthly"

    # Profesyonel filtre davranışı:
    # - İlk açılış varsayılan aylık görünümle gelir: bugün dahil son 30 gün.
    # - Günlük / haftalık / aylık / 3 aylık seçimleri tarih aralığını otomatik değiştirir.
    # - Kullanıcı tarih inputlarını manuel değiştirirse butonsuz şekilde özel tarih aralığı çalışır.
    today = today_real
    requested_start = parse_date(request.GET.get("date_from") or "")
    requested_end = parse_date(request.GET.get("date_to") or "")

    if requested_start and requested_end:
        start_date = requested_start
        today = min(requested_end, today_real)
        if start_date > today:
            start_date, today = today, start_date
            today = min(today, today_real)
        selected_days = max((today - start_date).days + 1, 1)
        if active_period == "custom":
            pass
    else:
        if active_period == "custom":
            active_period = "monthly"
        selected_days = _period_days(active_period)
        start_date = today - timedelta(days=selected_days - 1)


    # Octo AI analizleri HTTP isteği içinde üretilmez.
    # Buton sadece Celery işini kuyruğa atar; ekran polling ile sonucu takip eder.
    if request.GET.get("ai_status") and AsyncResult is not None:
        task_id = request.GET.get("ai_status")
        result = AsyncResult(task_id)
        payload = {"task_id": task_id, "state": result.state}
        if result.successful():
            data = result.result if isinstance(result.result, dict) else {}
            payload.update({"done": True, "result": data})
        elif result.failed():
            payload.update({"done": True, "failed": True, "error": str(result.result)})
        else:
            payload.update({"done": False})
        return JsonResponse(payload)

    # Güvenli fallback: Celery worker/register problemi varsa panel boş kalmasın.
    # Normal kullanımda buton ai_async ile Celery kullanır; bu endpoint sadece JS timeout/hata sonrası devreye girer.
    if request.GET.get("ai_sync") == "1":
        guard = _control_tower_ai_guard(request, consume_credit=False)
        if guard:
            return JsonResponse(guard["payload"], status=guard["status"])
        if build_lightweight_snapshot_for_user is None:
            return JsonResponse({"ok": False, "error": "AI snapshot servisi import edilemedi."}, status=500)
        snapshot = build_lightweight_snapshot_for_user(
            user,
            period=active_period,
            days=selected_days,
            agency_client=agency_scope.selected_client,
        )
        return JsonResponse({"ok": True, "snapshot_id": snapshot.id, "state": "SYNC_DONE"})

    if request.GET.get("ai_async") == "1":
        guard = _control_tower_ai_guard(request, consume_credit=False)
        if guard:
            return JsonResponse(guard["payload"], status=guard["status"])
        if generate_control_tower_ai_report_task is None:
            return JsonResponse({"ok": False, "error": "Celery AI analiz task import edilemedi."}, status=500)
        task = generate_control_tower_ai_report_task.delay(
            user_id=user.id,
            period=active_period,
            days=selected_days,
            force=True,
        )
        return JsonResponse({"ok": True, "task_id": task.id, "state": "QUEUED"})

    control_tower_cache_enabled = not any(
        request.GET.get(key)
        for key in ["export", "ai_refresh", "ai_done", "ai_status", "ai_sync", "ai_async"]
    )
    control_tower_cache_version = CacheService.get_version("control_tower", user.id)
    control_tower_cache_key_parts = (
        "schema",
        "no-empty-summary-v1",
        "user",
        user.id,
        "agency_client",
        agency_scope.cache_key,
        "period",
        active_period,
        "from",
        start_date.isoformat(),
        "to",
        today.isoformat(),
    )
    if control_tower_cache_enabled:
        cached_context = CacheService.get(
            "control_tower",
            *control_tower_cache_key_parts,
            version=control_tower_cache_version,
        )
        if cached_context is not None:
            cached_context = _localize_control_tower_context(dict(cached_context), current_language)
            return render(request, "dashboard/control_tower.html", cached_context)

    prev_start = start_date - timedelta(days=selected_days)
    prev_end = start_date - timedelta(days=1)

    own_ads = scope_queryset(request, Ad.objects.filter(source_type="OWN"))
    competitor_ads = scope_queryset(request, Ad.objects.filter(source_type="COMPETITOR"))

    def scoped_anomaly_queryset(queryset):
        if agency_scope.selected_client:
            return queryset.filter(
                rakip__platform_account__agency_client=agency_scope.selected_client
            )
        return queryset

    def scoped_octo_task_queryset(queryset):
        if not agency_scope.selected_client:
            return queryset
        client = agency_scope.selected_client
        return queryset.filter(
            Q(platform_account__agency_client=client)
            | Q(campaign__platform_account__agency_client=client)
            | Q(ad_group__campaign__platform_account__agency_client=client)
            | Q(ad__platform_account__agency_client=client)
            | Q(creative__platform_account__agency_client=client)
        ).distinct()

    metrics = AdMetricHistory.objects.filter(ad__in=own_ads, date__gte=start_date, date__lte=today)
    prev_metrics = AdMetricHistory.objects.filter(ad__in=own_ads, date__gte=prev_start, date__lte=prev_end)
    metric_source = prev_metric_source = "ad_metric_history"

    totals = _aggregate_performance(metrics)
    prev_totals = _aggregate_performance(prev_metrics)

    latest_octo = (
        OctoScoreHistory.objects
        .filter(user=user)
        .order_by("-calculated_at")
        .first()
    )

    previous_octo = (
        OctoScoreHistory.objects
        .filter(user=user)
        .order_by("-calculated_at")[1:2]
        .first()
    )

    avg_roas = totals["avg_roas"] or 0
    avg_ctr = totals["avg_ctr"] or 0
    avg_cpc = totals["avg_cpc"] or 0
    total_spend = totals["total_spend"] or 0
    total_clicks = totals["total_clicks"] or 0
    total_impressions = totals["total_impressions"] or 0
    total_conversions = totals["total_conversions"] or 0
    has_performance_data = any([
        _num(total_impressions) > 0,
        _num(total_clicks) > 0,
        _num(total_spend) > 0,
        _num(totals["total_revenue"]) > 0,
        _num(total_conversions) > 0,
    ])
    prev_total_clicks = prev_totals["total_clicks"] or 0
    prev_total_conversions = prev_totals["total_conversions"] or 0

    conversion_rate = (
        Decimal(total_conversions) / Decimal(total_clicks) * 100
        if total_clicks
        else Decimal("0")
    )
    prev_conversion_rate = (
        Decimal(prev_total_conversions) / Decimal(prev_total_clicks) * 100
        if prev_total_clicks
        else Decimal("0")
    )

    roas_delta = _pct_change(avg_roas, prev_totals["avg_roas"])
    ctr_delta = _pct_change(avg_ctr, prev_totals["avg_ctr"])
    cpc_delta = _pct_change(avg_cpc, prev_totals["avg_cpc"])
    spend_delta = _pct_change(total_spend, prev_totals["total_spend"])
    click_delta = _pct_change(total_clicks, prev_totals["total_clicks"])
    impression_delta = _pct_change(total_impressions, prev_totals["total_impressions"])

    # Dönüşüm ve Dönüşüm Oranı farklı KPI'lardır.
    # Dönüşüm = adet, Dönüşüm Oranı = conversions / clicks * 100.
    conversion_count_delta = _pct_change(total_conversions, prev_totals["total_conversions"])
    conversion_rate_delta = _pct_change(conversion_rate, prev_conversion_rate)

    # Octo AI Skoru V2 burada geçici olarak hazırlanır.
    # Asıl çok faktörlü skor; creative, radar, görev ve uyarı verileri oluştuktan sonra hesaplanır.
    octo_score = 0
    octo_label = "AI skoru hesaplanıyor"
    octo_components = {}
    octo_delta = 0

    # GA4 / AnalyticsDailyMetric Control Tower hesaplamalarından tamamen çıkarıldı.
    # Bu sayfadaki tüm ana metrikler reklam veritabanı tablolarından gelir.

    campaign_health = []
    active_campaign_filter = Q(status__iexact="ACTIVE") | Q(status__iexact="ENABLED")
    campaign_rows = (
        scope_queryset(request, Campaign.objects.all())
        .filter(active_campaign_filter)
        .select_related("platform_account", "platform_account__platform")
        .order_by("-updated_at", "-created_at")
    )

    for campaign in campaign_rows:
        current_campaign_metrics, metric_origin = _campaign_metric_queryset(campaign, start_date, today)
        previous_campaign_metrics, previous_metric_origin = _campaign_metric_queryset(campaign, prev_start, prev_end)

        current_summary = _aggregate_performance(current_campaign_metrics)
        previous_summary = _aggregate_performance(previous_campaign_metrics)

        alert_count = 0
        if AnomalyAlert is not None:
            try:
                alert_qs = scoped_anomaly_queryset(AnomalyAlert.objects.filter(user=user))
                if _model_has_field(AnomalyAlert, "campaign"):
                    alert_qs = alert_qs.filter(campaign=campaign)
                elif _model_has_field(AnomalyAlert, "campaign_id"):
                    alert_qs = alert_qs.filter(campaign_id=campaign.id)
                else:
                    alert_qs = alert_qs.none()
                if _model_has_field(AnomalyAlert, "detected_at"):
                    alert_qs = alert_qs.filter(detected_at__date__gte=start_date, detected_at__date__lte=today)
                alert_count = alert_qs.count()
            except Exception:
                alert_count = 0

        health = _campaign_health_score_engine(
            campaign=campaign,
            metrics=current_summary,
            prev_metrics=previous_summary,
            alert_count=alert_count,
        )

        platform_name = "-"
        try:
            if campaign.platform_account and campaign.platform_account.platform:
                platform_name = campaign.platform_account.platform.name
        except Exception:
            platform_name = "-"

        campaign_health.append({
            "name": campaign.name,
            "platform": platform_name,
            "score": health["score"],
            "level": health["level"],
            "label": health["label"],
            "reason": health["reason"],
            "detail": health["detail"],
            "delta": health["delta"],
            "delta_abs": health["delta_abs"],
            "roas": health["roas"],
            "ctr": health["ctr"],
            "conversion_rate": health["conversion_rate"],
            "cpc": health["cpc"],
            "cpa": health["cpa"],
            "cpm": health["cpm"],
            "spend": health["spend"],
            "revenue": health["revenue"],
            "conversions": health["conversions"],
            "impressions": health["impressions"],
            "clicks": health["clicks"],
            "data_confidence": health["data_confidence"],
            "expected_gain": _campaign_expected_gain(health),
            "expected_gain_label": _fmt_money(_campaign_expected_gain(health)),
            "risk_reason": health["reason"],
            "ai_summary": _campaign_ai_summary(health),
            "trend_signal": _trend_signal(health["delta"], True),
            "roas_label": _fmt_ratio(health["roas"]),
            "ctr_label": _fmt_percent(health["ctr"]),
            "conversion_rate_label": _fmt_percent(health["conversion_rate"]),
            "cpc_label": _fmt_money(health["cpc"]),
            "cpa_label": _fmt_money(health["cpa"]),
            "spend_label": _fmt_money(health["spend"]),
            "revenue_label": _fmt_money(health["revenue"]),
            "conversions_label": _format_dashboard_number(health["conversions"], decimals=0),
            "data_confidence_label": _fmt_percent(health["data_confidence"]),
            "metric_origin": "Kampanya geçmişi" if metric_origin == "campaign" else "Reklam geçmişi fallback",
        })

    # Control Tower operasyon kartıdır: tüm aktif kampanyalar listelenir,
    # en çok müdahale gerekenler en üstte gösterilir. Kart scroll ile devam eder.
    campaign_health = sorted(campaign_health, key=lambda row: (row["score"], -row["delta_abs"], row["name"]))
    campaign_health_count = len(campaign_health)

    def _health_bucket(row):
        level = str(row.get("level", "")).lower().strip()
        label = str(row.get("label", "")).lower().strip()
        score = _num(row.get("score"))

        # Öncelik label + skor bilgisinde.
        # Çünkü skor motoru 40-54 aralığında level=mid, label=Riskli döndürüyor.
        # Eski sırada level=mid önce yakalandığı için riskli kampanya izlenmeliye düşüyordu.
        if "kritik" in label or "risk" in label or score < 55:
            return "risk"
        if "izlen" in label or "watch" in label or 55 <= score < 70:
            return "watch"
        if "sağ" in label or "sag" in label or "mükemmel" in label or "mukemmel" in label or score >= 70:
            return "healthy"

        # Eski/yeni tüm olası seviye adları normalize edilir.
        # Label/skor boş gelirse son güvenli ayrım level üzerinden yapılır.
        if level in {"bad", "risk", "risky", "critical", "danger", "high_risk"}:
            return "risk"
        if level in {"mid", "warn", "warning", "watch", "neutral", "izlenmeli"}:
            return "watch"
        if level in {"good", "healthy", "success", "safe", "positive"}:
            return "healthy"

        return "watch"

    risk_campaigns = [row for row in campaign_health if _health_bucket(row) == "risk"]
    watch_campaigns = [row for row in campaign_health if _health_bucket(row) == "watch"]
    healthy_campaigns = [row for row in campaign_health if _health_bucket(row) == "healthy"]

    # Segmentler tek merkezden üretilir. Template artık ayrı ayrı değişken aramaz;
    # sayaç ve liste aynı kaynaktan gelir. Böylece sayaç var/liste yok veya
    # Riskli/İzlenmeli karışması engellenir.
    campaign_health_segments = {
        "risk": risk_campaigns,
        "watch": watch_campaigns,
        "healthy": healthy_campaigns,
    }
    campaign_health_segment_cards = [
        {
            "key": "risk",
            "state": "bad",
            "icon": "fa-fire-flame-curved",
            "short_label": "Riskli",
            "title": "Riskli Kampanyalar",
            "subtitle": "Acil müdahale",
            "note": "Skor 55 altı veya kritik/risk sinyali",
            "rows": risk_campaigns,
            "count": len(risk_campaigns),
        },
        {
            "key": "watch",
            "state": "mid",
            "icon": "fa-eye",
            "short_label": "İzlenmeli",
            "title": "İzlenmeli Kampanyalar",
            "subtitle": "Yakın takip",
            "note": "Skor 55-69 arası veya watch/warning sinyali",
            "rows": watch_campaigns,
            "count": len(watch_campaigns),
        },
        {
            "key": "healthy",
            "state": "good",
            "icon": "fa-circle-check",
            "short_label": "Sağlıklı",
            "title": "Sağlıklı Kampanyalar",
            "subtitle": "Ölçeklenebilir",
            "note": "Skor 70+ veya sağlıklı/başarılı sinyal",
            "rows": healthy_campaigns,
            "count": len(healthy_campaigns),
        },
    ]

    critical_alerts = []

    if AnomalyAlert:
        alert_qs = scoped_anomaly_queryset(AnomalyAlert.objects.filter(user=user))
        for alert in alert_qs.order_by("-detected_at")[:3]:
            critical_alerts.append({
                "message": getattr(alert, "description", None) or getattr(alert, "title", "Anomali uyarısı"),
                "level": getattr(alert, "severity", "warning"),
            })

    if not critical_alerts and Notification and not agency_scope.selected_client:
        for notification in Notification.objects.filter(user=user).order_by("-created_at")[:3]:
            critical_alerts.append({
                "message": getattr(notification, "message", None) or getattr(notification, "title", "Bildirim"),
                "level": getattr(notification, "level", "warning"),
            })

    # Campaign Center öneri listesi Control Tower'dan kaldırıldı.
    # Ekranda yalnızca OctoTaskInstance tabanlı gerçek görev merkezi kalır.

    # Octo Görev Merkezi V3
    # Yeni OctoTaskInstance görev motorundan beslenir.
    # Rakip/competitor modülü görevleri de aynı motor içinde devrededir; ayrı kopya görev üretilmez.
    octo_task_center_tasks = []
    octo_task_center_sections = []
    octo_task_center_stats = {
        "critical": 0,
        "warning": 0,
        "info": 0,
        "opportunity": 0,
        "open": 0,
        "viewed": 0,
        "snoozed": 0,
        "done": 0,
        "total_active": 0,
    }

    control_alert_center = {
        "items": [],
        "total_count": 0,
        "critical_count": 0,
        "warning_count": 0,
        "opportunity_count": 0,
    }

    if OctoTaskInstance is not None:
        active_octo_task_qs = (
            scoped_octo_task_queryset(
                OctoTaskInstance.objects.filter(user=user, status__in=["open", "viewed", "snoozed"])
            )
            .select_related("rule", "campaign", "ad_group", "ad", "ad__competitor", "creative", "platform_account", "platform_connection")
            .order_by("-priority_score", "-last_detected_at", "-created_at")
        )

        done_octo_task_qs = scoped_octo_task_queryset(
            OctoTaskInstance.objects.filter(user=user, status="done")
        )

        octo_task_center_stats = {
            "critical": active_octo_task_qs.filter(severity="critical").count(),
            "warning": active_octo_task_qs.filter(severity="warning").count(),
            "info": active_octo_task_qs.filter(severity="info").count(),
            "opportunity": active_octo_task_qs.filter(severity="opportunity").count(),
            "open": active_octo_task_qs.filter(status="open").count(),
            "viewed": active_octo_task_qs.filter(status="viewed").count(),
            "snoozed": active_octo_task_qs.filter(status="snoozed").count(),
            "done": done_octo_task_qs.count(),
            "total_active": active_octo_task_qs.count(),
        }

        severity_labels = {
            "critical": "KRİTİK",
            "warning": "UYARI",
            "info": "BİLGİ",
            "opportunity": "FIRSAT",
        }
        status_labels = {
            "open": "Açık",
            "viewed": "İncelendi",
            "snoozed": "Ertelendi",
            "done": "Tamamlandı",
            "dismissed": "Kapatıldı",
        }
        module_labels = {
            "performance": "Performans",
            "creative": "Kreatif",
            "budget": "Bütçe",
            "competitor": "Rakip",
            "conversion": "Dönüşüm",
        }

        def _task_payload(task):
            campaign = getattr(task, "campaign", None)
            ad = getattr(task, "ad", None)
            platform_account = getattr(task, "platform_account", None)
            rule = getattr(task, "rule", None)
            is_competitor_task = (
                getattr(task, "module", None) == "competitor"
                or (ad is not None and getattr(ad, "source_type", None) == "COMPETITOR")
            )

            campaign_name = "Genel hesap görevi"
            competitor_name = ""
            if is_competitor_task and ad is not None:
                competitor = getattr(ad, "competitor", None)
                competitor_name = (
                    getattr(competitor, "name", None)
                    or getattr(ad, "competitor_name", None)
                    or "Rakip firma"
                )
                campaign_name = competitor_name
            elif campaign is not None and getattr(campaign, "name", None):
                campaign_name = campaign.name
            elif platform_account is not None:
                campaign_name = (
                    getattr(platform_account, "account_name", None)
                    or getattr(platform_account, "name", None)
                    or "Platform hesabı"
                )

            platform_name = "-"
            try:
                if platform_account and platform_account.platform:
                    platform_name = platform_account.platform.name
            except Exception:
                platform_name = "-"

            rule_expected_result = getattr(rule, "expected_result", None) if rule is not None else None
            rule_user_condition = getattr(rule, "user_condition", None) if rule is not None else None
            rule_root_cause = getattr(rule, "root_cause", None) if rule is not None else None
            rule_cta_text = getattr(rule, "cta_text", None) if rule is not None else None

            impact_text = rule_expected_result or rule_user_condition or "Beklenen etki görev uygulandıktan sonra takip edilir."
            detail_text = task.message_tr or rule_user_condition or rule_root_cause or "Octo bu görevi son performans sinyallerine göre oluşturdu."
            action_text = task.action_text_tr or rule_cta_text or "Görevi İncele"

            campaign_id = getattr(campaign, "id", None) if campaign is not None else None
            ad_id = getattr(ad, "id", None) if ad is not None else None
            campaign_url = ""
            campaign_analysis_url = ""

            if is_competitor_task:
                try:
                    competitor_url = reverse("competitor_intelligence")
                except NoReverseMatch:
                    competitor_url = "/competitor-intelligence/"
                query = {"open_competitor_ad": ad_id or "", "competitor": competitor_name or campaign_name}
                campaign_url = f"{competitor_url}?{urlencode(query)}"
            elif campaign_id:
                try:
                    campaign_analysis_url = reverse("octo_campaign_analysis_safe", kwargs={"campaign_id": campaign_id})
                except NoReverseMatch:
                    campaign_analysis_url = f"/campaign-center/octo-analysis-safe/{campaign_id}/"

                # V2 Campaign id için eski /campaigns/<id>/ kullanılmaz.
                # Campaign Center zaten open_octo parametresiyle aynı kampanyanın modalını açabiliyor.
                try:
                    campaign_center_url = reverse("campaign_center")
                except NoReverseMatch:
                    campaign_center_url = "/campaign-center/"
                campaign_url = f"{campaign_center_url}?{urlencode({'open_octo': campaign_id, 'campaign_name': campaign_name})}"

            target_url = campaign_url or "#"
            if not is_competitor_task:
                ad_group = getattr(task, "ad_group", None)
                creative = getattr(task, "creative", None)
                if ad is not None and getattr(ad, "id", None):
                    try:
                        ads_center_url = reverse("ads_center")
                    except NoReverseMatch:
                        ads_center_url = "/ads-center/"
                    target_url = f"{ads_center_url}?{urlencode({'open_ad': ad.id})}"
                elif creative is not None and getattr(creative, "id", None):
                    try:
                        creative_center_url = reverse("creative_center")
                    except NoReverseMatch:
                        creative_center_url = "/creative-center/"
                    target_url = f"{creative_center_url}?{urlencode({'open_creative': creative.id})}"
                elif ad_group is not None and getattr(ad_group, "id", None):
                    try:
                        adgroup_center_url = reverse("adgroup_center")
                    except NoReverseMatch:
                        adgroup_center_url = "/adgroup-center/"
                    target_url = f"{adgroup_center_url}?{urlencode({'open_adgroup': ad_group.id})}"

            return {
                "id": task.id,
                "title": task.title_tr or "Octo görevi",
                "message": detail_text,
                "action_text": action_text,
                "campaign": campaign_name,
                "campaign_id": campaign_id,
                "campaign_url": campaign_url,
                "campaign_analysis_url": campaign_analysis_url,
                "target_url": target_url,
                "ad_id": ad_id,
                "is_competitor_task": is_competitor_task,
                "source_label": "Rakip Reklamı" if is_competitor_task else "Kampanya",
                "platform": platform_name,
                "impact": impact_text,
                "severity": task.severity,
                "severity_label": severity_labels.get(task.severity, "GÖREV"),
                "status": task.status,
                "status_label": status_labels.get(task.status, "Açık"),
                "module": task.module,
                "module_label": module_labels.get(task.module, task.module or "Genel"),
                "priority_score": task.priority_score,
                "last_detected_at": task.last_detected_at,
            }

        section_definitions = [
            {
                "key": "critical",
                "state": "bad",
                "icon": "fa-fire-flame-curved",
                "title": "Kritik Görevler",
                "subtitle": "Önce müdahale edilmesi gereken kampanyalar",
                "note": "Acil kontrol · veri, maliyet veya gelir riski",
                "queryset": active_octo_task_qs.filter(severity="critical"),
                "count": octo_task_center_stats["critical"],
            },
            {
                "key": "warning",
                "state": "mid",
                "icon": "fa-triangle-exclamation",
                "title": "Uyarılar",
                "subtitle": "Yakından takip edilmesi gereken kampanyalar",
                "note": "Performans zayıflaması · maliyet veya ilgi sinyali",
                "queryset": active_octo_task_qs.filter(severity__in=["warning", "info"]),
                "count": octo_task_center_stats["warning"] + octo_task_center_stats["info"],
            },
            {
                "key": "opportunity",
                "state": "good",
                "icon": "fa-arrow-trend-up",
                "title": "Fırsatlar",
                "subtitle": "Büyütme veya iyileştirme potansiyeli olan kampanyalar",
                "note": "Ölçekleme · bütçe veya kreatif fırsatı",
                "queryset": active_octo_task_qs.filter(severity="opportunity"),
                "count": octo_task_center_stats["opportunity"],
            },
        ]

        for section in section_definitions:
            rows = [_task_payload(task) for task in section["queryset"]]
            competitor_rows = [row for row in rows if row.get("is_competitor_task")]
            campaign_rows = [row for row in rows if not row.get("is_competitor_task")]
            section["rows"] = rows
            section["campaign_rows"] = campaign_rows
            section["competitor_rows"] = competitor_rows
            section["competitor_count"] = len(competitor_rows)
            section["campaign_count"] = len(campaign_rows)
            section["task_groups"] = [
                {
                    "key": "competitor",
                    "label": "Rakip reklam görevleri",
                    "icon": "fa-binoculars",
                    "rows": competitor_rows,
                    "count": len(competitor_rows),
                },
                {
                    "key": "campaign",
                    "label": "Kampanya görevleri",
                    "icon": "fa-bullseye",
                    "rows": campaign_rows,
                    "count": len(campaign_rows),
                },
            ]
            section.pop("queryset", None)
            octo_task_center_sections.append(section)
            octo_task_center_tasks.extend(rows)

    # Header Alarm Merkezi: Kritik Uyarılar kartının yerine gerçek aksiyon merkezi.
    # Yeni model/endpoint üretmez; mevcut OctoTaskInstance ve AnomalyAlert kayıtlarından beslenir.
    def _ct_alert_target_for_ad(ad_obj):
        if ad_obj is None or not getattr(ad_obj, "id", None):
            return "#"
        if getattr(ad_obj, "source_type", None) == "COMPETITOR":
            competitor = getattr(ad_obj, "competitor", None)
            competitor_name = getattr(competitor, "name", None) or getattr(ad_obj, "competitor_name", "") or ""
            try:
                base_url = reverse("competitor_intelligence")
            except NoReverseMatch:
                base_url = "/competitor-intelligence/"
            return f"{base_url}?{urlencode({'open_competitor_ad': ad_obj.id, 'competitor': competitor_name})}"
        try:
            base_url = reverse("ads_center")
        except NoReverseMatch:
            base_url = "/ads-center/"
        return f"{base_url}?{urlencode({'open_ad': ad_obj.id})}"

    def _ct_alert_time(value):
        if not value:
            return ""
        try:
            return timezone.localtime(value).strftime("%d.%m %H:%M")
        except Exception:
            return str(value)[:16]

    def _ct_alert_state(severity):
        if severity in {"critical", "high"}:
            return "danger"
        if severity in {"warning", "medium", "info"}:
            return "warning"
        if severity == "opportunity":
            return "success"
        return "info"

    def _ct_alert_label(severity):
        return {
            "critical": "KRİTİK",
            "high": "YÜKSEK",
            "warning": "UYARI",
            "medium": "ORTA",
            "info": "BİLGİ",
            "opportunity": "FIRSAT",
            "low": "DÜŞÜK",
        }.get(severity or "", "MESAJ")

    alert_items = []

    if OctoTaskInstance is not None:
        alert_task_qs = (
            active_octo_task_qs
            .filter(severity__in=["critical", "warning", "opportunity"])
            .order_by("-priority_score", "-last_detected_at", "-created_at")[:15]
        )
        for task in alert_task_qs:
            payload = _task_payload(task)
            severity = payload.get("severity") or "warning"
            alert_items.append({
                "kind": "task",
                "state": _ct_alert_state(severity),
                "icon": "fa-bell" if severity == "critical" else "fa-triangle-exclamation" if severity == "warning" else "fa-arrow-trend-up",
                "title": payload.get("title") or "Octo görevi",
                "message": payload.get("message") or "Kontrol edilmesi gereken görev var.",
                "target_name": payload.get("campaign") or "",
                "target_url": payload.get("target_url") or payload.get("campaign_url") or "#",
                "source_label": payload.get("source_label") or payload.get("module_label") or "Octo Görevi",
                "severity": severity,
                "severity_label": _ct_alert_label(severity),
                "time_label": _ct_alert_time(payload.get("last_detected_at")),
                "sort_score": payload.get("priority_score") or 0,
            })

    if AnomalyAlert is not None:
        anomaly_qs = scoped_anomaly_queryset(
            AnomalyAlert.objects.filter(user=user, is_dismissed=False, severity__in=["critical", "high"])
        ).order_by("-detected_at")[:10]
        for alert in anomaly_qs:
            ad_obj = getattr(alert, "rakip", None)
            action_link = getattr(alert, "action_link", None)
            target_url = action_link or _ct_alert_target_for_ad(ad_obj)
            alert_items.append({
                "kind": "anomaly",
                "state": "danger" if getattr(alert, "severity", "") == "critical" else "warning",
                "icon": "fa-circle-exclamation",
                "title": getattr(alert, "title", None) or "Anomali uyarısı",
                "message": getattr(alert, "description", None) or getattr(alert, "suggested_action", None) or "Sistem gerçek performans anomalisi yakaladı.",
                "target_name": getattr(ad_obj, "name", None) or getattr(ad_obj, "ad_name", None) or "",
                "target_url": target_url,
                "source_label": "Anomali" if not ad_obj else "Rakip Reklamı" if getattr(ad_obj, "source_type", None) == "COMPETITOR" else "Reklam",
                "severity": getattr(alert, "severity", "warning"),
                "severity_label": _ct_alert_label(getattr(alert, "severity", "warning")),
                "time_label": _ct_alert_time(getattr(alert, "detected_at", None)),
                "sort_score": 95 if getattr(alert, "severity", "") == "critical" else 80,
            })

    # Aynı hedef ve başlık tekrar ediyorsa drawer içinde tek göster.
    deduped_alerts = []
    seen_alerts = set()
    for item in sorted(alert_items, key=lambda row: row.get("sort_score", 0), reverse=True):
        key = (item.get("kind"), item.get("title"), item.get("target_url"))
        if key in seen_alerts:
            continue
        seen_alerts.add(key)
        deduped_alerts.append(item)

    control_alert_center = {
        "items": deduped_alerts[:20],
        "total_count": len(deduped_alerts),
        "critical_count": sum(1 for item in deduped_alerts if item.get("severity") in {"critical", "high"}),
        "warning_count": sum(1 for item in deduped_alerts if item.get("severity") in {"warning", "medium", "info"}),
        "opportunity_count": sum(1 for item in deduped_alerts if item.get("severity") == "opportunity"),
    }

    total_competitor = competitor_ads.count() or 1

    platform_icon_map = {
        "facebook": "fab fa-facebook-f",
        "meta": "fab fa-meta",
        "instagram": "fab fa-instagram",
        "google": "fab fa-google",
        "google ads": "fab fa-google",
        "google_analytics": "fas fa-chart-line",
        "google analytics": "fas fa-chart-line",
        "tiktok": "fab fa-tiktok",
        "linkedin": "fab fa-linkedin-in",
        "x": "fab fa-x-twitter",
        "twitter": "fab fa-x-twitter",
        "youtube": "fab fa-youtube",
    }
    platform_order = ["Meta", "Instagram", "Google Ads", "Google Analytics", "TikTok", "LinkedIn", "X", "YouTube"]
    platform_strip_cards = []
    try:
        connection_rows = list(
            PlatformConnection.objects.filter(user=user, is_active=True)
            .select_related("platform")
            .values("platform__name", "platform__code", "status", "last_sync")
        )
        account_counts = {
            row["platform__name"]: row["count"]
            for row in platform_accounts_for_request(request, active_only=True)
            .values("platform__name")
            .annotate(count=Count("id"))
        }
        by_name = {}
        for row in connection_rows:
            platform_name = row.get("platform__name") or row.get("platform__code") or "Platform"
            key = str(platform_name).strip().lower()
            by_name[key] = row
        for platform_name in platform_order:
            key = platform_name.lower()
            matched_key = next((k for k in by_name if key in k or k in key), None)
            row = by_name.get(matched_key) if matched_key else None
            account_count = account_counts.get(platform_name) or 0
            if row:
                raw_status = (row.get("status") or "active").lower()
                state = "good" if raw_status == "active" else "warn" if raw_status in {"expired", "disconnected"} else "bad"
                status_label = "Aktif" if state == "good" else "Uyarı" if state == "warn" else "Hata"
                last_sync_value = row.get("last_sync")
                sync_label = timezone.localtime(last_sync_value).strftime("%d.%m %H:%M") if last_sync_value else "Bekliyor"
            else:
                state = "idle"
                status_label = "Bağlı değil"
                sync_label = "-"
            platform_strip_cards.append({
                "name": platform_name,
                "icon": platform_icon_map.get(platform_name.lower(), "fas fa-plug-circle-check"),
                "state": state,
                "status": status_label,
                "sync": sync_label,
                "accounts": account_count,
            })
    except Exception:
        platform_strip_cards = [
            {"name": name, "icon": platform_icon_map.get(name.lower(), "fas fa-plug-circle-check"), "state": "idle", "status": "Hazır", "sync": "-", "accounts": 0}
            for name in platform_order
        ]

    try:
        today_campaigns = CampaignMetricHistory.objects.filter(
            campaign__in=scope_queryset(request, Campaign.objects.all()),
            date=today_real,
        ).values("campaign_id").distinct().count()
    except Exception:
        today_campaigns = 0
    try:
        today_adgroups = scope_queryset(
            request,
            AdGroup.objects.filter(created_at__date=today_real),
            account_lookup="campaign__platform_account",
        ).count()
    except Exception:
        today_adgroups = 0
    try:
        today_ads = own_ads.filter(created_at__date=today_real).count()
    except Exception:
        today_ads = 0
    try:
        today_metrics_count = metrics.filter(date=today_real).count()
    except Exception:
        today_metrics_count = 0

    # Hesap Varlık Özeti'ndeki Kritik Uyarı sayısı yalnızca ekranda
    # gösterilen ilk 3 uyarıdan hesaplanmamalı. Gerçek kritik sayı;
    # açık kritik Octo görevleri + kapatılmamış kritik/yüksek anomalilerden gelir.
    # Böylece Octo Görev Merkezi'nde 25 kritik görev varken özet kartı 3 göstermez.
    real_critical_alert_count = int(octo_task_center_stats.get("critical", 0) or 0)
    if AnomalyAlert is not None:
        try:
            real_critical_alert_count += scoped_anomaly_queryset(
                AnomalyAlert.objects.filter(
                    user=user,
                    is_dismissed=False,
                    severity__in=["critical", "high"],
                )
            ).count()
        except Exception:
            pass
    if not real_critical_alert_count:
        real_critical_alert_count = len(critical_alerts)

    today_summary = {
        "campaigns": today_campaigns or scope_queryset(request, Campaign.objects.all()).count(),
        "ad_groups": today_adgroups or scope_queryset(
            request,
            AdGroup.objects.all(),
            account_lookup="campaign__platform_account",
        ).count(),
        "ads": today_ads or own_ads.count(),
        "critical_alerts": real_critical_alert_count,
        "pending_tasks": octo_task_center_stats.get("open", 0),
        "applied_tasks": octo_task_center_stats.get("done", 0),
        "metrics": today_metrics_count,
    }

    competitor_rows = []
    competitor_ad_groups = []

    competitor_category_meta = {
        "direct": {
            "label": "Doğrudan Rakipler",
            "tone": "bad",
            "icon": "fa-crosshairs",
            "note": "Aynı müşteri kitlesine doğrudan baskı yapan reklamlar",
        },
        "indirect": {
            "label": "Dolaylı Rakipler",
            "tone": "mid",
            "icon": "fa-route",
            "note": "Benzer ihtiyaca oynayan, pazarı dolaylı etkileyen reklamlar",
        },
        "potential": {
            "label": "Potansiyel Rakipler",
            "tone": "good",
            "icon": "fa-seedling",
            "note": "Yeni yükselen ve izlemeye alınması gereken reklam sinyalleri",
        },
        "unknown": {
            "label": "Kategorisiz Rakip Reklamları",
            "tone": "neutral",
            "icon": "fa-layer-group",
            "note": "Rakip kategorisi tanımlanmamış reklamlar",
        },
    }

    def _clean_text(value, fallback=""):
        text = str(value or "").strip()
        if not text:
            return fallback

        first_line = next(
            (line.strip(" -•\t") for line in text.splitlines() if line.strip()),
            text,
        )
        return first_line[:150]

    def _safe_date_label(value):
        if not value:
            return "-"
        try:
            return timezone.localtime(value).strftime("%d.%m.%Y")
        except Exception:
            try:
                return value.strftime("%d.%m.%Y")
            except Exception:
                return "-"

    def _competitor_ad_payload(ad):
        competitor = getattr(ad, "competitor", None)
        platform_account = getattr(ad, "platform_account", None)
        platform_name = "-"
        try:
            if platform_account and platform_account.platform:
                platform_name = platform_account.platform.name
        except Exception:
            platform_name = "-"

        ad_title = (
            getattr(ad, "headline", None)
            or getattr(ad, "name", None)
            or getattr(ad, "primary_text", None)
            or f"Rakip reklam #{getattr(ad, 'id', '')}"
        )
        ad_title = _clean_text(ad_title, "Rakip reklam")
        primary_text = _clean_text(getattr(ad, "primary_text", None) or getattr(ad, "description", None), "Metin bulunamadı")
        if len(primary_text) > 110:
            primary_text = primary_text[:107].rstrip() + "..."

        competitor_name = (
            getattr(competitor, "name", None)
            or getattr(platform_account, "account_name", None)
            or "Rakip"
        )
        category = getattr(competitor, "category", None) or "unknown"
        if category not in competitor_category_meta:
            category = "unknown"

        return {
            "id": getattr(ad, "id", None),
            "title": ad_title,
            "text": primary_text,
            "competitor": competitor_name,
            "category": category,
            "platform": platform_name,
            "format": getattr(ad, "ad_format", None) or getattr(ad, "objective", None) or "Reklam",
            "cta": getattr(ad, "call_to_action", None) or "İncele",
            "landing_url": getattr(ad, "landing_url", None) or "",
            "seen_label": _safe_date_label(getattr(ad, "last_seen_at", None) or getattr(ad, "created_at", None)),
            "status": getattr(ad, "status", None) or "UNKNOWN",
        }

    competitor_group = (
        competitor_ads.values(
            "competitor_id",
            "competitor__name",
            "platform_account__account_name",
            "platform_account__platform__name",
        )
        .annotate(total=Count("id"))
        .order_by("-total")[:8]
    )

    for row in competitor_group:
        name = (
            row.get("competitor__name")
            or row.get("platform_account__account_name")
            or row.get("platform_account__platform__name")
            or "Competitor"
        )
        total = row["total"] or 0
        share = round((total / total_competitor) * 100)
        pressure_score, pressure_state, pressure_label = _competitor_pressure_score(total, share)
        competitor_rows.append({
            "name": name,
            "new_ads": total,
            "new_ads_label": _format_dashboard_number(total, decimals=0),
            "trend": "up" if total else "flat",
            "trend_icon": "▲" if total else "▬",
            "trend_state": "bad" if total else "neutral",
            "share": share,
            "share_label": _fmt_percent(share),
            "pressure_score": pressure_score,
            "pressure_state": pressure_state,
            "pressure_label": pressure_label,
        })

    competitor_ads_for_list = list(
        competitor_ads
        .select_related("competitor", "platform_account", "platform_account__platform")
        .order_by("competitor__name", "-last_seen_at", "-created_at")[:120]
    )

    # Rakip reklam listesi kategoriye göre değil, firma bazlı gösterilir:
    # Rakip Firma -> o firmanın reklamları.
    # Böylece kullanıcı hangi rakibin hangi kreatif/reklam hamlesini yaptığını doğrudan görür.
    competitor_company_buckets = {}
    for ad in competitor_ads_for_list:
        payload = _competitor_ad_payload(ad)
        competitor_name = payload.get("competitor") or "Rakip firma"
        bucket = competitor_company_buckets.setdefault(competitor_name, {
            "key": competitor_name.lower().replace(" ", "-"),
            "name": competitor_name,
            "platform": payload.get("platform") or "-",
            "count": 0,
            "rows": [],
        })
        bucket["rows"].append(payload)
        bucket["count"] += 1

    for bucket in competitor_company_buckets.values():
        rows = bucket.get("rows") or []
        total_count = bucket.get("count") or len(rows)
        bucket["visible_count"] = min(total_count, 5)
        bucket["hidden_count"] = max(total_count - 5, 0)
        bucket["latest_label"] = rows[0].get("seen_label") if rows else "-"

    competitor_ad_groups = sorted(
        competitor_company_buckets.values(),
        key=lambda item: item["count"],
        reverse=True,
    )[:8]

    # Octo Görev Merkezi rakip görevleri yalnızca OctoTaskInstance tablosundan gelir.
    # Gösterim amaçlı sanal görev üretilmez. Rakip reklam görevi görünmüyorsa
    # generate_octo_tasks komutu gerçek koşulu yakalayıp instance açmamış demektir.

    competitor_current_count = 0
    competitor_previous_count = 0
    try:
        if _model_has_field(Ad, "created_at"):
            competitor_current_count = competitor_ads.filter(created_at__date__gte=start_date, created_at__date__lte=today).count()
            competitor_previous_count = competitor_ads.filter(created_at__date__gte=prev_start, created_at__date__lte=prev_end).count()
        else:
            competitor_current_count = total_competitor
    except Exception:
        competitor_current_count = total_competitor
        competitor_previous_count = 0

    if not competitor_current_count:
        competitor_current_count = sum(int(_num(r.get("new_ads"))) for r in competitor_rows)

    competitor_intelligence = _build_competitor_intelligence(
        competitor_rows=competitor_rows,
        total_competitor=total_competitor,
        current_count=competitor_current_count,
        previous_count=competitor_previous_count,
        selected_days=selected_days,
    )

    # Creative Performans Duvarı
    # Kaynak doğrudan DB metrik tablolarıdır.
    # 1) Öncelik: CreativeMetricHistory -> Creative
    # 2) Fallback: AdMetricHistory -> Ad -> Creative
    # Metrik olmayan kreatif gösterilmez. Böylece CTR/ROAS/Yorgunluk boş veya uydurma gelmez.
    # Ürün mantığı gereği Control Tower yalnızca AKTİF kampanyalara bağlı kreatifleri gösterir.
    # Önemli: bazı reklamlarda kampanya doğrudan ad.campaign üzerinden,
    # bazılarında ise ad.ad_group.campaign üzerinden bağlı olabilir. İki ilişki yolu da desteklenir.
    active_ad_campaign_filter = (
        Q(campaign__status__iexact="ACTIVE") |
        Q(campaign__status__iexact="ENABLED") |
        Q(ad_group__campaign__status__iexact="ACTIVE") |
        Q(ad_group__campaign__status__iexact="ENABLED")
    )

    active_campaign_creative_ids = list(
        scope_queryset(
            request,
            Ad.objects.filter(
            source_type="OWN",
            creative__isnull=False,
            ),
        )
        .filter(active_ad_campaign_filter)
        .values_list("creative_id", flat=True)
        .distinct()
    )

    creative_wall = []
    creative_seen_ids = set()

    def _creative_media_url(creative):
        return (
            getattr(creative, "thumbnail_url", None)
            or getattr(creative, "image_url", None)
            or getattr(creative, "video_url", None)
            or ""
        )

    def _fatigue_from_metrics(frequency, ctr, roas, impressions):
        frequency = _num(frequency)
        ctr = _num(ctr)
        roas = _num(roas)
        impressions = _num(impressions)
        if frequency:
            return min(100, int(frequency * 12))
        if impressions >= 50000 and ctr < 0.8:
            return 72
        if impressions >= 20000 and ctr < 1.2:
            return 55
        if ctr > 2 or roas > 2:
            return 18
        return 28 if impressions else 0

    def _creative_status_from_metrics(score, roas, ctr, fatigue, conversions):
        score = _num(score)
        roas = _num(roas)
        ctr = _num(ctr)
        fatigue = _num(fatigue)
        conversions = _num(conversions)

        if fatigue >= 65:
            return {
                "key": "fatigue",
                "label": "Yorgun",
                "state": "bad",
                "reason": "Yorgunluk 65%+",
            }
        if roas >= 2 and ctr >= 1.2 and fatigue < 50:
            return {
                "key": "scale",
                "label": "Ölçeklenebilir",
                "state": "good",
                "reason": "ROAS 2+ · CTR 1.2%+ · yorgunluk düşük",
            }
        if conversions > 0 and roas >= 1.5:
            return {
                "key": "conversion",
                "label": "Dönüştüren",
                "state": "good",
                "reason": "Dönüşüm var · ROAS 1.5+",
            }
        if roas < 1 and ctr < 0.8:
            return {
                "key": "weak",
                "label": "Zayıf",
                "state": "bad",
                "reason": "ROAS 1 altı · CTR 0.8% altı",
            }
        return {
            "key": "watch",
            "label": "İzlenmeli",
            "state": "mid",
            "reason": "Orta sinyal · karar için takip gerekir",
        }

    def _add_creative_card(creative, metrics, source_label):
        if not creative:
            return

        ctr = _num(metrics.get("avg_ctr"))
        roas = _num(metrics.get("avg_roas"))
        frequency = _num(metrics.get("avg_frequency"))
        impressions = _num(metrics.get("total_impressions"))
        clicks = _num(metrics.get("total_clicks"))
        spend = _num(metrics.get("total_spend"))
        revenue = _num(metrics.get("total_revenue"))
        conversions = _num(metrics.get("total_conversions"))
        reach = _num(metrics.get("total_reach"))

        ctr = round((clicks / impressions) * 100, 2) if impressions else 0
        roas = round(revenue / spend, 2) if spend else 0
        frequency = round(impressions / reach, 2) if reach else frequency

        fatigue = _fatigue_from_metrics(frequency, ctr, roas, impressions)

        # Gerçek sinyal yoksa kart basma.
        if ctr == 0 and roas == 0 and impressions == 0 and clicks == 0 and spend == 0:
            return

        score = _score_from_roas_ctr(roas, ctr)
        star_count = max(1, min(5, round((score / 100) * 5)))
        status = _creative_status_from_metrics(score, roas, ctr, fatigue, conversions)

        # Popup/kart için kreatife bağlı aktif kampanya bilgisini bul.
        active_ad = (
            own_ads.filter(creative_id=creative.id)
            .filter(active_ad_campaign_filter)
            .select_related("campaign", "ad_group", "ad_group__campaign", "platform_account", "platform_account__platform")
            .order_by("-updated_at", "-created_at")
            .first()
        )
        campaign = getattr(active_ad, "campaign", None) or getattr(getattr(active_ad, "ad_group", None), "campaign", None)
        ad_group = getattr(active_ad, "ad_group", None)
        platform_name = "-"
        try:
            if active_ad and active_ad.platform_account and active_ad.platform_account.platform:
                platform_name = active_ad.platform_account.platform.name
        except Exception:
            platform_name = "-"

        creative_wall.append({
            "id": creative.id,
            "name": str(creative)[:70],
            "image_url": _creative_media_url(creative),
            "ctr": ctr,
            "roas": roas,
            "fatigue": fatigue,
            "stars": "★" * star_count + "☆" * (5 - star_count),
            "score": score,
            "impressions": int(impressions),
            "clicks": int(clicks),
            "spend": spend,
            "revenue": revenue,
            "conversions": conversions,
            "source": source_label,
            "status_key": status["key"],
            "status_label": status["label"],
            "status_state": status["state"],
            "status_reason": status["reason"],
            "recommended_action": status["reason"],
            "campaign_name": getattr(campaign, "name", "Kampanya bulunamadı"),
            "campaign_id": getattr(campaign, "id", None),
            "campaign_status": getattr(campaign, "status", "ACTIVE"),
            "ad_id": getattr(active_ad, "id", None),
            "adgroup_name": getattr(ad_group, "name", "Reklam grubu bulunamadı"),
            "ad_name": getattr(active_ad, "name", "Reklam bulunamadı"),
            "platform": platform_name,
        })
        creative_seen_ids.add(creative.id)

    creative_metric_rows = (
        CreativeMetricHistory.objects.filter(
            creative_id__in=active_campaign_creative_ids,
            date__gte=start_date,
            date__lte=today,
        )
        .values("creative_id")
        .annotate(
            avg_frequency=Avg("frequency"),
            total_spend=Sum("spend"),
            total_clicks=Sum("clicks"),
            total_impressions=Sum("impressions"),
            total_reach=Sum("reach"),
            total_revenue=Sum("conversion_value"),
            total_conversions=Sum("conversions"),
            last_metric_date=Max("date"),
        )
        .order_by("-last_metric_date")
    )

    creative_ids = [row["creative_id"] for row in creative_metric_rows if row.get("creative_id")]
    creative_map = Creative.objects.filter(id__in=creative_ids).in_bulk()

    for row in creative_metric_rows:
        creative = creative_map.get(row.get("creative_id"))
        _add_creative_card(creative, row, "CreativeMetricHistory")

    # Fallback: CreativeMetricHistory seçilen dönemde eksikse AdMetricHistory üzerinden kreatif performansı üret.
    # Burada da hem ad.campaign hem ad.ad_group.campaign yolu desteklenir.
    if len(creative_wall) < len(active_campaign_creative_ids):
        ad_metric_campaign_filter = (
            Q(ad__campaign__status__iexact="ACTIVE") |
            Q(ad__campaign__status__iexact="ENABLED") |
            Q(ad__ad_group__campaign__status__iexact="ACTIVE") |
            Q(ad__ad_group__campaign__status__iexact="ENABLED")
        )
        ad_metric_rows = (
            AdMetricHistory.objects.filter(
                ad__in=own_ads,
                ad__source_type="OWN",
                ad__creative__isnull=False,
                ad__creative_id__in=active_campaign_creative_ids,
                date__gte=start_date,
                date__lte=today,
            )
            .filter(ad_metric_campaign_filter)
            .values("ad__creative_id")
            .annotate(
                avg_frequency=Avg("frequency"),
                total_spend=Sum("spend"),
                total_clicks=Sum("clicks"),
                total_impressions=Sum("impressions"),
                total_reach=Sum("reach"),
                total_revenue=Sum("conversion_value"),
                total_conversions=Sum("conversions"),
                last_metric_date=Max("date"),
            )
            .order_by("-last_metric_date")
        )

        fallback_ids = [row["ad__creative_id"] for row in ad_metric_rows if row.get("ad__creative_id")]
        fallback_map = Creative.objects.filter(id__in=fallback_ids).in_bulk()

        for row in ad_metric_rows:
            creative_id = row.get("ad__creative_id")
            if creative_id in creative_seen_ids:
                continue
            creative = fallback_map.get(creative_id)
            _add_creative_card(creative, row, "AdMetricHistory")

    creative_wall = sorted(
        creative_wall,
        key=lambda item: (
            str(item.get("status_key") or ""),
            _num(item.get("score")),
            _num(item.get("roas")),
            _num(item.get("ctr")),
            _num(item.get("impressions")),
        ),
        reverse=True,
    )

    creative_wall_segment_order = [
        ("scale", "good", "fa-rocket", "Ölçeklenebilir", "Ölçek", "Büyütülebilir kreatifler", "ROAS 2+ · CTR 1.2%+ · yorgunluk düşük"),
        ("conversion", "good", "fa-bullseye", "Dönüştüren", "Dönüşüm", "Satış/dönüşüm üreten kreatifler", "Dönüşüm var · ROAS 1.5+"),
        ("watch", "mid", "fa-eye", "İzlenmeli", "İzle", "Karar için takip gereken kreatifler", "Orta sinyal · karar için takip gerekir"),
        ("fatigue", "bad", "fa-battery-quarter", "Yorgun", "Yorgun", "Frekans/yorgunluk riski taşıyan kreatifler", "Yorgunluk 65%+"),
        ("weak", "bad", "fa-triangle-exclamation", "Zayıf", "Zayıf", "Performansı zayıf kreatifler", "ROAS 1 altı · CTR 0.8% altı"),
    ]
    creative_wall_segment_cards = []
    creative_wall_stats = {"total": len(creative_wall), "scale": 0, "convert": 0, "watch": 0, "fatigue": 0, "weak": 0}
    for key, state, icon, title, short_label, subtitle, note in creative_wall_segment_order:
        rows = [item for item in creative_wall if item.get("status_key") == key]
        stats_key = "convert" if key == "conversion" else key
        creative_wall_stats[stats_key] = len(rows)
        creative_wall_segment_cards.append({
            "key": key,
            "state": state,
            "icon": icon,
            "title": title,
            "short_label": short_label,
            "subtitle": subtitle,
            "note": note,
            "rows": rows,
            "count": len(rows),
        })

    # Performans Trendi: seçilen periyoda göre tamamen veritabanından hesaplanır.
    trend_days = _period_days(active_period)
    trend_start = today - timedelta(days=trend_days - 1)
    trend_prev_start = trend_start - timedelta(days=trend_days)
    trend_prev_end = trend_start - timedelta(days=1)

    trend_metrics, _trend_source = _performance_queryset(user, trend_start, today)
    trend_prev_metrics, _trend_prev_source = _performance_queryset(user, trend_prev_start, trend_prev_end)

    trend_summary = _aggregate_performance(trend_metrics)
    trend_prev_summary = _aggregate_performance(trend_prev_metrics)
    trend_totals = {"spend": trend_summary["total_spend"], "roas": trend_summary["avg_roas"], "revenue": trend_summary["total_revenue"]}
    trend_prev_totals = {"spend": trend_prev_summary["total_spend"], "roas": trend_prev_summary["avg_roas"], "revenue": trend_prev_summary["total_revenue"]}

    # Performans trendi Campaign Center ile tutarlı olması için sadece reklam/kampanya
    # conversion_value verisini kullanır. GA4 bu sayfada hiçbir hesaplamaya dahil edilmez.
    trend_revenue = trend_totals.get("revenue") or 0
    trend_prev_revenue = trend_prev_totals.get("revenue") or 0

    trend_spend = trend_totals["spend"] or 0
    trend_prev_spend = trend_prev_totals["spend"] or 0
    trend_roas = _safe_div(trend_revenue, trend_spend) or (trend_totals["roas"] or 0)
    trend_prev_roas = _safe_div(trend_prev_revenue, trend_prev_spend) or (trend_prev_totals["roas"] or 0)

    # Mini barlar da sabit değil; seçilen periyodun kendi gerçek kayıtlarından oluşturulur.
    if active_period == "daily":
        bucket_count = 1
        bucket_size = 1
    elif active_period == "weekly":
        bucket_count = 7
        bucket_size = 1
    elif active_period == "monthly":
        bucket_count = 5
        bucket_size = 6
    else:
        bucket_count = 3
        bucket_size = 30

    spend_series = []
    revenue_series = []
    roas_series = []

    for index in range(bucket_count):
        bucket_start = trend_start + timedelta(days=index * bucket_size)
        bucket_end = min(today, bucket_start + timedelta(days=bucket_size - 1))

        bucket_qs, _bucket_source = _performance_queryset(user, bucket_start, bucket_end)
        bucket_summary = _aggregate_performance(bucket_qs)
        bucket_ads = {"spend": bucket_summary["total_spend"], "roas": bucket_summary["avg_roas"]}

        bucket_revenue = bucket_summary["total_revenue"] or 0

        bucket_spend = bucket_ads["spend"] or 0
        bucket_roas = _safe_div(bucket_revenue, bucket_spend) or (bucket_ads["roas"] or 0)

        spend_series.append(bucket_spend)
        revenue_series.append(bucket_revenue)
        roas_series.append(bucket_roas)

    trend_spend_delta = _pct_change(trend_spend, trend_prev_spend)
    trend_revenue_delta = _pct_change(trend_revenue, trend_prev_revenue)
    trend_roas_delta = _pct_change(trend_roas, trend_prev_roas)

    trend = {
        "active_period": active_period,
        "period_label": _period_label(active_period),
        "date_label": f"{trend_start.strftime('%d.%m.%Y')} - {today.strftime('%d.%m.%Y')}",
        "spend": trend_spend,
        "revenue": trend_revenue,
        "roas": trend_roas,
        "spend_delta": trend_spend_delta,
        "revenue_delta": trend_revenue_delta,
        "roas_delta": trend_roas_delta,
        "spend_label": _delta_text(trend_spend_delta),
        "revenue_label": _delta_text(trend_revenue_delta),
        "roas_label": _delta_text(trend_roas_delta),
        # Harcama artışı her zaman iyi/kötü değildir; nötr gösterilir.
        # Gelir ve ROAS artışı iyi kabul edilir.
        "spend_delta_class": "neutral",
        "revenue_delta_class": _delta_class(trend_revenue_delta, True),
        "roas_delta_class": _delta_class(trend_roas_delta, True),
        "spend_bars": _bar_heights(spend_series),
        "revenue_bars": _bar_heights(revenue_series),
        "roas_bars": _bar_heights(roas_series),
    }

    # Octo AI Radar V2
    # Radar artık tek tek KPI değerlerinin kendisini değil, normalize edilmiş 0-100 sağlık skorunu gösterir.
    # Üst KPI kartları ile çelişmemesi için ROAS/CTR/Dönüşüm aynı hesaplardan beslenir.
    # Control Tower ana skorları sadece reklam veritabanı metriklerinden hesaplanır.
    # GA4 hiçbir şekilde fallback veya alternatif kaynak olarak kullanılmaz.
    effective_roas = _num(avg_roas)
    effective_conversion_rate = _num(conversion_rate)
    creative_score = (
        int(sum([_num(c.get("score")) for c in creative_wall]) / len(creative_wall))
        if creative_wall
        else _score_from_roas_ctr(avg_roas, avg_ctr)
    )

    # Hedef eşikleri: ticari dashboard için okunabilir sağlık skorları.
    # ROAS 5.00 = 100, CTR 3.00% = 100, dönüşüm 5.00% = 100 kabul edilir.
    budget_score = _inverse_score(abs(spend_delta), 10, 60) if total_spend else 50
    roas_score = _score(effective_roas, 5)
    conversion_score = _score(effective_conversion_rate, 5)
    ctr_score = _score(avg_ctr, 3)

    # Rakip baskısı ters skordur: çok rakip reklamı = daha düşük sağlık.
    competitor_ad_count = competitor_ads.count()
    competitor_score = _inverse_score(competitor_ad_count, 0, 40) if competitor_ad_count else 100
    if not has_performance_data:
        budget_score = 0
        roas_score = 0
        conversion_score = 0
        creative_score = 0
        competitor_score = 0
        ctr_score = 0

    # Radar eksen sırası SVG ile aynıdır: Harcama, Gelir, Dönüşüm, Creative, Rekabet, Hedefleme.
    radar_values = [budget_score, roas_score, conversion_score, creative_score, competitor_score, ctr_score]
    radar_avg_score = _weighted_avg([
        (budget_score, 20),
        (roas_score, 20),
        (conversion_score, 20),
        (creative_score, 15),
        (competitor_score, 15),
        (ctr_score, 10),
    ])
    radar_state_class, radar_state_label = _radar_state(radar_avg_score)

    radar_items = [
        {
            "key": "spend", "label": "Harcama", "value": budget_score, "raw": f"{spend_delta}%",
            "icon": "fas fa-wallet", "weight": 20,
            "tip": "Harcama verimliliği, seçilen dönem ile önceki dönem harcama değişiminin dengeli olup olmadığını ölçer. Ani harcama sıçramaları skoru düşürür.",
        },
        {
            "key": "revenue", "label": "Gelir", "value": roas_score, "raw": round(effective_roas, 2),
            "icon": "fas fa-arrow-trend-up", "weight": 20,
            "tip": "Gelir etkinliği ROAS üzerinden skorlanır. ROAS 5.00 ve üzeri 100 puan kabul edilir.",
        },
        {
            "key": "conversion", "label": "Dönüşüm", "value": conversion_score, "raw": f"{round(effective_conversion_rate, 2)}%",
            "icon": "fas fa-users", "weight": 20,
            "tip": "Dönüşüm kalitesi, dönüşüm oranı üzerinden hesaplanır. Dönüşüm oranı = conversions / clicks x 100.",
        },
        {
            "key": "creative", "label": "Creative", "value": creative_score, "raw": f"{len(creative_wall)} kreatif",
            "icon": "fas fa-paintbrush", "weight": 15,
            "tip": "Creative performansı, kreatif skorlarının ortalamasından gelir. Veri yoksa ROAS ve CTR tabanlı güvenli fallback kullanılır.",
        },
        {
            "key": "competition", "label": "Rekabet", "value": competitor_score, "raw": competitor_ad_count,
            "icon": "fas fa-trophy", "weight": 15,
            "tip": "Rekabet gücü ters skorlanır. Rakip reklam yoğunluğu arttıkça rekabet baskısı yükselir ve skor düşer.",
        },
        {
            "key": "targeting", "label": "Hedefleme", "value": ctr_score, "raw": f"{round(_num(avg_ctr), 2)}%",
            "icon": "fas fa-crosshairs", "weight": 10,
            "tip": "Hedefleme kalitesi CTR ile okunur. CTR 3.00% ve üzeri 100 puan kabul edilir.",
        },
    ]
    for item in radar_items:
        item["state_class"], item["state_label"] = _radar_state(item["value"])

    radar = {
        "budget": budget_score,
        "roas": roas_score,
        "creative": creative_score,
        "conversion": conversion_score,
        "competitor": competitor_score,
        "ctr": ctr_score,
        "polygon_points": _radar_polygon(radar_values),
        "avg_score": radar_avg_score,
        "state_class": radar_state_class,
        "state_label": radar_state_label,
        "items": radar_items,
    }

    # Octo AI Skoru V2
    # Bu skor artık yalnızca OctoScoreHistory veya basit ROAS/CTR fallback'ine bağlı değildir.
    # Performans, maliyet, dönüşüm, creative sağlık, bütçe dengesi, rakip baskısı,
    # kritik uyarılar ve bekleyen Octo görevleri birlikte değerlendirilir.
    octo_ai_result = _octo_ai_score_engine(
        roas=effective_roas,
        ctr=avg_ctr,
        cpc=avg_cpc,
        conversion_rate=effective_conversion_rate,
        spend_delta=spend_delta,
        creative_score=creative_score,
        competitor_ad_count=competitor_ad_count,
        critical_alert_count=real_critical_alert_count,
        pending_ai_tasks=octo_task_center_stats.get("open", 0),
        high_ai_tasks=octo_task_center_stats.get("critical", 0),
    )

    octo_score = octo_ai_result["score"]
    octo_label = octo_ai_result["label"]
    octo_components = octo_ai_result["components"]

    # Octo değişimi, kayıtlı eski OctoScoreHistory yerine seçilen periyodun önceki dönem verisiyle hesaplanır.
    # Böylece Günlük / Haftalık / Aylık / 3 Aylık seçimlerinde skor gerçek veriye göre değişir.
    prev_effective_roas = _num(prev_totals["avg_roas"])
    prev_effective_ctr = _num(prev_totals["avg_ctr"])
    prev_effective_cpc = _num(prev_totals["avg_cpc"])
    prev_creative_score = _score_from_roas_ctr(prev_effective_roas, prev_effective_ctr)

    prev_octo_ai_result = _octo_ai_score_engine(
        roas=prev_effective_roas,
        ctr=prev_effective_ctr,
        cpc=prev_effective_cpc,
        conversion_rate=_num(prev_conversion_rate),
        spend_delta=0,
        creative_score=prev_creative_score,
        competitor_ad_count=competitor_ad_count,
        critical_alert_count=0,
        pending_ai_tasks=0,
        high_ai_tasks=0,
    )
    octo_delta = _pct_change(octo_score, prev_octo_ai_result["score"])
    if not has_performance_data:
        octo_score = 0
        octo_label = "Hazır"
        octo_components = {}
        octo_delta = 0

    base_query_params = request.GET.copy()
    base_query_params.pop("export", None)
    base_query_params.pop("ai_refresh", None)
    export_params = base_query_params.copy()
    export_params["export"] = "pdf"

    def _period_url(period_key):
        days = _period_days(period_key)
        start = today_real - timedelta(days=days - 1)
        end = today_real
        return f"?period={period_key}&date_from={start.strftime('%Y-%m-%d')}&date_to={end.strftime('%Y-%m-%d')}"

    period_links = {
        "daily": _period_url("daily"),
        "weekly": _period_url("weekly"),
        "monthly": _period_url("monthly"),
        "quarterly": _period_url("quarterly"),
    }


    context = {
        "filters": {
            "active_period": active_period,
            "date_from": start_date.strftime("%Y-%m-%d"),
            "date_to": today.strftime("%Y-%m-%d"),
            "date_label": f"{start_date.strftime('%d.%m.%Y')} - {today.strftime('%d.%m.%Y')}",
            "selected_days": selected_days,
            "today": today_real.strftime("%Y-%m-%d"),
            "period_label": _period_label(active_period),
            "metric_source": metric_source,
        },
        "has_performance_data": has_performance_data,
        "period_links": period_links,
        "platform_strip_cards": platform_strip_cards,
        "export_query": export_params.urlencode(),
        "summary": {
            "platform_connections": platform_accounts_for_request(request, active_only=True).exclude(connection__isnull=True).values("connection_id").distinct().count(),
            "platform_accounts": platform_accounts_for_request(request, active_only=True).count(),
            "campaigns": scope_queryset(request, Campaign.objects.all()).count(),
            "ad_groups": scope_queryset(request, AdGroup.objects.all(), account_lookup="campaign__platform_account").count(),
            "creatives": scope_queryset(request, Creative.objects.all()).count(),
            "own_ads": own_ads.count(),
            "active_ads": own_ads.filter(is_active=True).count(),
            "competitor_ads": competitor_ads.count(),
            "total_impressions": total_impressions,
            "total_clicks": total_clicks,
            "total_spend": total_spend,
            "total_revenue": totals["total_revenue"] or 0,
            "total_conversions": total_conversions,
            "avg_roas": avg_roas,
            "avg_ctr": avg_ctr,
            "avg_cpc": avg_cpc,
            "avg_cpm": totals["avg_cpm"] or 0,
            "conversion_rate": conversion_rate,
            "octo_score": octo_score,
            "octo_label": octo_label,
            "octo_components": octo_components,
            "octo_score_level_class": _score_level_class(octo_score),
            "octo_score_direction_class": _delta_class(octo_delta, True),
            "octo_delta": octo_delta,
            "octo_delta_abs": abs(octo_delta),
            "octo_delta_label": _delta_text(octo_delta),
            "octo_delta_class": _delta_class(octo_delta, True),
            "roas_delta_label": _delta_text(roas_delta),
            "roas_delta_class": _delta_class(roas_delta, True),
            "ctr_delta_label": _delta_text(ctr_delta),
            "ctr_delta_class": _delta_class(ctr_delta, True),
            "cpc_delta_label": _delta_text(cpc_delta),
            "cpc_delta_class": _delta_class(cpc_delta, False),
            "conversion_rate_delta_label": _delta_text(conversion_rate_delta),
            "conversion_rate_delta_class": _delta_class(conversion_rate_delta, True),
            "conversion_count_delta_label": _delta_text(conversion_count_delta),
            "conversion_count_delta_class": _delta_class(conversion_count_delta, True),
            # Geriye dönük template uyumluluğu: mevcut conversion_* alanları oranı temsil eder.
            "conversion_delta_label": _delta_text(conversion_rate_delta),
            "conversion_delta_class": _delta_class(conversion_rate_delta, True),
            "spend_delta_label": _delta_text(spend_delta),
            "spend_delta_class": _delta_class(spend_delta, True),
            "click_delta_label": _delta_text(click_delta),
            "click_delta_class": _delta_class(click_delta, True),
            "impression_delta_label": _delta_text(impression_delta),
            "impression_delta_class": _delta_class(impression_delta, True),
            "roas_delta": roas_delta,
            "roas_delta_abs": abs(roas_delta),
            "ctr_delta": ctr_delta,
            "ctr_delta_abs": abs(ctr_delta),
            "cpc_delta": cpc_delta,
            "cpc_delta_abs": abs(cpc_delta),
            "conversion_delta": conversion_rate_delta,
            "conversion_delta_abs": abs(conversion_rate_delta),
            "conversion_count_delta": conversion_count_delta,
            "conversion_count_delta_abs": abs(conversion_count_delta),
            "spend_label": _label(spend_delta),
            "click_label": _label(click_delta),
            "impression_label": _label(impression_delta),
            "conversion_label": _label(conversion_rate_delta),
            "conversion_count_label": _label(conversion_count_delta),
            "roas_label": _label(roas_delta),
        },
        "live_performance": {
            "spend": total_spend,
            "revenue": totals["total_revenue"] or 0,
            "roas": avg_roas,
            "conversions": total_conversions,
            "conversion_rate": conversion_rate,
            "clicks": total_clicks,
            "impressions": total_impressions,
        },
        "radar": radar,
        "campaign_health": campaign_health,
        "campaign_health_count": campaign_health_count,
        "risk_campaigns": risk_campaigns,
        "watch_campaigns": watch_campaigns,
        "healthy_campaigns": healthy_campaigns,
        "campaign_health_segments": campaign_health_segments,
        "campaign_health_segment_cards": campaign_health_segment_cards,
        "critical_alerts": critical_alerts,
        "control_alert_center": control_alert_center,
        "octo_task_center_tasks": octo_task_center_tasks,
        "octo_task_center_sections": octo_task_center_sections,
        "octo_task_center_stats": octo_task_center_stats,
        "competitor_rows": competitor_rows,
        "competitor_ad_groups": competitor_ad_groups,
        "competitor_intelligence": competitor_intelligence,
        "today_summary": today_summary,
        "creative_wall": creative_wall,
        "creative_wall_segment_cards": creative_wall_segment_cards,
        "creative_wall_stats": creative_wall_stats,
        "trend": trend,
    }

    context["refresh_meta"] = _control_tower_refresh_meta(
        user,
        active_period,
        start_date,
        today,
        agency_client=agency_scope.selected_client,
    )

    if build_decision_center_from_context:
        context["decision_center"] = build_decision_center_from_context(context)
    else:
        context["decision_center"] = {
            "title_tr": "OCTO KARAR MERKEZİ",
            "title_en": "OCTO DECISION CENTER",
            "updated_at": timezone.localtime().strftime("%d.%m.%Y %H:%M"),
            "metrics": [],
            "items": [],
        }

    # Octo AI raporu dashboard açılışında yeniden üretilmez; hazır DB kaydı okunur.
    # "Analiz Et" tıklandığında ise mevcut Control Tower context'i ile TAM analiz üretilir,
    # DB'ye kaydedilir ve sayfa temiz URL ile yenilenir. Böylece özet/spinner alanında takılma olmaz.
    context["ai_report_generated"] = False
    context["octo_ai_report"] = None
    ai_pdf_params = base_query_params.copy()
    ai_pdf_params["export"] = "ai_pdf"
    ai_refresh_params = base_query_params.copy()
    ai_refresh_params["ai_refresh"] = "1"
    context["octo_ai_report_pdf_query"] = ai_pdf_params.urlencode()
    context["octo_ai_refresh_query"] = ai_refresh_params.urlencode()

    if request.GET.get("ai_refresh") == "1":
        # Stabil akış: Analiz Et butonu AJAX/polling kullanmaz.
        # Sunucu mevcut Control Tower context'i ile analizi üretir, DB'ye yazar
        # ve temiz URL'ye döner. Böylece %92/spinner/özet takılması yaşanmaz.
        deep_ai_context = _control_tower_deep_ai_context(context)
        deep_ai_digest = (deep_ai_context.get("data_coverage") or {}).get("source_digest", "")
        cached_analysis = None
        if ControlTowerAIAnalysis is not None and request.GET.get("force_ai") != "1":
            try:
                tariff = AIOperationTariff.objects.get(key="control-tower-analysis", is_active=True)
                cache_cutoff = timezone.now() - timedelta(seconds=int(tariff.cache_timeout_seconds or 0))
                cached_analysis = (
                    ControlTowerAIAnalysis.objects.filter(
                        snapshot__user=user,
                        snapshot__period=active_period,
                        snapshot__date_from=start_date,
                        snapshot__date_to=today,
                        analysis_type="deep_ai_ecosystem",
                        created_at__gte=cache_cutoff,
                    )
                    .order_by("-created_at", "-id")
                    .first()
                )
                cached_digest = (((cached_analysis.payload or {}).get("data_coverage") or {}).get("source_digest", "")) if cached_analysis else ""
                if cached_analysis and cached_digest != deep_ai_digest:
                    cached_analysis = None
            except Exception:
                cached_analysis = None

        if cached_analysis:
            done_params = base_query_params.copy()
            done_params["ai_done"] = "1"
            done_params["ai_cached"] = "1"
            done_url = request.path + "?" + done_params.urlencode() + "#octoAiAnalysisReport"
            return HttpResponseRedirect(done_url)
        elif not has_performance_data:
            context["octo_ai_report_error"] = "Analiz icin performans verisi bulunamadi."
        elif (guard := _control_tower_ai_guard(request)):
            if guard["payload"].get("error") == "insufficient_ai_credits":
                from django.contrib import messages
                messages.warning(request, "AI kredi bakiyeniz yetersiz. Devam etmek için ek kredi paketi seçin.")
                return HttpResponseRedirect(ai_credit_purchase_url())
            context["octo_ai_report_error"] = guard["payload"].get("message") or "Octo AI analizi baslatilamadi."
        elif save_snapshot_from_context is None:
            context["octo_ai_report_error"] = "Octo AI snapshot servisi import edilemedi."
        else:
            try:
                new_snapshot = save_snapshot_from_context(
                    user,
                    active_period,
                    start_date,
                    today,
                    context,
                    agency_client=agency_scope.selected_client,
                )
                try:
                    report, _ai_snapshot = _build_octo_ai_report_from_latest_snapshot(
                        user,
                        active_period,
                        start_date,
                        today,
                        agency_client=agency_scope.selected_client,
                    )
                    executive_summary = _build_executive_summary_from_context({
                        **context,
                        "octo_ai_report": report,
                    })
                    from openai import OpenAI
                    real_ai = run_sixteen_agent_orchestration(
                        client=OpenAI(api_key=settings.OPENAI_API_KEY, timeout=60, max_retries=2),
                        model=settings.OPENAI_MODEL,
                        task="Tum Control Tower verilerini capraz analiz et; kanitli bulgu, risk ve oncelikli aksiyon ver.",
                        context=deep_ai_context,
                        modalities=["text"],
                        reference="control_tower.deep_analysis",
                        user=request.user,
                        organization=_control_tower_ai_organization(request, agency_scope),
                        # 16 parallel calls must stay below the account's 30k TPM
                        # ceiling. The strict four-field JSON fits this budget.
                        max_tokens_per_agent=160,
                        tariff_key="control-tower-analysis",
                    )
                    ai_rows = real_ai.get("agents") or []
                    deep_context = deep_ai_context
                    average_confidence = round(
                        sum(row.get("confidence", 0) for row in ai_rows) / len(ai_rows) * 100
                    ) if ai_rows else 0
                    _safe_create_ai_analysis(
                        snapshot=_ai_snapshot or new_snapshot,
                        card_key="deep_ai_ecosystem",
                        analysis_type="deep_ai_ecosystem",
                        title_tr="16 Ajanli Octo Derin Analiz",
                        title_en="16-Agent Octo Deep Analysis",
                        analysis_tr="\n".join(
                            f"{row.get('name', 'Ajan')}: {row.get('finding', '')}" for row in ai_rows
                        ),
                        recommendation_tr="\n".join(
                            f"{row.get('name', 'Ajan')}: {row.get('recommendation', '')}" for row in ai_rows
                        ),
                        what_happened="\n".join(row.get("finding", "") for row in ai_rows),
                        root_cause="\n".join(row.get("risk", "") for row in ai_rows if row.get("risk")),
                        action_plan="\n".join(row.get("recommendation", "") for row in ai_rows),
                        expected_impact="16 uzman ajanin tum Control Tower verilerini capraz analiz sonucu.",
                        severity="info",
                        priority="high",
                        status="active",
                        confidence=average_confidence,
                        payload={
                            "analysis_type": "deep_ai_ecosystem",
                            "agents": ai_rows,
                            "strategy": real_ai.get("strategy") or {},
                            "data_coverage": deep_context.get("data_coverage") or {},
                            "complete_page_dataset": True,
                        },
                    )
                    if executive_summary:
                        executive_summary["ai_results"] = ai_rows
                        executive_summary["confidence"] = average_confidence
                        if ai_rows:
                            executive_summary["top_opportunity"] = {
                                "title": "Öncelikli AI fırsatı",
                                "detail": ai_rows[0].get("recommendation", ""),
                                "amount": executive_summary.get("potential_gain", 0),
                                "items": [row.get("recommendation", "") for row in ai_rows[:4]],
                            }
                            executive_summary["top_risk"] = {
                                "title": "Öncelikli AI riski",
                                "detail": next((row.get("risk") for row in ai_rows if row.get("risk")), ai_rows[0].get("finding", "")),
                                "amount": executive_summary.get("potential_loss", 0),
                                "items": [row.get("finding", "") for row in ai_rows[:4]],
                            }
                    _save_executive_summary_ai_record(_ai_snapshot or new_snapshot, executive_summary)
                except Exception as summary_exc:
                    refund_ai_tariff_credits(
                        user=request.user,
                        organization=_control_tower_ai_organization(request, agency_scope),
                        tariff_key="control-tower-analysis", reason=str(summary_exc),
                        reference="control_tower.ai_analysis",
                    )
                    context["octo_ai_report_error"] = f"Executive Summary kaydı yazılamadı: {summary_exc}"
                if not context.get("octo_ai_report_error"):
                    done_params = base_query_params.copy()
                    done_params["ai_done"] = "1"
                    done_url = request.path
                    query = done_params.urlencode()
                    if query:
                        done_url += "?" + query
                    done_url += "#octoAiAnalysisReport"
                    CacheService.bump_version("control_tower", user.id)
                    return HttpResponseRedirect(done_url)
            except Exception as exc:
                refund_ai_tariff_credits(
                    user=request.user,
                    organization=_control_tower_ai_organization(request, agency_scope),
                    tariff_key="control-tower-analysis", reason=str(exc),
                    reference="control_tower.ai_analysis",
                )
                context["octo_ai_report_error"] = str(exc)

    if has_performance_data and not context.get("octo_ai_report"):
        try:
            report, ai_snapshot = _build_octo_ai_report_from_latest_snapshot(
                user,
                active_period,
                start_date,
                today,
                agency_client=agency_scope.selected_client,
            )
            context["octo_ai_report"] = report
            context["ai_snapshot_id"] = getattr(ai_snapshot, "id", None)
        except Exception as exc:
            context["octo_ai_report_error"] = str(exc)

    context["executive_summary"] = _build_executive_summary_from_context(context) if has_performance_data else None
    cache_context = context
    context = _localize_control_tower_context(dict(context), current_language)

    if request.GET.get("export") == "ai_pdf":
        report = context.get("octo_ai_report")
        if report:
            report["executive_summary"] = context.get("executive_summary")
            return _build_octo_ai_analysis_pdf(
                report,
                branding=get_report_branding(request.user, agency_client=agency_scope.selected_client),
            )
        return HttpResponse("Önce Octo AI analizi üretmelisiniz.", status=404, content_type="text/plain; charset=utf-8")

    if request.GET.get("export") == "pdf" and build_control_tower_screenshot_pdf:
        return build_control_tower_screenshot_pdf(request)

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="kontrol-kulesi-raporu.csv"'
        response.write("\ufeff")
        writer = csv.writer(response, delimiter=";")
        writer.writerow(["Kontrol Kulesi Raporu", context["filters"]["date_label"]])
        writer.writerow([])
        writer.writerow(["Özet KPI", "Değer"])
        writer.writerow(["Octo AI Skoru", context["summary"]["octo_score"]])
        writer.writerow(["ROAS", context["summary"]["avg_roas"]])
        writer.writerow(["CPC", context["summary"]["avg_cpc"]])
        writer.writerow(["CTR", context["summary"]["avg_ctr"]])
        writer.writerow(["Dönüşüm Oranı", context["summary"]["conversion_rate"]])
        writer.writerow(["Harcama", context["summary"]["total_spend"]])
        writer.writerow(["Tıklama", context["summary"]["total_clicks"]])
        writer.writerow(["Gösterim", context["summary"]["total_impressions"]])
        writer.writerow([])
        writer.writerow(["Performans Trendi", "Değer", "Değişim"])
        writer.writerow(["Harcama", trend["spend"], trend["spend_label"]])
        writer.writerow(["Gelir", trend["revenue"], trend["revenue_label"]])
        writer.writerow(["ROAS", trend["roas"], trend["roas_label"]])
        writer.writerow([])
        writer.writerow(["Creative", "CTR", "ROAS", "Yorgunluk", "Skor"])
        for creative in creative_wall:
            writer.writerow([creative["name"], creative["ctr"], creative["roas"], creative["fatigue"], creative["score"]])
        writer.writerow([])
        writer.writerow(["Radar", "Skor", "Ham Değer"])
        for item in radar["items"]:
            writer.writerow([item["label"], item["value"], item["raw"]])
        return response

    if control_tower_cache_enabled:
        CacheService.set(
            "control_tower",
            *control_tower_cache_key_parts,
            value=cache_context,
            timeout=CONTROL_TOWER_CACHE_TIMEOUT,
            version=control_tower_cache_version,
        )
    return render(request, "dashboard/control_tower.html", context)

@login_required
def control_tower_archive(request):
    """Control Tower AI arşivi.

    Arşiv yeni analiz üretmez. Dashboard'da kullanılan ControlTowerAIAnalysis
    kayıtlarını tarih/saat sırasıyla raporlar ve seçilen kayıttan PDF üretir.
    """
    if ControlTowerAIAnalysis is None:
        return render(request, "dashboard/control_tower/archive.html", {
            "records": [],
            "selected": None,
            "total_count": 0,
            "active_type": "all",
            "tabs": [],
            "per_page": 10,
            "page_size_options": [10, 20, 50, 100],
            "error": "ControlTowerAIAnalysis modeli import edilemedi.",
        })

    user = request.user
    active_type = request.GET.get("type") or "all"
    selected_id = request.GET.get("id")
    page_size_options = [10, 20, 50, 100]
    try:
        per_page = int(request.GET.get("per_page") or 10)
    except Exception:
        per_page = 10
    if per_page not in page_size_options:
        per_page = 10

    agency_scope = get_agency_scope(request)
    base_qs = ControlTowerAIAnalysis.objects.filter(snapshot__user=user)
    if agency_scope.is_agency:
        base_qs = base_qs.filter(
            snapshot__summary__agency_client_id=(
                agency_scope.selected_client.id if agency_scope.selected_client else None
            )
        )
    base_qs = base_qs.order_by("-created_at", "-id")

    categories = [
        ("all", "Tümü", "fas fa-layer-group", None),
        ("executive_summary", "Executive Summary", "fas fa-chart-pie", ["executive_summary"]),
        ("strategic_advisor", "Strategic Advisor", "fas fa-brain", ["strategic_advisor", "decision_center", "kpi_strip"]),
        ("competitor_intelligence", "Competitor Intelligence", "fas fa-binoculars", ["competitor_intelligence"]),
        ("campaign_health", "Campaign Health", "fas fa-heart-pulse", ["campaign_health"]),
        ("creative_wall", "Creative Performance", "fas fa-wand-magic-sparkles", ["creative_wall", "creative"]),
    ]

    def _filter_by_keys(qs, keys):
        if not keys:
            return qs
        query = Q()
        for key in keys:
            query |= Q(analysis_type=key) | Q(card_key=key)
        return qs.filter(query)

    tabs = []
    key_map = {key: keys for key, _, _, keys in categories}
    if active_type not in key_map:
        active_type = "all"

    for key, label, icon, keys in categories:
        count = _filter_by_keys(base_qs, keys).count() if keys else base_qs.count()
        tabs.append({
            "key": key,
            "label": label,
            "icon": icon,
            "count": count,
            "active": key == active_type,
        })

    filtered_qs = _filter_by_keys(base_qs, key_map.get(active_type))
    paginator = Paginator(filtered_qs, per_page)
    page_number = request.GET.get("page") or 1
    page_obj = paginator.get_page(page_number)
    records_qs = page_obj.object_list
    records = [_archive_analysis_to_row(item) for item in records_qs]

    selected_obj = None
    if selected_id:
        try:
            selected_qs = base_qs.filter(id=int(selected_id))
            selected_obj = selected_qs.first()
        except Exception:
            selected_obj = None
    if selected_obj is None and records:
        selected_obj = base_qs.filter(id=records[0]["id"]).first()

    selected = _archive_analysis_to_row(selected_obj) if selected_obj else None

    if request.GET.get("export") == "pdf" and selected:
        report = {
            "headline": selected.get("title_tr") or "Octo AI Arşiv Raporu",
            "created_at": selected.get("created_label"),
            "date_label": selected.get("created_label"),
            "overall_state": selected.get("state"),
            "octo_score": 0,
            "avg_confidence": selected.get("confidence", 0),
            "total_gain": selected.get("expected_gain", 0),
            "total_loss": selected.get("expected_loss", 0),
            "analyses": [{
                "title_tr": selected.get("title_tr"),
                "analysis_tr": selected.get("what_happened"),
                "recommendation_tr": selected.get("action_plan"),
                "severity": selected.get("severity"),
                "confidence": selected.get("confidence"),
                "state": selected.get("state"),
                "expected_gain": selected.get("expected_gain"),
                "expected_loss": selected.get("expected_loss"),
                "what_happened_items": selected.get("what_happened_items"),
                "why_happened_items": selected.get("root_cause_items"),
                "what_will_happen_items": selected.get("forecast_items"),
                "recommended_action_items": selected.get("recommended_action_items"),
                "expected_impact_items": selected.get("expected_impact_items"),
            }],
            "actions": [],
        }
        return _build_octo_ai_analysis_pdf(
            report,
            branding=get_report_branding(
                request.user,
                agency_client=get_agency_scope(request).selected_client,
            ),
        )

    return render(request, "dashboard/control_tower/archive.html", {
        "records": records,
        "selected": selected,
        "total_count": base_qs.count(),
        "filtered_count": filtered_qs.count(),
        "page_obj": page_obj,
        "paginator": paginator,
        "active_type": active_type,
        "tabs": tabs,
        "per_page": per_page,
        "page_size_options": page_size_options,
    })
