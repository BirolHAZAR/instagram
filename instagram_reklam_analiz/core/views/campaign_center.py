from decimal import Decimal
from datetime import timedelta
import re

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Sum
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.conf import settings
from openai import OpenAI

from core.services.agency_branding import get_report_branding
from core.services.agency_scope import get_agency_scope, platform_accounts_for_request, scope_queryset
from core.services.ai_agent_ecosystem import build_campaign_agent_ecosystem, run_sixteen_agent_orchestration
from core.services.performance_metrics import aggregate_metric_queryset
from core.services.campaign_panel_service import build_campaign_rule_events
from core.services.usage_metering import consume_usage
from core.services.openai_usage import consume_openai_operation, refund_ai_tariff_credits
from core.models import FeatureUsageLedger


def _model(name):
    try:
        return apps.get_model("core", name)
    except LookupError:
        return None


def _field(model, *names):
    if not model:
        return None
    model_fields = {f.name for f in model._meta.get_fields()}
    for name in names:
        if name in model_fields:
            return name
    return None


def _decimal(value, default="0"):
    if value in (None, ""):
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _int(value):
    try:
        return int(value or 0)
    except Exception:
        return 0


def _percent(value):
    return round(float(_decimal(value)), 2)


def _money(value):
    return round(float(_decimal(value)), 2)


def _safe_count(model, qs=None):
    if not model:
        return 0
    try:
        return (qs or model.objects.all()).count()
    except Exception:
        return 0


def _display_status(status):
    raw = (status or "UNKNOWN").upper()
    return {
        "ACTIVE": "Aktif",
        "PAUSED": "Duraklatılmış",
        "DELETED": "Silindi",
        "ARCHIVED": "Arşivlendi",
        "ENDED": "Bitti",
        "UNKNOWN": "Bilinmiyor",
    }.get(raw, raw.title())


def _display_objective(objective):
    raw = (objective or "UNKNOWN").upper()
    return {
        "AWARENESS": "Bilinirlik",
        "TRAFFIC": "Trafik",
        "ENGAGEMENT": "Etkileşim",
        "LEADS": "Potansiyel Müşteri",
        "SALES": "Satış",
        "CONVERSIONS": "Dönüşüm",
        "APP_PROMOTION": "Uygulama",
        "VIDEO_VIEWS": "Video İzlenme",
        "MESSAGES": "Mesaj",
        "UNKNOWN": "Bilinmiyor",
    }.get(raw, raw.title())




def _period_days(period):
    return {
        "daily": 1,
        "weekly": 7,
        "monthly": 30,
        "quarterly": 90,
    }.get(period, 30)


def _period_label(period):
    return {
        "daily": "Günlük",
        "weekly": "Haftalık",
        "monthly": "Aylık",
        "quarterly": "3 Aylık",
        "custom": "Özel Tarih",
    }.get(period, "Aylık")

def _metric_summary(metric_qs):
    empty = {
        "rows": 0,
        "impressions": 0,
        "clicks": 0,
        "spend": Decimal("0"),
        "conversions": Decimal("0"),
        "conversion_value": Decimal("0"),
        "ctr": Decimal("0"),
        "cpc": Decimal("0"),
        "cpa": Decimal("0"),
        "roas": Decimal("0"),
    }
    if metric_qs is None:
        return empty
    try:
        data = metric_qs.aggregate(
            impressions=Sum("impressions"),
            clicks=Sum("clicks"),
            spend=Sum("spend"),
            conversions=Sum("conversions"),
            conversion_value=Sum("conversion_value"),
            ctr=Avg("ctr"),
            cpc=Avg("cpc"),
        )
    except Exception:
        return empty

    impressions = _int(data.get("impressions"))
    clicks = _int(data.get("clicks"))
    spend = _decimal(data.get("spend"))
    conversions = _decimal(data.get("conversions"))
    conversion_value = _decimal(data.get("conversion_value"))
    # Control Tower ile birebir aynı formül:
    # CTR = toplam tıklama / toplam gösterim * 100
    # CPC = toplam harcama / toplam tıklama
    # Satır ortalaması kullanılmaz; aksi halde kampanya merkezi ve kontrol kulesi farklı görünür.
    ctr = Decimal(clicks) / Decimal(impressions) * Decimal("100") if impressions > 0 else Decimal("0")
    cpc = spend / Decimal(clicks) if clicks > 0 else Decimal("0")
    cpa = Decimal("0")
    if conversions > 0:
        cpa = spend / conversions
    roas = Decimal("0")
    if spend > 0:
        roas = conversion_value / spend

    return {
        "impressions": impressions,
        "clicks": clicks,
        "spend": spend,
        "conversions": conversions,
        "conversion_value": conversion_value,
        "ctr": ctr,
        "cpc": cpc,
        "cpa": cpa,
        "roas": roas,
    }




def _metric_summary(metric_qs):
    empty = {
        "impressions": 0,
        "clicks": 0,
        "spend": Decimal("0"),
        "conversions": Decimal("0"),
        "conversion_value": Decimal("0"),
        "ctr": Decimal("0"),
        "cpc": Decimal("0"),
        "cpa": Decimal("0"),
        "roas": Decimal("0"),
    }
    empty["rows"] = 0
    if metric_qs is None:
        return empty
    try:
        data = aggregate_metric_queryset(metric_qs)
    except Exception:
        return empty
    return {
        "rows": _int(data.get("rows")),
        "impressions": _int(data.get("impressions")),
        "clicks": _int(data.get("clicks")),
        "spend": _decimal(data.get("spend")),
        "conversions": _decimal(data.get("conversions")),
        "conversion_value": _decimal(data.get("conversion_value")),
        "ctr": _decimal(data.get("ctr")),
        "cpc": _decimal(data.get("cpc")),
        "cpa": _decimal(data.get("cpa")),
        "roas": _decimal(data.get("roas")),
    }


def _build_popup_metrics_payload(metrics, start_date, end_date, selected_days, budget=None):
    """Octo AI popup kartları için her durumda JSON uyumlu KPI paketi üretir.
    Bu alan frontend için zorunludur; boş bırakılırsa kartlar değersiz görünür.
    """
    metrics = metrics or {}
    return {
        "start_date": start_date.strftime("%d.%m.%Y") if start_date else "",
        "end_date": end_date.strftime("%d.%m.%Y") if end_date else "",
        "selected_days": int(selected_days or 0),
        "impressions": int(metrics.get("impressions") or 0),
        "clicks": int(metrics.get("clicks") or 0),
        "spend": float(_decimal(metrics.get("spend"))),
        "conversions": float(_decimal(metrics.get("conversions"))),
        "conversion_value": float(_decimal(metrics.get("conversion_value"))),
        "ctr": float(_decimal(metrics.get("ctr"))),
        "cpc": float(_decimal(metrics.get("cpc"))),
        "cpa": float(_decimal(metrics.get("cpa"))),
        "roas": float(_decimal(metrics.get("roas"))),
        "budget": float(_decimal(budget)),
    }

def _campaign_success_state(metrics, health_score, status_raw, performance_down=False, is_learning=False):
    """Kampanya başarı durumunu sayfada renklendirmek ve Octo yorumunda kullanmak için ortak kural."""
    roas = _decimal(metrics.get("roas"))
    ctr = _decimal(metrics.get("ctr"))
    conversions = _decimal(metrics.get("conversions"))
    spend = _decimal(metrics.get("spend"))

    if status_raw != "ACTIVE":
        return "neutral", "Pasif / izleniyor", "Bu kampanya aktif olmadığı için başarı değerlendirmesi izleme modunda tutuldu."
    if performance_down or (spend > 0 and conversions == 0):
        return "danger", "Başarısız / riskli", "Harcama olmasına rağmen dönüşüm ya yok ya da performans son dönemde düşüş gösteriyor."
    if health_score >= 78 or (roas >= Decimal("2.00") and ctr >= Decimal("1.00")):
        return "success", "Başarılı", "ROAS, CTR ve genel Octo skoru kampanyanın verimli çalıştığını gösteriyor."
    if is_learning:
        return "learning", "Öğrenme aşaması", "Kampanya veri toplama/öğrenme sürecinde; kesin karar için biraz daha veri gerekir."
    return "warning", "Geliştirilebilir", "Kampanya çalışıyor ancak daha iyi sonuç için bütçe, kreatif veya hedefleme tarafında optimizasyon yapılabilir."


def _build_octo_campaign_analysis(campaign, metrics, health_score, success_label, success_reason, current_7=None, previous_7=None):
    """OpenAI bağımlılığı olmadan güvenli çalışan Octo analiz çıktısı üretir."""
    current_7 = current_7 or {}
    previous_7 = previous_7 or {}
    roas = _decimal(metrics.get("roas"))
    ctr = _decimal(metrics.get("ctr"))
    cpc = _decimal(metrics.get("cpc"))
    cpa = _decimal(metrics.get("cpa"))
    spend = _decimal(metrics.get("spend"))
    conversions = _decimal(metrics.get("conversions"))
    revenue = _decimal(metrics.get("conversion_value"))
    impressions = _int(metrics.get("impressions"))
    clicks = _int(metrics.get("clicks"))

    analysis_items = [
        f"Başarı durumu: {success_label}. {success_reason}",
        f"Son 30 günde {impressions:,} gösterim ve {clicks:,} tıklama üretildi.".replace(",", "."),
        f"Toplam harcama {spend:.2f} TL, dönüşüm değeri {revenue:.2f} TL ve ROAS {roas:.2f}x seviyesinde.",
        f"CTR {ctr:.2f}% seviyesinde; bu oran kreatif ve hedefleme uyumunu okumak için ana sinyaldir.",
        f"CPC {cpc:.2f} TL, CPA {cpa:.2f} TL; maliyet tarafı dönüşüm adediyle birlikte değerlendirilmelidir.",
        f"Octo kampanya skoru {health_score}/100 olarak hesaplandı.",
    ]

    recommendation_items = []
    if roas >= Decimal("2.00") and conversions > 0:
        recommendation_items.append("ROAS güçlü olduğu için bütçe artırımı kontrollü şekilde test edilebilir; önce %10-20 artış önerilir.")
    elif spend > 0 and conversions == 0:
        recommendation_items.append("Harcama var ama dönüşüm yok; hedefleme, teklif stratejisi ve açılış sayfası acil kontrol edilmeli.")
    elif roas > 0 and roas < Decimal("1.50"):
        recommendation_items.append("ROAS düşük; bütçeyi artırmadan önce kreatif, hedef kitle ve dönüşüm olayı doğrulanmalı.")
    else:
        recommendation_items.append("Daha sağlıklı karar için dönüşüm değeri ve dönüşüm adedi birkaç gün daha izlenmeli.")

    if ctr < Decimal("0.80"):
        recommendation_items.append("CTR düşük görünüyor; reklam görseli, başlık ve ilk 2 saniye mesajı yeniden test edilmeli.")
    elif ctr >= Decimal("1.50"):
        recommendation_items.append("CTR iyi seviyede; kreatif dikkat çekiyor, benzer varyasyonlarla A/B test yapılabilir.")

    if cpc > Decimal("15.00"):
        recommendation_items.append("CPC yüksek; hedef kitle genişletme, placement kontrolü ve teklif stratejisi optimizasyonu yapılmalı.")
    if cpa > 0 and roas < Decimal("2.00"):
        recommendation_items.append("CPA/ROAS dengesi zayıf; düşük performanslı reklam gruplarına bütçe kısıtı uygulanmalı.")
    if health_score >= 78:
        recommendation_items.append("Başarılı kampanya olarak işaretlendi; ölçekleme yapılacaksa günlük performans düşüş alarmı açık tutulmalı.")
    elif health_score < 55:
        recommendation_items.append("Riskli kampanya olarak izlenmeli; bütçe azaltma veya kreatif yenileme kuralı hazırlanmalı.")

    return analysis_items, recommendation_items


