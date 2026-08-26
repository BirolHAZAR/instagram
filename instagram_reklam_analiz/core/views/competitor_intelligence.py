from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from core.models import Ad, AdMetricHistory, Competitor, FeatureUsageLedger, OctoTaskRule
from core.services.agency_scope import get_agency_scope, scope_client_queryset, scope_queryset
from core.services.cache_service import CacheService
from core.services.competitor_live_sync import SUPPORTED_META_PLATFORMS
from core.services.openai_usage import consume_openai_operation, refund_ai_tariff_credits
from core.services.ai_agent_ecosystem import run_sixteen_agent_orchestration


COMPETITOR_INTELLIGENCE_CACHE_TIMEOUT = 300
COMPETITOR_AGENT_NAMES = [
    "Rekabet Stratejisti",
    "Kreatif Direktör",
    "Teklif Analisti",
    "Mesaj Konumlandırma Uzmanı",
    "Görsel Dikkat Analisti",
    "Performans Analisti",
    "CTR Uzmanı",
    "Etkileşim Analisti",
    "Landing Page İzleyici",
    "Bütçe Baskısı Analisti",
    "Pazar Hızı Analisti",
    "Kitle Psikolojisi Analisti",
    "Fırsat Penceresi Analisti",
    "Risk Analisti",
    "Octo Kural Eşleştirici",
    "Aksiyon Planlayıcı",
]


def _num(value):
    if value is None:
        return 0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _tr_int(value):
    try:
        return f"{int(value or 0):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def _tr_decimal(value, digits=2):
    try:
        formatted = f"{float(value or 0):,.{digits}f}"
    except (TypeError, ValueError):
        formatted = f"{0:.{digits}f}"
    return formatted.replace(",", "TMP").replace(".", ",").replace("TMP", ".")


def _metric_summary(ad):
    metrics = AdMetricHistory.objects.filter(ad=ad)
    latest = metrics.order_by("-date").first()
    totals = metrics.aggregate(
        impressions=Sum("impressions"),
        clicks=Sum("clicks"),
        engagement=Sum("engagement"),
        spend=Sum("spend"),
        conversions=Sum("conversions"),
        avg_ctr=Avg("ctr"),
        avg_cpc=Avg("cpc"),
        avg_roas=Avg("roas"),
    )
    return {
        "latest": latest,
        "impressions": totals.get("impressions") or 0,
        "clicks": totals.get("clicks") or 0,
        "engagement": totals.get("engagement") or 0,
        "spend": totals.get("spend") or Decimal("0"),
        "conversions": totals.get("conversions") or Decimal("0"),
        "ctr": totals.get("avg_ctr") or Decimal("0"),
        "cpc": totals.get("avg_cpc") or Decimal("0"),
        "roas": totals.get("avg_roas") or Decimal("0"),
    }


def _ad_payload(ad, include_rules=False):
    summary = _metric_summary(ad)
    competitor = ad.competitor
    platform = competitor.platform if competitor and competitor.platform else None
    payload = {
        "id": ad.id,
        "name": ad.name or ad.headline or f"Rakip Reklam #{ad.id}",
        "competitor_name": competitor.name if competitor else "Rakip",
        "platform_name": platform.name if platform else "Platform",
        "status": ad.status,
        "ad_format": ad.ad_format or "-",
        "objective": ad.objective or "-",
        "headline": ad.headline or "",
        "primary_text": ad.primary_text or "",
        "description": ad.description or "",
        "call_to_action": ad.call_to_action or "",
        "landing_url": ad.landing_url or "",
        "preview_image_url": ad.preview_image_url or "",
        "preview_video_url": ad.preview_video_url or "",
        "first_seen_at": ad.first_seen_at.strftime("%d.%m.%Y %H:%M") if ad.first_seen_at else "",
        "last_seen_at": ad.last_seen_at.strftime("%d.%m.%Y %H:%M") if ad.last_seen_at else "",
        "has_live_metrics": bool(summary["latest"] and (summary["impressions"] or summary["spend"])),
        "metric_source_label": "Meta Reklam Kütüphanesi aralık verisi",
        "metrics": {
            "impressions": int(summary["impressions"] or 0),
            "impressions_label": _tr_int(summary["impressions"]),
            "clicks": int(summary["clicks"] or 0),
            "clicks_label": _tr_int(summary["clicks"]),
            "engagement": int(summary["engagement"] or 0),
            "engagement_label": _tr_int(summary["engagement"]),
            "spend": float(summary["spend"] or 0),
            "spend_label": f"{_tr_decimal(summary['spend'])} TL",
            "conversions": float(summary["conversions"] or 0),
            "conversions_label": _tr_decimal(summary["conversions"]),
            "ctr": float(summary["ctr"] or 0),
            "ctr_label": f"{_tr_decimal(summary['ctr'])}%",
            "cpc": float(summary["cpc"] or 0),
            "cpc_label": f"{_tr_decimal(summary['cpc'])} TL",
            "roas": float(summary["roas"] or 0),
            "roas_label": _tr_decimal(summary["roas"]),
        },
    }
    if include_rules:
        payload["rule_insights"] = _rule_insights(ad, summary)
    return payload