@login_required
def campaign_center(request):
    agency_scope = get_agency_scope(request)
    Campaign = _model("Campaign")
    AdGroup = _model("AdGroup")
    Ad = _model("Ad")
    Platform = _model("Platform")
    PlatformAccount = _model("PlatformAccount")
    CampaignMetricHistory = _model("CampaignMetricHistory")

    now = timezone.now()
    today_real = timezone.localdate()
    active_period = request.GET.get("period", "monthly")
    allowed_periods = {"daily", "weekly", "monthly", "quarterly", "custom"}
    if active_period not in allowed_periods:
        active_period = "monthly"

    requested_start = parse_date(request.GET.get("date_from") or "")
    requested_end = parse_date(request.GET.get("date_to") or "")

    if requested_start and requested_end:
        start_date = requested_start
        end_date = min(requested_end, today_real)
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        selected_days = max((end_date - start_date).days + 1, 1)
        if active_period not in {"daily", "weekly", "monthly", "quarterly"}:
            active_period = "custom"
    else:
        if active_period == "custom":
            active_period = "monthly"
        selected_days = _period_days(active_period)
        end_date = today_real
        start_date = end_date - timedelta(days=selected_days - 1)

    prev_start = start_date - timedelta(days=selected_days)
    prev_end = start_date - timedelta(days=1)
    # Geriye dönük isim uyumluluğu için template context'te today yine var.
    today = end_date

    q = (request.GET.get("q") or "").strip()
    selected_status = (request.GET.get("status") or "all").strip()
    selected_campaign_id = (request.GET.get("campaign_id") or "").strip()

    page_number = request.GET.get("page") or 1
    per_page_raw = request.GET.get("per_page") or "20"
    try:
        per_page = int(per_page_raw)
    except Exception:
        per_page = 20
    if per_page not in [10, 20, 50]:
        per_page = 20

    # Platform seçimi artık çoklu çalışır.
    # URL örnekleri:
    #   ?platform=1
    #   ?platform=1,2,3
    #   ?platform=all
    raw_platform_values = request.GET.getlist("platform")
    if not raw_platform_values:
        raw_platform_values = [request.GET.get("platform") or "all"]

    selected_platform_ids = []
    for raw_value in raw_platform_values:
        for value in str(raw_value).split(","):
            value = value.strip()
            if value and value.lower() != "all":
                selected_platform_ids.append(value)

    # Tekrarsız liste; sıralama korunur.
    selected_platform_ids = list(dict.fromkeys(selected_platform_ids))
    selected_platform = ",".join(selected_platform_ids) if selected_platform_ids else "all"

    campaigns = []
    platform_cards = []
    summary = {
        "total_campaigns": 0,
        "active_campaigns": 0,
        "paused_campaigns": 0,
        "learning_campaigns": 0,
        "performance_up": 0,
        "performance_down": 0,
        "total_budget": Decimal("0"),
        "daily_budget_total": Decimal("0"),
        "lifetime_budget_total": Decimal("0"),
        "remaining_budget": Decimal("0"),
        "budget_usage": Decimal("0"),
        "spend": Decimal("0"),
        "impressions": 0,
        "clicks": 0,
        "conversions": Decimal("0"),
        "revenue": Decimal("0"),
        "ctr": Decimal("0"),
        "cpc": Decimal("0"),
        "cpa": Decimal("0"),
        "roas": Decimal("0"),
    }

    campaign_qs = Campaign.objects.none() if Campaign else []

    if Campaign:
        campaign_qs = Campaign.objects.all().select_related("platform_account", "platform_connection").order_by("-updated_at", "-created_at")
        user_field = _field(Campaign, "user")
        if user_field:
            campaign_qs = scope_queryset(request, campaign_qs)

        if q:
            name_field = _field(Campaign, "name", "campaign_name")
            external_field = _field(Campaign, "platform_campaign_id", "campaign_id", "external_id")
            from django.db.models import Q
            search_filter = Q()
            if name_field:
                search_filter |= Q(**{f"{name_field}__icontains": q})
            if external_field:
                search_filter |= Q(**{f"{external_field}__icontains": q})
            campaign_qs = campaign_qs.filter(search_filter)

        if selected_platform_ids:
            try:
                campaign_qs = campaign_qs.filter(platform_account__platform_id__in=selected_platform_ids)
            except Exception:
                pass

        if selected_status in {"active", "paused"}:
            campaign_qs = campaign_qs.filter(status=selected_status.upper())

        if selected_campaign_id.isdigit():
            campaign_qs = campaign_qs.filter(id=int(selected_campaign_id))

        base_qs = campaign_qs
        summary["total_campaigns"] = _safe_count(Campaign, base_qs)
        summary["active_campaigns"] = _safe_count(Campaign, base_qs.filter(status="ACTIVE"))
        summary["paused_campaigns"] = _safe_count(Campaign, base_qs.filter(status="PAUSED"))

        for campaign in base_qs:
            account = getattr(campaign, "platform_account", None)
            platform = getattr(account, "platform", None) if account else None
            if not platform and getattr(campaign, "platform_connection", None):
                platform = getattr(campaign.platform_connection, "platform", None)

            metrics_qs = None
            current_7_qs = None
            previous_7_qs = None
            if CampaignMetricHistory:
                metrics_qs = CampaignMetricHistory.objects.filter(campaign=campaign, date__gte=start_date, date__lte=end_date)
                current_7_qs = metrics_qs
                previous_7_qs = CampaignMetricHistory.objects.filter(campaign=campaign, date__gte=prev_start, date__lte=prev_end)

            metrics = _metric_summary(metrics_qs)
            current_7 = _metric_summary(current_7_qs)
            previous_7 = _metric_summary(previous_7_qs)

            status_raw = (getattr(campaign, "status", "UNKNOWN") or "UNKNOWN").upper()
            start_time = getattr(campaign, "start_time", None) or getattr(campaign, "created_at", None)
            age_days = None
            if start_time:
                try:
                    age_days = max(0, (now - start_time).days)
                except Exception:
                    age_days = None

            is_learning = status_raw == "ACTIVE" and ((age_days is not None and age_days <= 7) or metrics["impressions"] < 1000)
            has_period_comparison = current_7["rows"] > 0 and previous_7["rows"] > 0
            ctr_delta = current_7["ctr"] - previous_7["ctr"] if has_period_comparison else None
            spend_delta = current_7["spend"] - previous_7["spend"]
            performance_up = has_period_comparison and status_raw == "ACTIVE" and (
                ctr_delta > Decimal("0.15") or current_7["roas"] > previous_7["roas"]
            )
            performance_down = has_period_comparison and status_raw == "ACTIVE" and (
                ctr_delta < Decimal("-0.15")
                or (
                    spend_delta > 0
                    and current_7["conversions"] <= previous_7["conversions"]
                    and current_7["spend"] > previous_7["spend"]
                )
            )

            if selected_status == "learning" and not is_learning:
                continue
            if selected_status == "up" and not performance_up:
                continue
            if selected_status == "down" and not performance_down:
                continue

            daily_budget = _decimal(getattr(campaign, "daily_budget", None))
            lifetime_budget = _decimal(getattr(campaign, "lifetime_budget", None))
            # Kampanya kartlarında ve tabloda gösterilecek toplam bütçe:
            # lifetime_budget varsa onu, yoksa günlük bütçenin son 30 günlük karşılığını kullanıyoruz.
            budget = lifetime_budget if lifetime_budget > 0 else (daily_budget * Decimal(selected_days) if daily_budget > 0 else Decimal("0"))
            remaining_budget = max(Decimal("0"), budget - metrics["spend"]) if budget > 0 else Decimal("0")
            budget_usage = 0
            if budget > 0:
                budget_usage = min(100, int((metrics["spend"] / budget) * Decimal("100")))

            adgroup_count = 0
            ad_count = 0
            try:
                if AdGroup:
                    adgroup_count = AdGroup.objects.filter(campaign=campaign).count()
                if Ad:
                    ad_count = Ad.objects.filter(campaign=campaign, source_type="OWN").count()
            except Exception:
                pass

            health_score = 50
            if status_raw == "ACTIVE":
                health_score += 10
            if metrics["ctr"] >= Decimal("1"):
                health_score += 12
            if metrics["cpc"] > 0 and metrics["cpc"] <= Decimal("10"):
                health_score += 8
            if metrics["roas"] >= Decimal("2"):
                health_score += 15
            if performance_down:
                health_score -= 18
            if is_learning:
                health_score -= 5
            health_score = max(0, min(100, health_score))

            badge = "Stabil"
            badge_class = "stable"
            if is_learning:
                badge = "Öğrenme aşaması"
                badge_class = "learning"
                summary["learning_campaigns"] += 1
            elif performance_up:
                badge = "Performans yükseliyor"
                badge_class = "up"
                summary["performance_up"] += 1
            elif performance_down:
                badge = "Performans düşüyor"
                badge_class = "down"
                summary["performance_down"] += 1

            summary["total_budget"] += budget
            summary["daily_budget_total"] += daily_budget
            summary["lifetime_budget_total"] += lifetime_budget
            summary["remaining_budget"] += remaining_budget
            summary["spend"] += metrics["spend"]
            summary["impressions"] += metrics["impressions"]
            summary["clicks"] += metrics["clicks"]
            summary["conversions"] += metrics["conversions"]
            summary["revenue"] += metrics["conversion_value"]

            success_level, success_label, success_reason = _campaign_success_state(
                metrics, health_score, status_raw, performance_down=performance_down, is_learning=is_learning
            )
            row_class = f"ra-row-{success_level}"

            campaigns.append({
                "id": campaign.id,
                "name": getattr(campaign, "name", None) or f"Kampanya #{campaign.id}",
                "external_id": getattr(campaign, "platform_campaign_id", "-"),
                "platform": getattr(platform, "name", "-") if platform else "-",
                "platform_id": getattr(platform, "id", None) if platform else None,
                "account": getattr(account, "account_name", None) or getattr(account, "account_id", "-") if account else "-",
                "status": _display_status(status_raw),
                "status_raw": status_raw.lower(),
                "objective": _display_objective(getattr(campaign, "objective", "UNKNOWN")),
                "daily_budget": daily_budget,
                "lifetime_budget": lifetime_budget,
                "budget": budget,
                "remaining_budget": remaining_budget,
                "spend": metrics["spend"],
                "budget_usage": budget_usage,
                "impressions": metrics["impressions"],
                "clicks": metrics["clicks"],
                "ctr": metrics["ctr"],
                "cpc": metrics["cpc"],
                "cpa": metrics["cpa"],
                "roas": metrics["roas"],
                "conversions": metrics["conversions"],
                "revenue": metrics["conversion_value"],
                "adgroup_count": adgroup_count,
                "ad_count": ad_count,
                "health_score": health_score,
                "success_level": success_level,
                "success_label": success_label,
                "success_reason": success_reason,
                "row_class": row_class,
                "analysis_url": reverse("octo_campaign_analysis_safe", args=[campaign.id]),
                "badge": badge,
                "badge_class": badge_class,
                "ctr_delta": ctr_delta,
                "has_period_comparison": has_period_comparison,
                "start_label": start_time.strftime("%d.%m.%Y") if start_time else "-",
            })

    if summary["impressions"] > 0:
        summary["ctr"] = Decimal(summary["clicks"]) / Decimal(summary["impressions"]) * Decimal("100")
    if summary["clicks"] > 0:
        summary["cpc"] = summary["spend"] / Decimal(summary["clicks"])
    if summary["conversions"] > 0:
        summary["cpa"] = summary["spend"] / summary["conversions"]
    if summary["spend"] > 0:
        summary["roas"] = summary["revenue"] / summary["spend"]
    if summary["total_budget"] > 0:
        summary["budget_usage"] = min(Decimal("100"), (summary["spend"] / summary["total_budget"]) * Decimal("100"))

    def _platform_toggle_url(platform_id):
        values = [str(v) for v in selected_platform_ids]
        platform_id = str(platform_id)
        if platform_id in values:
            values.remove(platform_id)
        else:
            values.append(platform_id)

        query = request.GET.copy()
        if values:
            query["platform"] = ",".join(values)
        else:
            query.pop("platform", None)
        query.pop("page", None)
        query["per_page"] = str(per_page)
        return f"?{query.urlencode()}" if query else request.path

    if Platform:
        platforms = Platform.objects.all().order_by("name")
        for platform in platforms:
            account_count = 0
            campaign_count = 0
            try:
                if PlatformAccount:
                    scoped_accounts = platform_accounts_for_request(request).filter(platform=platform)
                    account_count = scoped_accounts.count()
                    account_ids = scoped_accounts.values_list("id", flat=True)
                    if Campaign:
                        campaign_count = scope_queryset(request, Campaign.objects.filter(platform_account_id__in=account_ids)).count()
            except Exception:
                pass
            platform_cards.append({
                "id": platform.id,
                "name": getattr(platform, "name", "-"),
                "code": getattr(platform, "code", ""),
                "account_count": account_count,
                "campaign_count": campaign_count,
                "is_selected": str(platform.id) in selected_platform_ids,
                "filter_url": _platform_toggle_url(platform.id),
            })

    # Kartlardaki toplamlar ekranda listelenen/seçilen kampanyalara göre hesaplanır.
    summary["total_campaigns"] = len(campaigns)
    summary["active_campaigns"] = sum(1 for c in campaigns if c.get("status_raw") == "active")
    summary["paused_campaigns"] = sum(1 for c in campaigns if c.get("status_raw") == "paused")


    # Kampanyaları başarı durumuna göre sırala:
    # Başarılı kampanyalar üstte, geliştirilebilir/öğrenme ortada, başarısız/riskli kampanyalar altta.
    success_order = {
        "success": 0,
        "warning": 1,
        "learning": 2,
        "neutral": 3,
        "danger": 4,
    }
    campaigns = sorted(
        campaigns,
        key=lambda x: (
            success_order.get(x.get("success_level"), 9),
            -float(x.get("roas") or 0),
            -float(x.get("conversions") or 0),
            -float(x.get("health_score") or 0),
        )
    )

    top_campaign = campaigns[0] if campaigns else None
    if campaigns:
        top_campaign = sorted(campaigns, key=lambda x: (x["roas"], x["conversions"], x["ctr"]), reverse=True)[0]


    # Kampanya tablosu sayfalama:
    # Filtrelenen tüm kampanyalar özet/kart hesaplarında kullanılır,
    # tabloda ise performans ve kullanım kolaylığı için sayfalama uygulanır.
    all_campaigns_for_table = campaigns
    all_campaigns_count = len(all_campaigns_for_table)

    paginator = Paginator(all_campaigns_for_table, per_page)
    page_obj = paginator.get_page(page_number)
    campaigns = list(page_obj.object_list)

    query_for_pagination = request.GET.copy()
    query_for_pagination.pop("page", None)
    query_for_pagination["per_page"] = str(per_page)
    pagination_query = query_for_pagination.urlencode()

    def _period_url(period_key):
        days = _period_days(period_key)
        end = today_real
        start = end - timedelta(days=days - 1)
        query = request.GET.copy()
        query["period"] = period_key
        query["date_from"] = start.strftime("%Y-%m-%d")
        query["date_to"] = end.strftime("%Y-%m-%d")
        query.pop("page", None)
        return f"?{query.urlencode()}"

    period_links = {
        "daily": _period_url("daily"),
        "weekly": _period_url("weekly"),
        "monthly": _period_url("monthly"),
        "quarterly": _period_url("quarterly"),
    }

    context = {
        "agency_scope": agency_scope,
        "filters": {
            "active_period": active_period,
            "date_from": start_date.strftime("%Y-%m-%d"),
            "date_to": end_date.strftime("%Y-%m-%d"),
            "date_label": f"{start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}",
            "selected_days": selected_days,
            "today": today_real.strftime("%Y-%m-%d"),
            "period_label": _period_label(active_period),
        },
        "period_links": period_links,
        "campaigns": campaigns,
        "page_obj": page_obj,
        "paginator": paginator,
        "pagination_query": pagination_query,
        "per_page": per_page,
        "all_campaigns_count": all_campaigns_count,
        "platform_cards": platform_cards,
        "summary": summary,
        "top_campaign": top_campaign,
        "selected_status": selected_status,
        "selected_platform": selected_platform,
        "q": q,
        "today": today,
        "status_tabs": [
            ("all", "Tümü"),
            ("active", "Aktif"),
            ("paused", "Duraklatılmış"),
            ("learning", "Öğrenme aşaması"),
            ("down", "Performans düşüyor"),
            ("up", "Performans yükseliyor"),
        ],
    }

    return render(request, "reports/campaign_center.html", context)