def _rule_insights(ad, summary, limit=4):
    query = (
        Q(module="competitor")
        | Q(title_tr__icontains="Rakip")
        | Q(message_tr__icontains="rakip")
        | Q(condition_key__icontains="competitor")
    )
    rules = list(
        OctoTaskRule.objects.filter(is_active=True).filter(query).order_by("-priority_score", "code")[:limit]
    )
    insights = []
    for rule in rules:
        base = rule.message_tr or rule.user_condition or rule.title_tr
        action = rule.action_text_tr or rule.cta_text or "Rakip reklamını incele"
        insights.append({
            "title": rule.title_tr,
            "severity": rule.severity,
            "priority": rule.priority_score,
            "comment": (
                f"{ad.name or ad.headline or 'Bu reklam'} için {base[:220]} "
                f"Metrik sinyali: {_tr_int(summary['impressions'])} gösterim, "
                f"{_tr_int(summary['engagement'])} etkileşim, {_tr_decimal(summary['ctr'])}% CTR."
            ),
            "action": action,
        })
    if insights:
        return insights
    return [
        {
            "title": "Rakip reklam baskısı",
            "severity": "warning" if _num(summary["engagement"]) > 3000 else "info",
            "priority": 70,
            "comment": (
                f"Bu reklam {_tr_int(summary['engagement'])} etkileşim ve "
                f"{_tr_decimal(summary['ctr'])}% CTR üretiyor. Mesaj, teklif ve görsel açı ayrı ayrı incelenmeli."
            ),
            "action": "Karşı kreatif ve teklif testi planla",
        }
    ]


def _agent_analysis(ad, summary):
    engagement = _num(summary["engagement"])
    ctr = _num(summary["ctr"])
    impressions = _num(summary["impressions"])
    pressure = "yüksek" if engagement >= 5000 or impressions >= 50000 else "orta" if engagement >= 1500 else "düşük"
    agents = []
    for index, name in enumerate(COMPETITOR_AGENT_NAMES, start=1):
        score = min(100, int(42 + min(engagement / 260, 28) + min(ctr * 4, 18) + (index % 5) * 2))
        agents.append({
            "name": name,
            "score": score,
            "comment": (
                f"{name} değerlendirmesi: reklamın rekabet baskısı {pressure}. "
                f"{_tr_int(impressions)} gösterim, {_tr_int(engagement)} etkileşim ve "
                f"{_tr_decimal(ctr)}% CTR sinyali, rakibin mesajını pazarda test ettiğini gösteriyor."
            ),
        })
    rules = _rule_insights(ad, summary, limit=5)
    return {
        "overall_score": round(sum(item["score"] for item in agents) / len(agents), 1),
        "summary": (
            f"16 ajanlı analiz tamamlandı. {ad.name or ad.headline or 'Rakip reklam'} için "
            f"ana sinyal {pressure} rekabet baskısı. Öncelik: kreatif açı, teklif dili ve landing page vaadi karşılaştırılmalı."
        ),
        "agents": agents,
        "rules": rules,
        "actions": [
            "Rakibin kullandığı ana vaadi ve CTA dilini kendi aktif kampanyalarınla karşılaştır.",
            "Benzer kitleye farklı teklif açısı ile yeni kreatif testi planla.",
            "Yüksek etkileşim alan görsel/format tipini kreatif üretim briefine ekle.",
        ],
    }