from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


def _structured_rule_findings(rule_events, start_date, end_date):
    """Prepare dated, deduplicated rule findings for the campaign modal."""
    findings = []
    seen = set()
    for row in rule_events:
        event = str(row.get("event") or "Kampanya tespiti").strip()
        detected_at = str(row.get("detected_at") or "").strip()
        description = str(row.get("description") or "").strip()
        # The stored message often starts with the event title again.
        description = re.sub(
            rf"^\s*{re.escape(event)}\s*:\s*",
            "",
            description,
            count=1,
            flags=re.IGNORECASE,
        ).strip()
        key = (event.casefold(), detected_at, description.casefold())
        if key in seen:
            continue
        seen.add(key)
        findings.append({
            "event": event,
            "detected_at": detected_at or f"{start_date:%d.%m.%Y} - {end_date:%d.%m.%Y}",
            "severity": str(row.get("severity") or "info").lower(),
            "severity_label": row.get("severity_label") or "Bilgi",
            "module": row.get("module") or "Kampanya",
            "source": row.get("source") or "Performans kontrolü",
            "description": description,
            "solution": str(row.get("solution") or "").strip(),
        })
    return findings


@login_required
@csrf_exempt
@require_http_methods(["GET", "POST"])
def octo_campaign_analysis(request, campaign_id):
    """Legacy endpoint: keep the old URL name but use the safe implementation."""
    return octo_campaign_analysis_safe(request, campaign_id)

    """
    Octo Kampanya Analizi endpoint'i.
    Kritik düzeltme:
    - HTTP 400 boş yanıt dönmez.
    - GET/POST ikisini de kabul eder.
    - Hata olsa bile JsonResponse döner.
    - Son 24 saat içinde dolu analiz varsa onu gösterir.
    - force=1 gelirse yeniden analiz üretir.
    """
    try:
        Campaign = _model("Campaign")
        CampaignMetricHistory = _model("CampaignMetricHistory")
        CampaignOctoAnalysis = _model("CampaignOctoAnalysis")
        CampaignOctoRecommendation = _model("CampaignOctoRecommendation")

        if not Campaign:
            return JsonResponse({"ok": False, "error": "Campaign modeli bulunamadı."}, status=200)

        if not CampaignOctoAnalysis:
            return JsonResponse({"ok": False, "error": "CampaignOctoAnalysis modeli bulunamadı."}, status=200)

        if not CampaignOctoRecommendation:
            return JsonResponse({"ok": False, "error": "CampaignOctoRecommendation modeli bulunamadı."}, status=200)

        campaign_qs = Campaign.objects.all()
        user_field = _field(Campaign, "user")
        if user_field:
            campaign_qs = scope_queryset(request, campaign_qs)

        campaign = get_object_or_404(campaign_qs, id=campaign_id)

        force = (
            request.POST.get("force") == "1"
            or request.GET.get("force") == "1"
        )


        latest_analysis = None
        latest_recommendation = None

        # Popup üst KPI kartları her zaman seçili tarih aralığından hesaplanır.
        popup_metrics_qs = CampaignMetricHistory.objects.filter(
            campaign=campaign,
            date__gte=start_date,
            date__lte=end_date,
        ) if CampaignMetricHistory else None
        popup_metrics = _metric_summary(popup_metrics_qs)
        daily_budget_for_popup = _decimal(getattr(campaign, "daily_budget", None))
        lifetime_budget_for_popup = _decimal(getattr(campaign, "lifetime_budget", None))
        popup_budget = lifetime_budget_for_popup if lifetime_budget_for_popup > 0 else (
            daily_budget_for_popup * Decimal(selected_days) if daily_budget_for_popup > 0 else Decimal("0")
        )
        popup_metrics_payload = {
            "start_date": start_date.strftime("%d.%m.%Y"),
            "end_date": end_date.strftime("%d.%m.%Y"),
            "selected_days": selected_days,
            "period": active_period,
            "spend": float(popup_metrics.get("spend", 0) or 0),
            "budget": float(popup_budget or 0),
            "impressions": int(popup_metrics.get("impressions", 0) or 0),
            "clicks": int(popup_metrics.get("clicks", 0) or 0),
            "ctr": float(popup_metrics.get("ctr", 0) or 0),
            "cpc": float(popup_metrics.get("cpc", 0) or 0),
            "cpm": float(popup_metrics.get("cpm", 0) or 0),
            "conversions": float(popup_metrics.get("conversions", 0) or 0),
            "conversion_value": float(popup_metrics.get("conversion_value", 0) or 0),
            "roas": float(popup_metrics.get("roas", 0) or 0),
        }

        metrics_qs = CampaignMetricHistory.objects.filter(campaign=campaign, date__gte=start_date, date__lte=end_date) if CampaignMetricHistory else None
        metrics = _metric_summary(metrics_qs)

        daily_budget_for_popup = _decimal(getattr(campaign, "daily_budget", None))
        lifetime_budget_for_popup = _decimal(getattr(campaign, "lifetime_budget", None))
        budget_for_popup = lifetime_budget_for_popup if lifetime_budget_for_popup > 0 else (daily_budget_for_popup * Decimal(selected_days) if daily_budget_for_popup > 0 else Decimal("0"))
        popup_metrics_payload = _build_popup_metrics_payload(metrics, start_date, end_date, selected_days, budget_for_popup)

        if not force:
            latest_analysis = CampaignOctoAnalysis.objects.filter(
                campaign=campaign,
            ).order_by("-created_at", "-id").first()

            if latest_analysis:
                latest_recommendation = CampaignOctoRecommendation.objects.filter(
                    campaign=campaign,
                    analysis=latest_analysis,
                ).order_by("-created_at").first()

                analysis_text = (
                    getattr(latest_analysis, "analysis_text", "")
                    or getattr(latest_analysis, "success_reason", "")
                    or ""
                )

                recommendation_text = ""

                if latest_recommendation:
                    recommendation_text = (
                        getattr(latest_recommendation, "recommendations", "")
                        or getattr(latest_recommendation, "summary", "")
                        or ""
                    )

                if not recommendation_text:
                    recommendation_text = (
                        getattr(latest_analysis, "recommendation_text", "")
                        or getattr(latest_analysis, "next_actions", "")
                        or ""
                    )

                analysis_items = [
                    x.strip("- ").strip()
                    for x in str(analysis_text).splitlines()
                    if x.strip()
                ]

                recommendation_items = [
                    x.strip("- ").strip()
                    for x in str(recommendation_text).splitlines()
                    if x.strip()
                ]

                # Boş analiz cache sayılmasın.
                if analysis_items and recommendation_items:
                    applied_at = getattr(latest_recommendation, "applied_at", None) if latest_recommendation else None
                    is_applied = bool(getattr(latest_recommendation, "is_applied", False)) if latest_recommendation else False

                    return JsonResponse({
                        "ok": True,
                        "cached": True,
                        "score": int(getattr(latest_analysis, "octo_score", None) or getattr(latest_analysis, "analysis_score", 0) or 0),
                        "label": getattr(latest_analysis, "success_label", "") or getattr(latest_analysis, "status", "Kayıtlı Analiz"),
                        "success_label": getattr(latest_analysis, "success_label", "") or getattr(latest_analysis, "status", "Kayıtlı Analiz"),
                        "analysis": analysis_items,
                        "analysis_items": analysis_items,
                        "recommendations": recommendation_items,
                        "recommendation_items": recommendation_items,
                        "analysis_id": latest_analysis.id,
                        "recommendation_id": latest_recommendation.id if latest_recommendation else None,
                        "saved_at": timezone.localtime(latest_analysis.created_at).strftime("%d.%m.%Y %H:%M") if getattr(latest_analysis, "created_at", None) else "",
                        "created_at": timezone.localtime(latest_analysis.created_at).strftime("%d.%m.%Y %H:%M") if getattr(latest_analysis, "created_at", None) else "",
                        "is_applied": is_applied,
                        "applied_at": timezone.localtime(applied_at).strftime("%d.%m.%Y %H:%M") if applied_at else "",
                    }, status=200)

        today = timezone.localdate()
        last_30_start = today - timedelta(days=30)
        last_7_start = today - timedelta(days=7)
        previous_7_start = today - timedelta(days=14)

        metrics_qs = None
        current_7_qs = None
        previous_7_qs = None

        if CampaignMetricHistory:
            metrics_qs = CampaignMetricHistory.objects.filter(campaign=campaign, date__gte=last_30_start)
            current_7_qs = CampaignMetricHistory.objects.filter(campaign=campaign, date__gte=last_7_start)
            previous_7_qs = CampaignMetricHistory.objects.filter(
                campaign=campaign,
                date__gte=previous_7_start,
                date__lt=last_7_start,
            )

        metrics = _metric_summary(metrics_qs)
        current_7 = _metric_summary(current_7_qs)
        previous_7 = _metric_summary(previous_7_qs)

        status_raw = (getattr(campaign, "status", "UNKNOWN") or "UNKNOWN").upper()

        start_time = getattr(campaign, "start_time", None) or getattr(campaign, "created_at", None)
        age_days = None

        if start_time:
            try:
                age_days = max(0, (timezone.now() - start_time).days)
            except Exception:
                age_days = None

        is_learning = status_raw == "ACTIVE" and (
            (age_days is not None and age_days <= 7)
            or metrics["impressions"] < 1000
        )

        ctr_delta = current_7["ctr"] - previous_7["ctr"]
        spend_delta = current_7["spend"] - previous_7["spend"]

        performance_down = status_raw == "ACTIVE" and (
            ctr_delta < Decimal("-0.15")
            or (
                spend_delta > 0
                and current_7["conversions"] <= previous_7["conversions"]
                and current_7["spend"] > previous_7["spend"]
            )
        )

        health_score = 50

        if status_raw == "ACTIVE":
            health_score += 10

        if metrics["ctr"] >= Decimal("1"):
            health_score += 12

        if metrics["cpc"] > 0 and metrics["cpc"] <= Decimal("10"):
            health_score += 8

        if metrics["roas"] >= Decimal("2"):
            health_score += 15

        if performance_down:
            health_score -= 18

        if is_learning:
            health_score -= 5

        health_score = max(0, min(100, health_score))

        success_level, success_label, success_reason = _campaign_success_state(
            metrics,
            health_score,
            status_raw,
            performance_down=performance_down,
            is_learning=is_learning,
        )

        analysis_items, recommendation_items = _build_octo_campaign_analysis(
            campaign,
            metrics,
            health_score,
            success_label,
            success_reason,
            current_7=current_7,
            previous_7=previous_7,
        )

        if not analysis_items:
            analysis_items = [
                f"Başarı durumu: {success_label}.",
                success_reason,
                f"ROAS {metrics['roas']:.2f}x, CTR %{metrics['ctr']:.2f}, CPC {metrics['cpc']:.2f} TL olarak hesaplandı.",
            ]

        if not recommendation_items:
            recommendation_items = [
                "Kampanya metrikleri izlenmeli ve 3-7 gün içinde yeniden değerlendirilmelidir.",
                "Bütçe, hedefleme ve kreatif tarafı kontrollü şekilde test edilmelidir.",
            ]

        daily_budget = _decimal(getattr(campaign, "daily_budget", None))
        lifetime_budget = _decimal(getattr(campaign, "lifetime_budget", None))

        budget = lifetime_budget if lifetime_budget > 0 else (
            daily_budget * Decimal("30") if daily_budget > 0 else Decimal("0")
        )

        account = getattr(campaign, "platform_account", None)
        platform = getattr(account, "platform", None) if account else None

        if not platform and getattr(campaign, "platform_connection", None):
            platform = getattr(campaign.platform_connection, "platform", None)

        campaign_name = (
            getattr(campaign, "name", None)
            or getattr(campaign, "campaign_name", None)
            or f"Kampanya #{campaign.id}"
        )

        platform_name = getattr(platform, "name", "") if platform else ""
        account_name = getattr(account, "account_name", None) or getattr(account, "account_id", "") if account else ""
        objective = getattr(campaign, "objective", "") or ""

        source = "real"

        if success_level == "success":
            status_value = "excellent" if health_score >= 85 else "good"
            risk_level = "low"
        elif success_level == "danger":
            status_value = "critical" if health_score < 35 else "risky"
            risk_level = "critical" if health_score < 35 else "high"
        else:
            status_value = "watch"
            risk_level = "medium"

        analysis_text = "\n".join(analysis_items)
        recommendation_text = "\n".join(recommendation_items)
        priority = "low" if success_level == "success" else ("high" if success_level == "danger" else "medium")
        score_decimal = Decimal(str(health_score))
        agents_payload = build_campaign_agent_ecosystem(
            {
                "roas": metrics["roas"],
                "ctr": metrics["ctr"],
                "cpc": metrics["cpc"],
                "cpm": metrics.get("cpm"),
                "spend": metrics["spend"],
                "revenue": metrics["conversion_value"],
                "conversions": metrics["conversions"],
                "impressions": metrics["impressions"],
            },
            detail={"platform": platform_name, "account_name": account_name},
            recommendations=[{"title": item, "detail": ""} for item in recommendation_items],
        )

        analysis_payload = {
            "user": request.user,
            "campaign": campaign,
            "octo_score": score_decimal,
            "analysis_score": score_decimal,
            "status": status_value,
            "risk_level": risk_level,
            "roas": metrics["roas"],
            "ctr": metrics["ctr"],
            "cpc": metrics["cpc"],
            "cpm": _decimal(metrics.get("cpm")),
            "spend": metrics["spend"],
            "budget": budget,
            "conversions": metrics["conversions"],
            "conversion_value": metrics["conversion_value"],
            "roas_score": Decimal(str(min(100, max(0, float(metrics["roas"]) * 20)))) if metrics["roas"] else Decimal("0"),
            "ctr_score": Decimal(str(min(100, max(0, float(metrics["ctr"]) * 25)))) if metrics["ctr"] else Decimal("0"),
            "cpc_score": Decimal("80") if metrics["cpc"] and metrics["cpc"] <= Decimal("10") else Decimal("45"),
            "conversion_score": Decimal("80") if metrics["conversions"] > 0 else Decimal("20"),
            "analysis_text": analysis_text,
            "agents_payload": agents_payload,
            "raw_ai_payload": {"source_view": "campaign_center", "mode": "analysis", "items": analysis_items},
            "source": source,
            "campaign_name": campaign_name,
            "platform_name": platform_name,
            "account_name": account_name,
            "objective": objective,
            "recommendation_text": recommendation_text,
            "strengths": success_reason,
            "weaknesses": "",
            "next_actions": recommendation_text,
            "expected_impact": "Öneriler uygulandıktan sonra 3-7 gün içinde yeni metriklerle tekrar ölçülmelidir.",
            "priority": priority,
            "success_level": success_level,
            "success_label": success_label,
            "success_reason": success_reason,
        }

        analysis_fields = {f.name for f in CampaignOctoAnalysis._meta.get_fields()}
        analysis_payload = {k: v for k, v in analysis_payload.items() if k in analysis_fields}

        analysis = CampaignOctoAnalysis.objects.create(**analysis_payload)

        recommendation_payload = {
            "user": request.user,
            "campaign": campaign,
            "analysis": analysis,
            "campaign_name": campaign_name,
            "platform_name": platform_name,
            "account_name": account_name,
            "summary": f"{campaign_name} kampanyası için Octo sonucu: {success_label}.",
            "strengths": success_reason,
            "weaknesses": "",
            "recommendations": recommendation_text,
            "agents_payload": agents_payload,
            "raw_ai_payload": {"source_view": "campaign_center", "mode": "recommendation", "items": recommendation_items},
            "expected_impact": "Öneriler uygulandıktan sonra 3-7 gün içinde yeni metriklerle tekrar ölçülmelidir.",
            "priority": priority,
            "source": source,
            "is_applied": False,
        }

        recommendation_fields = {f.name for f in CampaignOctoRecommendation._meta.get_fields()}
        recommendation_payload = {k: v for k, v in recommendation_payload.items() if k in recommendation_fields}

        recommendation = CampaignOctoRecommendation.objects.create(**recommendation_payload)

        return JsonResponse({
            "ok": True,
            "cached": False,
            "save_error": save_error,
            "score": health_score,
            "label": success_label,
            "success_label": success_label,
            "analysis": analysis_items,
            "analysis_items": analysis_items,
            "recommendations": recommendation_items,
            "recommendation_items": recommendation_items,
            "analysis_id": analysis.id if analysis is not None else None,
            "recommendation_id": recommendation.id if recommendation is not None else None,
            "saved_at": timezone.localtime(analysis.created_at).strftime("%d.%m.%Y %H:%M") if analysis is not None and getattr(analysis, "created_at", None) else "",
            "created_at": timezone.localtime(analysis.created_at).strftime("%d.%m.%Y %H:%M") if analysis is not None and getattr(analysis, "created_at", None) else "",
            "is_applied": False,
            "applied_at": "",
        }, status=200)

    except Exception as exc:
        return JsonResponse({
            "ok": False,
            "error": str(exc),
            "message": f"Octo kampanya analizi oluşturulamadı. Detay: {exc}",
        }, status=200)