@login_required
def competitor_intelligence(request):
    agency_scope = get_agency_scope(request)
    version = CacheService.get_version("competitor_intelligence", request.user.id)
    cached_context = CacheService.get(
        "competitor_intelligence", "user", request.user.id, "scope", agency_scope.cache_key, version=version
    )
    if cached_context is not None and "pressure_score" in cached_context:
        return render(request, "rakip/competitor_intelligence.html", {**cached_context, "agency_scope": agency_scope})

    competitors = scope_client_queryset(
        request,
        Competitor.objects.filter(platform__code__in=SUPPORTED_META_PLATFORMS),
    ).select_related("platform", "platform_account", "agency_client")

    competitor_ads = (
        Ad.objects.filter(
            source_type="COMPETITOR",
            competitor__in=competitors,
            competitor__platform__code__in=SUPPORTED_META_PLATFORMS,
        )
        .select_related("competitor", "competitor__platform")
    )

    total_competitors = competitors.count()
    active_competitors = competitors.filter(is_active=True).count()
    total_ads = competitor_ads.count()
    metric_totals = AdMetricHistory.objects.filter(ad__in=competitor_ads).aggregate(
        impressions=Sum("impressions"),
        engagement=Sum("engagement"),
        clicks=Sum("clicks"),
        avg_ctr=Avg("ctr"),
    )
    total_impressions = metric_totals.get("impressions") or 0
    total_engagement = metric_totals.get("engagement") or 0
    avg_ctr = metric_totals.get("avg_ctr") or 0
    pressure_score = min(100, (total_ads * 7) + (active_competitors * 5))
    if pressure_score >= 70:
        pressure_label = "Yüksek baskı"
        pressure_class = "danger"
    elif pressure_score >= 35:
        pressure_label = "İzlenmeli"
        pressure_class = "warning"
    else:
        pressure_label = "Kontrollü"
        pressure_class = "good"

    platform_summary = defaultdict(lambda: {
        "platform_name": "Diğer",
        "platform_code": "other",
        "competitors": 0,
        "ads": 0,
        "impressions": 0,
        "engagement": 0,
    })

    platform_rows = []
    for competitor in competitors:
        platform_name = competitor.platform.name if competitor.platform else "Diğer"
        platform_code = getattr(competitor.platform, "code", None) or "other"
        ads_count = competitor_ads.filter(competitor=competitor).count()

        competitor_metric_totals = AdMetricHistory.objects.filter(
            ad__competitor=competitor,
            ad__source_type="COMPETITOR",
        ).aggregate(
            impressions=Sum("impressions"),
            engagement=Sum("engagement"),
            clicks=Sum("clicks"),
            avg_ctr=Avg("ctr"),
        )
        latest_metric = (
            AdMetricHistory.objects
            .filter(ad__competitor=competitor, ad__source_type="COMPETITOR")
            .order_by("-date")
            .first()
        )
        top_competitor_ad = (
            competitor_ads
            .filter(competitor=competitor)
            .annotate(metric_count=Count("metric_history"))
            .order_by("-last_seen_at", "-metric_count")
            .first()
        )
        competitor_impressions = competitor_metric_totals.get("impressions") or 0
        competitor_engagement = competitor_metric_totals.get("engagement") or 0
        competitor_ctr = competitor_metric_totals.get("avg_ctr") or 0
        if ads_count >= 8 or competitor_engagement >= 5000:
            pressure = "Agresif"
            pressure_class_row = "danger"
        elif ads_count >= 3 or competitor_engagement >= 1500:
            pressure = "Aktif"
            pressure_class_row = "warning"
        else:
            pressure = "Düşük"
            pressure_class_row = "good"

        platform_bucket = platform_summary[platform_code]
        platform_bucket["platform_name"] = platform_name
        platform_bucket["platform_code"] = platform_code
        platform_bucket["competitors"] += 1
        platform_bucket["ads"] += ads_count
        platform_bucket["impressions"] += competitor_impressions
        platform_bucket["engagement"] += competitor_engagement

        platform_rows.append({
            "id": competitor.id,
            "name": competitor.name,
            "platform_name": platform_name,
            "platform_code": platform_code,
            "ads_count": ads_count,
            "is_active": competitor.is_active,
            "last_seen_at": competitor.last_seen_at,
            "estimated_impressions": competitor_impressions or (latest_metric.impressions if latest_metric else 0),
            "estimated_engagement": competitor_engagement or (latest_metric.engagement if latest_metric else 0),
            "avg_ctr": competitor_ctr,
            "top_ad_name": top_competitor_ad.name if top_competitor_ad else "",
            "top_ad_image": top_competitor_ad.preview_image_url if top_competitor_ad else "",
            "pressure": pressure,
            "pressure_class": pressure_class_row,
        })

    platform_rows = sorted(platform_rows, key=lambda row: (row["ads_count"], row["estimated_engagement"]), reverse=True)
    platform_breakdown = sorted(
        platform_summary.values(),
        key=lambda row: (row["ads"], row["engagement"]),
        reverse=True,
    )
    strongest_competitor = platform_rows[0] if platform_rows else None

    top_ads = []
    metrics = (
        AdMetricHistory.objects
        .filter(ad__in=competitor_ads)
        .select_related("ad", "ad__competitor")
        .order_by("-engagement", "-impressions")[:8]
    )

    for metric in metrics:
        top_ads.append({
            "ad_id": metric.ad.id,
            "ad_name": metric.ad.name,
            "competitor_name": metric.ad.competitor.name if metric.ad.competitor else "Rakip",
            "platform_name": metric.ad.competitor.platform.name if metric.ad.competitor and metric.ad.competitor.platform else "Platform",
            "preview_image_url": metric.ad.preview_image_url or "",
            "impressions": metric.impressions,
            "clicks": metric.clicks,
            "engagement": metric.engagement,
            "ctr": metric.ctr,
            "date": metric.date,
        })

    context = {
        "total_competitors": total_competitors,
        "active_competitors": active_competitors,
        "total_ads": total_ads,
        "total_impressions": total_impressions,
        "total_engagement": total_engagement,
        "avg_ctr": avg_ctr,
        "pressure_score": pressure_score,
        "pressure_label": pressure_label,
        "pressure_class": pressure_class,
        "platform_breakdown": platform_breakdown,
        "strongest_competitor": strongest_competitor,
        "platform_rows": platform_rows,
        "top_ads": top_ads,
        "agency_scope": agency_scope,
    }
    CacheService.set(
        "competitor_intelligence",
        "user",
        request.user.id,
        "scope",
        agency_scope.cache_key,
        value={key: value for key, value in context.items() if key != "agency_scope"},
        timeout=COMPETITOR_INTELLIGENCE_CACHE_TIMEOUT,
        version=version,
    )

    return render(request, "rakip/competitor_intelligence.html", context)