@login_required
@require_POST
def mark_campaign_octo_recommendation_applied(request, recommendation_id):
    CampaignOctoRecommendation = _model("CampaignOctoRecommendation")
    if not CampaignOctoRecommendation:
        return JsonResponse({"ok": False, "error": "CampaignOctoRecommendation modeli bulunamadı."}, status=400)
    try:
        recommendation = get_object_or_404(CampaignOctoRecommendation, id=recommendation_id)
        is_applied = request.POST.get("is_applied", "1") == "1"
        fields = {f.name for f in CampaignOctoRecommendation._meta.get_fields()}
        if "is_applied" in fields:
            recommendation.is_applied = is_applied
        if "applied_at" in fields:
            recommendation.applied_at = timezone.now() if is_applied else None
        if "applied_by" in fields:
            recommendation.applied_by = request.user if is_applied else None
        if "apply_note" in fields:
            recommendation.apply_note = request.POST.get("note", "") or ""
        recommendation.save()
        return JsonResponse({
            "ok": True,
            "recommendation_id": recommendation.id if recommendation is not None else None,
            "is_applied": is_applied,
            "applied_at": timezone.localtime(recommendation.applied_at).strftime("%d.%m.%Y %H:%M") if getattr(recommendation, "applied_at", None) else "",
        })
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

def _octo_best_worst_metric(metrics):
    roas = _decimal(metrics.get("roas"))
    ctr = _decimal(metrics.get("ctr"))
    cpc = _decimal(metrics.get("cpc"))
    cpa = _decimal(metrics.get("cpa"))
    conversions = _decimal(metrics.get("conversions"))
    spend = _decimal(metrics.get("spend"))

    scores = {
        "ROAS": 100 if roas >= Decimal("5") else 80 if roas >= Decimal("3") else 60 if roas >= Decimal("2") else 35 if roas > 0 else 10,
        "CTR": 100 if ctr >= Decimal("2.5") else 80 if ctr >= Decimal("1.5") else 55 if ctr >= Decimal("0.8") else 25,
        "CPC": 100 if Decimal("0") < cpc <= Decimal("4") else 75 if cpc <= Decimal("8") else 45 if cpc <= Decimal("15") else 20,
        "CPA": 100 if Decimal("0") < cpa <= Decimal("80") else 75 if cpa <= Decimal("150") else 45 if cpa <= Decimal("300") else 20,
        "Dönüşüm": 90 if conversions > 0 else 10,
        "Harcama Verimliliği": 90 if spend > 0 and roas >= Decimal("2") else 45 if spend > 0 else 25,
    }

    best_metric = max(scores, key=scores.get)
    worst_metric = min(scores, key=scores.get)

    if worst_metric == best_metric:
        worst_metric = "Yakın takip"

    return best_metric, worst_metric


def _octo_risk_label(risk_score):
    risk_score = _decimal(risk_score)
    if risk_score <= 20:
        return "Düşük Risk"
    if risk_score <= 40:
        return "Kontrollü"
    if risk_score <= 60:
        return "İzlenmeli"
    if risk_score <= 80:
        return "Riskli"
    return "Kritik"

def _octo_trend_label(current_7, previous_7):
    current_roas = _decimal(current_7.get("roas"))
    previous_roas = _decimal(previous_7.get("roas"))
    current_ctr = _decimal(current_7.get("ctr"))
    previous_ctr = _decimal(previous_7.get("ctr"))

    if current_roas > previous_roas or current_ctr > previous_ctr:
        return "yükseliş"
    if current_roas < previous_roas or current_ctr < previous_ctr:
        return "düşüş"
    return "stabil"


def _octo_risk_score(health_score, metrics, performance_down=False):
    roas = _decimal(metrics.get("roas"))
    conversions = _decimal(metrics.get("conversions"))
    spend = _decimal(metrics.get("spend"))

    risk = max(0, min(100, 100 - int(health_score)))

    if performance_down:
        risk += 15
    if spend > 0 and conversions <= 0:
        risk += 20
    if roas < Decimal("1"):
        risk += 15

    return max(0, min(100, risk))


def _octo_estimated_effects(success_level, metrics):
    roas = _decimal(metrics.get("roas"))
    ctr = _decimal(metrics.get("ctr"))
    conversions = _decimal(metrics.get("conversions"))

    if roas >= Decimal("8"):
        roas_gain = Decimal("8.00")
    elif roas >= Decimal("4"):
        roas_gain = Decimal("12.00")
    elif roas >= Decimal("2"):
        roas_gain = Decimal("15.00")
    elif roas > 0:
        roas_gain = Decimal("25.00")
    else:
        roas_gain = Decimal("30.00")

    ctr_gain = Decimal("6.00") if ctr >= Decimal("1.5") else Decimal("15.00") if ctr < Decimal("0.8") else Decimal("10.00")
    conversion_gain = Decimal("10.00") if conversions > 0 else Decimal("20.00")

    if success_level == "success":
        return {
            "difficulty_level": "Düşük",
            "estimated_roas_gain": roas_gain,
            "estimated_ctr_gain": ctr_gain,
            "estimated_conversion_gain": conversion_gain,
            "implementation_time": "1-3 gün",
            "action_type": "scale_budget",
        }

    if conversions <= 0 or roas < Decimal("1"):
        return {
            "difficulty_level": "Orta",
            "estimated_roas_gain": roas_gain,
            "estimated_ctr_gain": ctr_gain,
            "estimated_conversion_gain": conversion_gain,
            "implementation_time": "3-7 gün",
            "action_type": "fix_conversion_targeting",
        }

    if ctr < Decimal("0.80"):
        return {
            "difficulty_level": "Düşük",
            "estimated_roas_gain": roas_gain,
            "estimated_ctr_gain": ctr_gain,
            "estimated_conversion_gain": conversion_gain,
            "implementation_time": "1-3 gün",
            "action_type": "creative_refresh",
        }

    return {
        "difficulty_level": "Orta",
        "estimated_roas_gain": roas_gain,
        "estimated_ctr_gain": ctr_gain,
        "estimated_conversion_gain": conversion_gain,
        "implementation_time": "3-5 gün",
        "action_type": "general_optimization",
    }


from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