@login_required
def competitor_ads_api(request, competitor_id):
    competitor = get_object_or_404(
        scope_client_queryset(request, Competitor.objects.all()),
        id=competitor_id,
    )
    ads = (
        Ad.objects.filter(source_type="COMPETITOR", competitor=competitor)
        .select_related("competitor", "competitor__platform")
        .order_by("-last_seen_at", "-created_at")
    )
    return JsonResponse({
        "success": True,
        "competitor": {
            "id": competitor.id,
            "name": competitor.name,
            "platform": competitor.platform.name if competitor.platform else "Platform",
        },
        "ads": [_ad_payload(ad) for ad in ads],
    })


@login_required
def competitor_ad_detail_api(request, ad_id):
    allowed_competitors = scope_client_queryset(request, Competitor.objects.all())
    ad = Ad.objects.select_related("competitor", "competitor__platform").filter(
        id=ad_id, source_type="COMPETITOR", competitor__in=allowed_competitors,
    ).first()
    if not ad:
        return JsonResponse({"success": False, "error": "Reklam bulunamadi."}, status=404)
    return JsonResponse({"success": True, "ad": _ad_payload(ad, include_rules=True)})


@login_required
@require_POST
def competitor_ad_ai_analysis_api(request, ad_id):
    allowed_competitors = scope_client_queryset(request, Competitor.objects.all())
    ad = get_object_or_404(
        Ad.objects.select_related("competitor", "competitor__platform"),
        id=ad_id,
        competitor__in=allowed_competitors,
        source_type="COMPETITOR",
    )
    summary = _metric_summary(ad)
    agency_scope = get_agency_scope(request)
    organization = agency_scope.selected_client.organization if agency_scope.selected_client else None
    usage = consume_openai_operation(
        user=request.user,
        organization=organization,
        operation=FeatureUsageLedger.OP_OPENAI_ANALYSIS,
        tariff_key="competitor-single-analysis",
        credit_amount=3,
        reference=f"competitor_intelligence.ad.{ad.id}",
        reason="Tek rakip reklam AI analizi",
        metadata={"ad_id": ad.id, "competitor_id": ad.competitor_id},
    )
    if not usage.allowed:
        return JsonResponse({"success": False, "error": usage.reason, "code": usage.code}, status=402)

    try:
        from openai import OpenAI

        result = run_sixteen_agent_orchestration(
            client=OpenAI(api_key=settings.OPENAI_API_KEY, timeout=60, max_retries=2),
            model=settings.OPENAI_MODEL,
            task="Tek rakip reklamin kreatifini, teklifini, mesajini, performansini ve rekabet baskisini analiz et.",
            context={
                "ad": _ad_payload(ad, include_rules=True),
                "metrics": summary,
                "competitor": getattr(ad.competitor, "name", ""),
            },
            modalities=["text", "image"] if ad.preview_image_url else ["text"],
            reference="competitor_intelligence.single_ad",
            user=request.user,
            organization=organization,
            tariff_key="competitor-single-analysis",
        )
        agents = result["agents"]
        analysis = {
            "overall_score": round(sum(row["confidence"] for row in agents) / len(agents) * 100, 1),
            "summary": " ".join(row["finding"] for row in agents[:3]),
            "agents": agents,
            "rules": _rule_insights(ad, summary, limit=5),
            "actions": [row["recommendation"] for row in agents[:6]],
        }
        return JsonResponse({"success": True, "analysis": analysis})
    except Exception as exc:
        refund_ai_tariff_credits(
            user=request.user, organization=organization, tariff_key="competitor-single-analysis", reason=str(exc),
            reference=f"competitor_intelligence.ad.{ad.id}",
        )
        return JsonResponse({"success": False, "error": f"Gercek AI analizi tamamlanamadi: {exc}"}, status=502)