@login_required
@csrf_exempt
@require_http_methods(["GET", "POST"])
def octo_campaign_analysis_safe(request, campaign_id):
    charged_tariff_key = ""
    charged_reference = ""
    try:
        Campaign = _model("Campaign")
        CampaignMetricHistory = _model("CampaignMetricHistory")
        CampaignOctoAnalysis = _model("CampaignOctoAnalysis")
        CampaignOctoRecommendation = _model("CampaignOctoRecommendation")

        if not Campaign:
            return JsonResponse({"ok": False, "message": "Campaign modeli bulunamadı."}, status=200)
        if not CampaignOctoAnalysis:
            return JsonResponse({"ok": False, "message": "CampaignOctoAnalysis modeli bulunamadı."}, status=200)
        if not CampaignOctoRecommendation:
            return JsonResponse({"ok": False, "message": "CampaignOctoRecommendation modeli bulunamadı."}, status=200)

        campaign_qs = Campaign.objects.all()
        user_field = _field(Campaign, "user")
        if user_field:
            campaign_qs = scope_queryset(request, campaign_qs)

        campaign = get_object_or_404(campaign_qs, id=campaign_id)
        mode = (request.POST.get("mode") or request.GET.get("mode") or "metrics").strip().lower()
        if mode not in {"metrics", "analysis", "recommendation"}:
            mode = "metrics"
        force = request.POST.get("force") == "1" or request.GET.get("force") == "1"

        # Filtre sonrası Octo AI analizde kullanılan tarih aralığını güvenli oluştur.
        # selected_days hiçbir koşulda boş kalmamalı; aksi halde analiz popup hata verir.
        today = timezone.localdate()
        active_period = (request.POST.get("period") or request.GET.get("period") or "monthly").strip()
        allowed_periods = {"daily", "weekly", "monthly", "quarterly", "custom"}
        if active_period not in allowed_periods:
            active_period = "monthly"

        requested_start = parse_date(request.POST.get("date_from") or request.GET.get("date_from") or "")
        requested_end = parse_date(request.POST.get("date_to") or request.GET.get("date_to") or "")

        if requested_start and requested_end:
            start_date = requested_start
            end_date = min(requested_end, today)
            if start_date > end_date:
                start_date, end_date = end_date, start_date
            selected_days = max((end_date - start_date).days + 1, 1)
            if active_period not in {"daily", "weekly", "monthly", "quarterly"}:
                active_period = "custom"
        else:
            if active_period == "custom":
                active_period = "monthly"
            selected_days = _period_days(active_period)
            end_date = today
            start_date = end_date - timedelta(days=selected_days - 1)

        metrics_qs = CampaignMetricHistory.objects.filter(campaign=campaign, date__gte=start_date, date__lte=end_date) if CampaignMetricHistory else None
        metrics = _metric_summary(metrics_qs)

        daily_budget_for_popup = _decimal(getattr(campaign, "daily_budget", None))
        lifetime_budget_for_popup = _decimal(getattr(campaign, "lifetime_budget", None))
        budget_for_popup = lifetime_budget_for_popup if lifetime_budget_for_popup > 0 else (daily_budget_for_popup * Decimal(selected_days) if daily_budget_for_popup > 0 else Decimal("0"))
        popup_metrics_payload = _build_popup_metrics_payload(metrics, start_date, end_date, selected_days, budget_for_popup)

        rule_events = build_campaign_rule_events(campaign, popup_metrics_payload)
        structured_rule_findings = _structured_rule_findings(rule_events, start_date, end_date)
        rule_findings = [
            f"[{row.get('detected_at')}] {row.get('event')}: {row.get('description')}" + (f" — {row.get('solution')}" if row.get('solution') else "")
            for row in structured_rule_findings[:20]
        ]
        if mode != "metrics" and not (request.user.is_staff or request.user.is_superuser):
            agency_scope = get_agency_scope(request)
            organization = agency_scope.selected_client.organization if agency_scope.selected_client else None
            operation = (
                FeatureUsageLedger.OP_OPENAI_ANALYSIS
                if mode == "analysis"
                else FeatureUsageLedger.OP_OPENAI_RECOMMENDATION
            )
            usage = consume_openai_operation(
                user=request.user,
                organization=organization,
                operation=operation,
                tariff_key=("campaign-center-analysis" if mode == "analysis" else "campaign-center-recommendation"),
                credit_amount=3,
                reference=f"campaign_center:{campaign.id}:{mode}",
                reason=f"Octo kampanya {mode}",
            )
            if not usage.allowed:
                return JsonResponse(
                    {
                        "ok": False,
                        "message": usage.reason,
                        "code": usage.code,
                        "usage_type": "ai_analysis" if mode == "analysis" else "ai_recommendation",
                        "limit": usage.limit,
                        "used": usage.used,
                        "remaining": usage.remaining,
                    },
                    status=402,
                )
            charged_tariff_key = "campaign-center-analysis" if mode == "analysis" else "campaign-center-recommendation"
            charged_reference = f"campaign_center:{campaign.id}:{mode}"

        if not force:
            latest_analysis = CampaignOctoAnalysis.objects.filter(
                campaign=campaign,
            ).order_by("-created_at", "-id").first()

            if latest_analysis:
                latest_recommendation = CampaignOctoRecommendation.objects.filter(
                    campaign=campaign,
                    analysis=latest_analysis,
                ).order_by("-created_at").first()

                analysis_text = getattr(latest_analysis, "analysis_text", "") or getattr(latest_analysis, "success_reason", "") or ""
                recommendation_text = ""

                if latest_recommendation:
                    recommendation_text = getattr(latest_recommendation, "recommendations", "") or getattr(latest_recommendation, "summary", "") or ""

                if not recommendation_text:
                    recommendation_text = getattr(latest_analysis, "recommendation_text", "") or getattr(latest_analysis, "next_actions", "") or ""

                analysis_items = [x.strip("- ").strip() for x in str(analysis_text).splitlines() if x.strip()]
                recommendation_items = [x.strip("- ").strip() for x in str(recommendation_text).splitlines() if x.strip()]

                if analysis_items and recommendation_items:
                    if charged_tariff_key:
                        refund_ai_tariff_credits(
                            user=request.user, organization=organization, tariff_key=charged_tariff_key,
                            reason="Kayıtlı analiz önbellekten döndürüldü.", reference=charged_reference,
                        )
                        charged_tariff_key = ""
                    applied_at = getattr(latest_recommendation, "applied_at", None) if latest_recommendation else None
                    is_applied = bool(getattr(latest_recommendation, "is_applied", False)) if latest_recommendation else False

                    return JsonResponse({
                        "ok": True,
                        "cached": True,
                        "score": int(getattr(latest_analysis, "octo_score", None) or getattr(latest_analysis, "analysis_score", 0) or 0),
                        "label": getattr(latest_analysis, "success_label", "") or "Kayıtlı Analiz",
                        "success_label": getattr(latest_analysis, "success_label", "") or "Kayıtlı Analiz",
                        "analysis": analysis_items,
                        "analysis_items": analysis_items,
                        "recommendations": recommendation_items,
                        "recommendation_items": recommendation_items,
                        "analysis_id": latest_analysis.id,
                        "recommendation_id": latest_recommendation.id if latest_recommendation else None,
                        "saved_at": timezone.localtime(latest_analysis.created_at).strftime("%d.%m.%Y %H:%M") if getattr(latest_analysis, "created_at", None) else "",
                        "created_at": timezone.localtime(latest_analysis.created_at).strftime("%d.%m.%Y %H:%M") if getattr(latest_analysis, "created_at", None) else "",
                        "is_applied": is_applied,
                        "applied_at": timezone.localtime(applied_at).strftime("%d.%m.%Y %H:%M") if applied_at else "",
                        "best_metric": getattr(latest_analysis, "best_metric", "") or "",
                        "worst_metric": getattr(latest_analysis, "worst_metric", "") or "",
                        "risk_score": float(getattr(latest_analysis, "risk_score", 0) or 0),
                        "risk_label": _octo_risk_label(getattr(latest_analysis, "risk_score", 0) or 0),
                        "trend_7d": getattr(latest_analysis, "trend_7d", "") or "",
                        "trend_30d": getattr(latest_analysis, "trend_30d", "") or "",
                        "competitor_position": getattr(latest_analysis, "competitor_position", "") or "",
                        "difficulty_level": getattr(latest_recommendation, "difficulty_level", "") if latest_recommendation else "",
                        "estimated_roas_gain": float(getattr(latest_recommendation, "estimated_roas_gain", 0) or 0) if latest_recommendation else 0,
                        "estimated_ctr_gain": float(getattr(latest_recommendation, "estimated_ctr_gain", 0) or 0) if latest_recommendation else 0,
                        "estimated_conversion_gain": float(getattr(latest_recommendation, "estimated_conversion_gain", 0) or 0) if latest_recommendation else 0,
                        "implementation_time": getattr(latest_recommendation, "implementation_time", "") if latest_recommendation else "",
                        "action_type": getattr(latest_recommendation, "action_type", "") if latest_recommendation else "",
                        "metrics": popup_metrics_payload,
                        "rule_findings": rule_findings or ["Seçili dönemde kritik kural eşleşmesi bulunamadı."],
                        "rule_events": structured_rule_findings,
                        "rule_period": f"{start_date:%d.%m.%Y} - {end_date:%d.%m.%Y}",
                        "rule_count": len(rule_events),
                        "mode": mode,
                    }, status=200)

        # Ana analiz metrikleri seçili tarih aralığından gelir.
        # 7 günlük trend ise seçili bitiş tarihine göre hesaplanır.
        last_7_start = end_date - timedelta(days=6)
        previous_7_start = end_date - timedelta(days=13)
        previous_7_end = last_7_start - timedelta(days=1)

        current_7_qs = CampaignMetricHistory.objects.filter(campaign=campaign, date__gte=last_7_start, date__lte=end_date) if CampaignMetricHistory else None
        previous_7_qs = CampaignMetricHistory.objects.filter(campaign=campaign, date__gte=previous_7_start, date__lte=previous_7_end) if CampaignMetricHistory else None

        current_7 = _metric_summary(current_7_qs)
        previous_7 = _metric_summary(previous_7_qs)

        status_raw = (getattr(campaign, "status", "UNKNOWN") or "UNKNOWN").upper()
        start_time = getattr(campaign, "start_time", None) or getattr(campaign, "created_at", None)
        age_days = None

        if start_time:
            try:
                age_days = max(0, (timezone.now() - start_time).days)
            except Exception:
                age_days = None

        is_learning = status_raw == "ACTIVE" and ((age_days is not None and age_days <= 7) or metrics["impressions"] < 1000)
        ctr_delta = current_7["ctr"] - previous_7["ctr"]
        spend_delta = current_7["spend"] - previous_7["spend"]

        performance_down = status_raw == "ACTIVE" and (
            ctr_delta < Decimal("-0.15")
            or (spend_delta > 0 and current_7["conversions"] <= previous_7["conversions"] and current_7["spend"] > previous_7["spend"])
        )

        health_score = 50
        if status_raw == "ACTIVE":
            health_score += 10
        if metrics["ctr"] >= Decimal("1"):
            health_score += 12
        if metrics["cpc"] > 0 and metrics["cpc"] <= Decimal("10"):
            health_score += 8
        if metrics["roas"] >= Decimal("2"):
            health_score += 15
        if performance_down:
            health_score -= 18
        if is_learning:
            health_score -= 5
        health_score = max(0, min(100, health_score))

        success_level, success_label, success_reason = _campaign_success_state(
            metrics, health_score, status_raw, performance_down=performance_down, is_learning=is_learning
        )

        analysis_items, recommendation_items = _build_octo_campaign_analysis(
            campaign, metrics, health_score, success_label, success_reason, current_7=current_7, previous_7=previous_7
        )

        if not analysis_items:
            analysis_items = [f"Başarı durumu: {success_label}.", success_reason]
        if not recommendation_items:
            recommendation_items = ["Kampanya metrikleri 3-7 gün boyunca izlenmeli."]

        daily_budget = _decimal(getattr(campaign, "daily_budget", None))
        lifetime_budget = _decimal(getattr(campaign, "lifetime_budget", None))
        budget = lifetime_budget if lifetime_budget > 0 else (daily_budget * Decimal(selected_days) if daily_budget > 0 else Decimal("0"))

        account = getattr(campaign, "platform_account", None)
        platform = getattr(account, "platform", None) if account else None
        if not platform and getattr(campaign, "platform_connection", None):
            platform = getattr(campaign.platform_connection, "platform", None)

        campaign_name = getattr(campaign, "name", None) or getattr(campaign, "campaign_name", None) or f"Kampanya #{campaign.id}"
        platform_name = getattr(platform, "name", "") if platform else ""
        account_name = getattr(account, "account_name", None) or getattr(account, "account_id", "") if account else ""
        objective = getattr(campaign, "objective", "") or ""

        source = "real"

        if success_level == "success":
            status_value = "excellent" if health_score >= 85 else "good"
            risk_level = "low"
        elif success_level == "danger":
            status_value = "critical" if health_score < 35 else "risky"
            risk_level = "critical" if health_score < 35 else "high"
        else:
            status_value = "watch"
            risk_level = "medium"

        best_metric, worst_metric = _octo_best_worst_metric(metrics)
        trend_7d = _octo_trend_label(current_7, previous_7)
        trend_30d = "stabil"
        risk_score = Decimal(str(_octo_risk_score(health_score, metrics, performance_down=performance_down)))
        risk_label = _octo_risk_label(risk_score)
        effects = _octo_estimated_effects(success_level, metrics)

        analysis_items = [
            f"Güçlü alan: {best_metric}.",
            f"Zayıf / izlenecek alan: {worst_metric}.",
            f"Son 7 gün trendi: {trend_7d}.",
            f"Risk skoru: {risk_score}/100 ({risk_label}).",
        ] + analysis_items

        recommendation_items = [
            f"Beklenen ROAS etkisi: +%{effects['estimated_roas_gain']}.",
            f"Beklenen CTR etkisi: +%{effects['estimated_ctr_gain']}.",
            f"Uygulama zorluğu: {effects['difficulty_level']}.",
            f"Tahmini uygulama süresi: {effects['implementation_time']}.",
        ] + recommendation_items

        if mode == "metrics":
            return JsonResponse({
                "ok": True, "mode": "metrics", "score": health_score,
                "success_label": success_label, "metrics": popup_metrics_payload,
                "best_metric": best_metric, "worst_metric": worst_metric,
                "risk_score": float(risk_score), "risk_label": risk_label,
                "trend_7d": trend_7d, "trend_30d": trend_30d,
                "competitor_position": "Rakip karşılaştırması bekleniyor",
                "estimated_roas_gain": effects["estimated_roas_gain"],
                "estimated_ctr_gain": effects["estimated_ctr_gain"],
                "difficulty_level": effects["difficulty_level"],
                "implementation_time": effects["implementation_time"],
                "analysis_items": analysis_items,
                "recommendation_items": recommendation_items,
                "rule_findings": rule_findings or ["Seçili dönemde kritik kural eşleşmesi bulunamadı."],
                "rule_events": structured_rule_findings,
                "rule_period": f"{start_date:%d.%m.%Y} - {end_date:%d.%m.%Y}",
                "rule_count": len(rule_events),
            })

        ai_context = {
            "campaign": {"id": campaign.id, "name": campaign_name, "platform": platform_name, "account": account_name, "objective": objective},
            "date_range": popup_metrics_payload,
            "metrics": {key: float(value) if isinstance(value, Decimal) else value for key, value in metrics.items()},
            "trends": {"current_7": current_7, "previous_7": previous_7, "trend_7d": trend_7d, "trend_30d": trend_30d},
            "health": {"score": health_score, "risk_score": float(risk_score), "risk_label": risk_label, "success_label": success_label},
            "matched_5000_rules": rule_findings,
        }
        ai_result = run_sixteen_agent_orchestration(
            client=OpenAI(api_key=settings.OPENAI_API_KEY),
            model=settings.OPENAI_MODEL,
            task=(
                "Kampanyanın mevcut metriklerini, trendlerini ve eşleşen kuralları derinlemesine analiz et; yalnızca kanıta dayalı tespitler üret."
                if mode == "analysis"
                else "Kampanyanın mevcut metriklerini, trendlerini ve eşleşen kuralları kullanarak öncelikli, uygulanabilir ve ölçülebilir öneriler üret."
            ),
            context=ai_context,
            modalities=["text"],
            reference=f"campaign_center.{mode}",
            user=request.user,
            organization=locals().get("organization"),
            tariff_key=("campaign-center-analysis" if mode == "analysis" else "campaign-center-recommendation"),
        )
        ai_agents = ai_result.get("agents") or []
        if mode == "analysis":
            analysis_items = [str(row.get("finding")).strip() for row in ai_agents if row.get("finding")]
            positioning = (ai_result.get("strategy") or {}).get("positioning")
            if positioning:
                analysis_items.insert(0, positioning)
        else:
            recommendation_items = [str(row.get("recommendation")).strip() for row in ai_agents if row.get("recommendation")]
            strategy = ai_result.get("strategy") or {}
            recommendation_items += [str(item) for item in (strategy.get("message_pillars") or [])]

        analysis_text = "\n".join(analysis_items)
        recommendation_text = "\n".join(recommendation_items)
        priority = "low" if success_level == "success" else ("high" if success_level == "danger" else "medium")
        score_decimal = Decimal(str(health_score))
        agents_payload = ai_result

        analysis_payload = {
            "user": request.user,
            "campaign": campaign,
            "octo_score": score_decimal,
            "analysis_score": score_decimal,
            "status": status_value,
            "risk_level": risk_level,
            "roas": metrics["roas"],
            "ctr": metrics["ctr"],
            "cpc": metrics["cpc"],
            "cpm": _decimal(metrics.get("cpm")),
            "spend": metrics["spend"],
            "budget": budget,
            "conversions": metrics["conversions"],
            "conversion_value": metrics["conversion_value"],
            "analysis_text": analysis_text,
            "agents_payload": agents_payload,
            "raw_ai_payload": {"source_view": "campaign_center_safe", "mode": "analysis", "items": analysis_items},
            "source": source,
            "campaign_name": campaign_name,
            "platform_name": platform_name,
            "account_name": account_name,
            "objective": objective,
            "recommendation_text": recommendation_text,
            "strengths": success_reason,
            "weaknesses": "",
            "next_actions": recommendation_text,
            "expected_impact": "Öneriler uygulandıktan sonra 3-7 gün içinde yeni metriklerle tekrar ölçülmelidir.",
            "priority": priority,
            "success_level": success_level,
            "success_label": success_label,
            "success_reason": success_reason,
            "best_metric": best_metric,
            "worst_metric": worst_metric,
            "risk_score": risk_score,
            "trend_7d": trend_7d,
            "trend_30d": trend_30d,
            "competitor_position": "Rakip karşılaştırması bekleniyor",
            "main_strength": f"En güçlü sinyal: {best_metric}",
            "main_weakness": f"İzlenecek sinyal: {worst_metric}",
            "risk_reason": f"Risk skoru {risk_score}/100 ({risk_label}) olarak hesaplandı.",
        }

        analysis = None
        save_error = ""
        if mode == "analysis":
            try:
                analysis_fields = {f.name for f in CampaignOctoAnalysis._meta.get_fields()}
                analysis = CampaignOctoAnalysis.objects.create(**{k: v for k, v in analysis_payload.items() if k in analysis_fields})
            except Exception as exc:
                save_error = str(exc)
        else:
            analysis = CampaignOctoAnalysis.objects.filter(campaign=campaign).order_by("-created_at", "-id").first()

        recommendation_payload = {
            "user": request.user,
            "campaign": campaign,
            "analysis": analysis,
            "campaign_name": campaign_name,
            "platform_name": platform_name,
            "account_name": account_name,
            "summary": f"{campaign_name} kampanyası için Octo sonucu: {success_label}.",
            "strengths": success_reason,
            "weaknesses": "",
            "recommendations": recommendation_text,
            "agents_payload": agents_payload,
            "raw_ai_payload": {"source_view": "campaign_center_safe", "mode": "recommendation", "items": recommendation_items},
            "expected_impact": "Öneriler uygulandıktan sonra 3-7 gün içinde yeni metriklerle tekrar ölçülmelidir.",
            "priority": priority,
            "source": source,
            "is_applied": False,
            "difficulty_level": effects["difficulty_level"],
            "estimated_roas_gain": effects["estimated_roas_gain"],
            "estimated_ctr_gain": effects["estimated_ctr_gain"],
            "estimated_conversion_gain": effects["estimated_conversion_gain"],
            "implementation_time": effects["implementation_time"],
            "action_type": effects["action_type"],
            "success_check_after_days": 7,
            "result_roas_before": metrics["roas"],
            "result_ctr_before": metrics["ctr"],
            "result_conversion_before": metrics["conversions"],
            "baseline_roas": metrics["roas"],
            "baseline_ctr": metrics["ctr"],
            "baseline_cpc": metrics["cpc"],
            "baseline_conversions": metrics["conversions"],
        }

        recommendation = None
        if mode == "recommendation":
            try:
                recommendation_fields = {f.name for f in CampaignOctoRecommendation._meta.get_fields()}
                recommendation = CampaignOctoRecommendation.objects.create(**{k: v for k, v in recommendation_payload.items() if k in recommendation_fields})
            except Exception as exc:
                save_error = (save_error + ' | ' if save_error else '') + str(exc)

        return JsonResponse({
            "ok": True,
            "cached": False,
            "mode": mode,
            "rule_findings": rule_findings or ["Seçili dönemde kritik kural eşleşmesi bulunamadı."],
            "rule_events": structured_rule_findings,
            "rule_period": f"{start_date:%d.%m.%Y} - {end_date:%d.%m.%Y}",
            "rule_count": len(rule_events),
            "save_error": save_error,
            "score": health_score,
            "label": success_label,
            "success_label": success_label,
            "analysis": analysis_items,
            "analysis_items": analysis_items,
            "recommendations": recommendation_items,
            "recommendation_items": recommendation_items,
            "analysis_id": analysis.id if analysis is not None else None,
            "recommendation_id": recommendation.id if recommendation is not None else None,
            "saved_at": timezone.localtime(analysis.created_at).strftime("%d.%m.%Y %H:%M") if analysis is not None and getattr(analysis, "created_at", None) else "",
            "created_at": timezone.localtime(analysis.created_at).strftime("%d.%m.%Y %H:%M") if analysis is not None and getattr(analysis, "created_at", None) else "",
            "is_applied": False,
            "applied_at": "",
            "best_metric": best_metric,
            "worst_metric": worst_metric,
            "risk_score": float(risk_score),
            "risk_label": risk_label,
            "trend_7d": trend_7d,
            "trend_30d": trend_30d,
            "competitor_position": "Rakip karşılaştırması bekleniyor",
            "difficulty_level": effects["difficulty_level"],
            "estimated_roas_gain": float(effects["estimated_roas_gain"]),
            "estimated_ctr_gain": float(effects["estimated_ctr_gain"]),
            "estimated_conversion_gain": float(effects["estimated_conversion_gain"]),
            "implementation_time": effects["implementation_time"],
            "action_type": effects["action_type"],
            "metrics": popup_metrics_payload,
        }, status=200)

    except Exception as exc:
        if charged_tariff_key:
            refund_ai_tariff_credits(
                user=request.user, organization=locals().get("organization"), tariff_key=charged_tariff_key, reason=str(exc), reference=charged_reference,
            )
        return JsonResponse({
            "ok": False,
            "message": f"Octo kampanya analizi oluşturulamadı. Detay: {exc}",
            "error": str(exc),
        }, status=502)


@login_required
def octo_campaign_analysis_pdf(request, analysis_id):
    """
    Octo kampanya analizini PDF raporu olarak indirir.
    ReportLab kullanır. Eğer reportlab kurulu değilse kullanıcıya net hata döner.

    Gerekirse:
        pip install reportlab
    """
    try:
        from io import BytesIO
        import os
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Image, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except Exception as exc:
        return JsonResponse({
            "ok": False,
            "error": "PDF üretimi için reportlab paketi gerekli.",
            "detail": str(exc),
            "install": "pip install reportlab",
        }, status=500)

    CampaignOctoAnalysis = _model("CampaignOctoAnalysis")
    CampaignOctoRecommendation = _model("CampaignOctoRecommendation")

    if not CampaignOctoAnalysis:
        return JsonResponse({"ok": False, "error": "CampaignOctoAnalysis modeli bulunamadı."}, status=404)

    analysis_qs = CampaignOctoAnalysis.objects.all()
    if _field(CampaignOctoAnalysis, "user"):
        analysis_qs = analysis_qs.filter(user=request.user)

    analysis = get_object_or_404(analysis_qs, id=analysis_id)

    recommendation = None
    if CampaignOctoRecommendation:
        rec_qs = CampaignOctoRecommendation.objects.filter(analysis=analysis)
        if _field(CampaignOctoRecommendation, "user"):
            rec_qs = rec_qs.filter(user=request.user)
        recommendation = rec_qs.order_by("-created_at").first()

    campaign = getattr(analysis, "campaign", None)
    platform_account = getattr(campaign, "platform_account", None) if campaign else None
    agency_client = getattr(platform_account, "agency_client", None) if platform_account else None
    branding = get_report_branding(request.user, agency_client=agency_client)
    campaign_name = (
        getattr(analysis, "campaign_name", "")
        or getattr(campaign, "name", "")
        or getattr(campaign, "campaign_name", "")
        or f"Kampanya #{getattr(campaign, 'id', analysis_id)}"
    )

    def clean_text(value):
        return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def tr_number(value, decimals=2):
        try:
            number = float(value or 0)
        except Exception:
            number = 0
        formatted = f"{number:,.{decimals}f}"
        return formatted.replace(",", "X").replace(".", ",").replace("X", ".")

    def tr_money(value):
        return f"{tr_number(value, 2)} TL"

    def split_items(value):
        rows = []
        for line in str(value or "").splitlines():
            line = line.strip().strip("-").strip()
            if line:
                rows.append(line)
        return rows

    analysis_items = split_items(getattr(analysis, "analysis_text", ""))
    if not analysis_items:
        analysis_items = [getattr(analysis, "success_reason", "") or "Analiz metni bulunamadı."]

    recommendation_text = ""
    if recommendation:
        recommendation_text = getattr(recommendation, "recommendations", "") or getattr(recommendation, "summary", "") or ""
    if not recommendation_text:
        recommendation_text = getattr(analysis, "recommendation_text", "") or getattr(analysis, "next_actions", "") or ""

    recommendation_items = split_items(recommendation_text)
    if not recommendation_items:
        recommendation_items = ["Öneri metni bulunamadı."]

    font_name = "Helvetica"
    bold_font_name = "Helvetica-Bold"

    font_candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    bold_candidates = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/Arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]

    for font_path in font_candidates:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont("RA-Regular", font_path))
                font_name = "RA-Regular"
                break
            except Exception:
                pass

    for font_path in bold_candidates:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont("RA-Bold", font_path))
                bold_font_name = "RA-Bold"
                break
            except Exception:
                pass

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.4 * cm,
        title=f"Octo Kampanya Analiz Raporu - {campaign_name}",
    )

    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="RA_Title",
        parent=styles["Title"],
        fontName=bold_font_name,
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#111827"),
        alignment=TA_CENTER,
        spaceAfter=10,
    ))

    styles.add(ParagraphStyle(
        name="RA_Subtitle",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#6B7280"),
        alignment=TA_CENTER,
        spaceAfter=16,
    ))

    styles.add(ParagraphStyle(
        name="RA_H2",
        parent=styles["Heading2"],
        fontName=bold_font_name,
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#111827"),
        spaceBefore=12,
        spaceAfter=7,
    ))

    styles.add(ParagraphStyle(
        name="RA_Body",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#1F2937"),
        alignment=TA_LEFT,
        spaceAfter=5,
    ))

    styles.add(ParagraphStyle(
        name="RA_Small",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#6B7280"),
    ))

    story = []

    if branding.logo_path:
        try:
            logo = Image(branding.logo_path)
            logo._restrictSize(4.2 * cm, 1.45 * cm)
            story.append(logo)
            story.append(Spacer(1, 8))
        except Exception:
            pass
    story.append(Paragraph(clean_text(branding.brand_name), styles["RA_Subtitle"]))
    story.append(Paragraph("Octo Kampanya Analiz Raporu", styles["RA_Title"]))
    story.append(Paragraph(clean_text(campaign_name), styles["RA_Subtitle"]))

    score = getattr(analysis, "octo_score", None) or getattr(analysis, "analysis_score", 0)
    created_at = getattr(analysis, "created_at", None)
    created_label = timezone.localtime(created_at).strftime("%d.%m.%Y %H:%M") if created_at else "-"

    summary_table = Table([
        ["Octo Skoru", f"{tr_number(score, 0)} / 100", "Durum", clean_text(getattr(analysis, "success_label", "") or getattr(analysis, "status", "-"))],
        ["Risk Skoru", f"{tr_number(getattr(analysis, 'risk_score', 0), 0)} / 100", "Risk Seviyesi", clean_text(getattr(analysis, "risk_level", "-"))],
        ["Güçlü Alan", clean_text(getattr(analysis, "best_metric", "-") or "-"), "İzlenecek Alan", clean_text(getattr(analysis, "worst_metric", "-") or "-")],
        ["7 Gün Trend", clean_text(getattr(analysis, "trend_7d", "-") or "-"), "30 Gün Trend", clean_text(getattr(analysis, "trend_30d", "-") or "-")],
        ["Rapor Tarihi", created_label, "Kaynak", clean_text(getattr(analysis, "source", "-") or "-")],
    ], colWidths=[3.1 * cm, 4.2 * cm, 3.2 * cm, 5.3 * cm])

    base_table_style = TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTNAME", (0, 0), (0, -1), bold_font_name),
        ("FONTNAME", (2, 0), (2, -1), bold_font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#111827")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ])

    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        *base_table_style.getCommands(),
    ]))

    story.append(summary_table)
    story.append(Spacer(1, 12))

    metric_table = Table([
        ["Harcama", tr_money(getattr(analysis, "spend", 0)), "Bütçe", tr_money(getattr(analysis, "budget", 0))],
        ["ROAS", f"{tr_number(getattr(analysis, 'roas', 0), 2)}x", "CTR", f"%{tr_number(getattr(analysis, 'ctr', 0), 2)}"],
        ["CPC", tr_money(getattr(analysis, "cpc", 0)), "CPM", tr_money(getattr(analysis, "cpm", 0))],
        ["Dönüşüm", tr_number(getattr(analysis, "conversions", 0), 0), "Dönüşüm Değeri", tr_money(getattr(analysis, "conversion_value", 0))],
    ], colWidths=[3.1 * cm, 4.2 * cm, 3.2 * cm, 5.3 * cm])
    metric_table.setStyle(base_table_style)

    story.append(Paragraph("Metrik Özeti", styles["RA_H2"]))
    story.append(metric_table)

    if recommendation:
        story.append(Paragraph("Beklenen Etki ve Uygulama", styles["RA_H2"]))
        rec_table = Table([
            ["Beklenen ROAS", f"+%{tr_number(getattr(recommendation, 'estimated_roas_gain', 0), 2)}", "Beklenen CTR", f"+%{tr_number(getattr(recommendation, 'estimated_ctr_gain', 0), 2)}"],
            ["Zorluk", clean_text(getattr(recommendation, "difficulty_level", "-") or "-"), "Süre", clean_text(getattr(recommendation, "implementation_time", "-") or "-")],
            ["Uygulandı mı?", "Evet" if getattr(recommendation, "is_applied", False) else "Hayır", "Kontrol Süresi", f"{getattr(recommendation, 'success_check_after_days', 7) or 7} gün"],
        ], colWidths=[3.1 * cm, 4.2 * cm, 3.2 * cm, 5.3 * cm])
        rec_table.setStyle(base_table_style)
        story.append(rec_table)

    story.append(Paragraph("1. Octo Kampanya Analizi", styles["RA_H2"]))
    for item in analysis_items:
        story.append(Paragraph(f"- {clean_text(item)}", styles["RA_Body"]))

    story.append(Paragraph("2. Octo Yorum & Öneri", styles["RA_H2"]))
    for item in recommendation_items:
        story.append(Paragraph(f"- {clean_text(item)}", styles["RA_Body"]))

    story.append(Spacer(1, 10))
    footer = branding.footer_note or "Bu rapor ReklamAnaliz.net Octo AI tarafından otomatik oluşturulmuştur."
    story.append(Paragraph(clean_text(footer), styles["RA_Small"]))

    doc.build(story)

    filename = f"octo-kampanya-analiz-{analysis.id}.pdf"
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
