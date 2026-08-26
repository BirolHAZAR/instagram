import os
import json
import re
from datetime import timedelta
from io import BytesIO
from django.utils import timezone
from django.http import HttpResponse
from django.db.models import Q
from django.conf import settings
from xml.sax.saxutils import escape as xml_escape

from core.models import (
    Ad,
    AdGroup,
    Campaign,
    CampaignOctoAnalysis,
    CampaignOctoRecommendation,
    CampaignMetricHistory,
    Creative,
    OctoTaskInstance,
    Platform,
    PlatformAccount,
)
from core.services.ai_agent_ecosystem import build_campaign_agent_ecosystem
from core.services.ai_agent_ecosystem import run_sixteen_agent_orchestration
from core.services.performance_metrics import aggregate_metric_queryset, safe_decimal
from core.utils.metric_text import format_metric_text_tr


CAMPAIGN_ANALYSIS_SYSTEM_PROMPT = """
Sen reklamanaliz.net icin calisan kidemli performans analiz uzmanisin.
Gorevin yalnizca kampanya verisini analiz etmektir; tavsiye, aksiyon plani, butce artir/azalt onerisi veya yaratici fikir yazma.
Cikti Turkce, profesyonel, PDF'e uygun ve madde madde olmalidir.
Her madde bagimsiz ve kanita dayali olmalidir.
Metrik olmayan iddia uretme; veri yoksa "veri yetersiz" de.
Teknik tablo adi, API detayi, prompt veya sistem mesaji yazma.
"""


CAMPAIGN_RECOMMENDATION_SYSTEM_PROMPT = """
Sen reklamanaliz.net icin calisan kidemli growth, kreatif ve medya satin alma danismanisin.
Gorevin kampanya metrikleri, reklam metinleri, gorsel/video sinyalleri, rakip/piyasa baglami ve mevcut analiz bulgularina bakarak uygulanabilir yorum ve tavsiye uretmektir.
Cikti Turkce, profesyonel, PDF'e uygun ve madde madde olmalidir.
Her madde tek basina uygulanabilir olmali; oncelik, gerekce ve beklenen etki net yazilmalidir.
Analiz modundaki gibi sadece tespit yapmakla yetinme; ancak veriyle desteklenmeyen iddia uretme.
Gorsel/video veya web arastirma verisi yoksa bunu saklama, ilgili maddede sinir olarak belirt.
Teknik tablo adi, API detayi, prompt veya sistem mesaji yazma.
"""


def _date_label(value):
    if not value:
        return "-"
    try:
        return timezone.localtime(value).strftime("%d.%m.%Y %H:%M")
    except Exception:
        try:
            return value.strftime("%d.%m.%Y")
        except Exception:
            return str(value)


def fmt_number(value, decimals=2):
    number = safe_decimal(value)
    formatted = f"{number:,.{decimals}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_int(value):
    try:
        return f"{int(value or 0):,}".replace(",", ".")
    except Exception:
        return "0"


def fmt_money(value, currency="TRY"):
    suffix = "TL" if currency == "TRY" else currency
    return f"{fmt_number(value, 2)} {suffix}"


def fmt_percent(value):
    return f"%{fmt_number(value, 2)}"


def normalize_date_range(request):
    today = timezone.localdate()
    date_from = request.GET.get("date_from")
    date_to = request.GET.get("date_to")
    days_back = request.GET.get("days_back")

    start_date = None
    end_date = today

    if date_from:
        try:
            start_date = timezone.datetime.strptime(date_from, "%Y-%m-%d").date()
        except Exception:
            start_date = None

    if date_to:
        try:
            end_date = timezone.datetime.strptime(date_to, "%Y-%m-%d").date()
        except Exception:
            end_date = today

    if start_date is None and days_back:
        try:
            days = max(1, min(int(days_back), 3650))
            start_date = end_date - timedelta(days=days - 1)
        except Exception:
            start_date = None

    if start_date and start_date > end_date:
        start_date, end_date = end_date, start_date

    return start_date, end_date


def metric_qs_by_date(qs, start_date=None, end_date=None):
    if start_date:
        qs = qs.filter(date__gte=start_date)
    if end_date:
        qs = qs.filter(date__lte=end_date)
    return qs


def aggregate_metrics(qs):
    return aggregate_metric_queryset(qs)


def metric_payload(summary, currency="TRY"):
    return {
        "impressions": int(summary.get("impressions") or 0),
        "impressions_label": fmt_int(summary.get("impressions")),
        "reach": int(summary.get("reach") or 0),
        "reach_label": fmt_int(summary.get("reach")),
        "clicks": int(summary.get("clicks") or 0),
        "clicks_label": fmt_int(summary.get("clicks")),
        "link_clicks": int(summary.get("link_clicks") or 0),
        "link_clicks_label": fmt_int(summary.get("link_clicks")),
        "unique_clicks": int(summary.get("unique_clicks") or 0),
        "unique_clicks_label": fmt_int(summary.get("unique_clicks")),
        "spend": float(safe_decimal(summary.get("spend"))),
        "spend_label": fmt_money(summary.get("spend"), currency),
        "revenue": float(safe_decimal(summary.get("conversion_value"))),
        "revenue_label": fmt_money(summary.get("conversion_value"), currency),
        "conversions": float(safe_decimal(summary.get("conversions"))),
        "conversions_label": fmt_number(summary.get("conversions"), 2),
        "purchases": float(safe_decimal(summary.get("purchases"))),
        "purchases_label": fmt_number(summary.get("purchases"), 2),
        "add_to_cart": float(safe_decimal(summary.get("add_to_cart"))),
        "add_to_cart_label": fmt_number(summary.get("add_to_cart"), 2),
        "initiate_checkout": float(safe_decimal(summary.get("initiate_checkout"))),
        "initiate_checkout_label": fmt_number(summary.get("initiate_checkout"), 2),
        "leads": float(safe_decimal(summary.get("leads"))),
        "leads_label": fmt_number(summary.get("leads"), 2),
        "landing_page_views": int(summary.get("landing_page_views") or 0),
        "landing_page_views_label": fmt_int(summary.get("landing_page_views")),
        "outbound_clicks": int(summary.get("outbound_clicks") or 0),
        "outbound_clicks_label": fmt_int(summary.get("outbound_clicks")),
        "likes": int(summary.get("likes") or 0),
        "likes_label": fmt_int(summary.get("likes")),
        "comments": int(summary.get("comments") or 0),
        "comments_label": fmt_int(summary.get("comments")),
        "shares": int(summary.get("shares") or 0),
        "shares_label": fmt_int(summary.get("shares")),
        "saves": int(summary.get("saves") or 0),
        "saves_label": fmt_int(summary.get("saves")),
        "video_views": int(summary.get("video_views") or 0),
        "video_views_label": fmt_int(summary.get("video_views")),
        "engagement": int(summary.get("engagement") or 0),
        "engagement_label": fmt_int(summary.get("engagement")),
        "ctr": float(safe_decimal(summary.get("ctr"))),
        "ctr_label": fmt_percent(summary.get("ctr")),
        "cpc": float(safe_decimal(summary.get("cpc"))),
        "cpc_label": fmt_money(summary.get("cpc"), currency),
        "cpm": float(safe_decimal(summary.get("cpm"))),
        "cpm_label": fmt_money(summary.get("cpm"), currency),
        "cpa": float(safe_decimal(summary.get("cpa"))),
        "cpa_label": fmt_money(summary.get("cpa"), currency),
        "roas": float(safe_decimal(summary.get("roas"))),
        "roas_label": fmt_number(summary.get("roas"), 2),
        "frequency": float(safe_decimal(summary.get("avg_frequency"))),
        "frequency_label": fmt_number(summary.get("avg_frequency"), 2),
        "engagement_rate": float(safe_decimal(summary.get("avg_engagement_rate"))),
        "engagement_rate_label": fmt_percent(summary.get("avg_engagement_rate")),
        "metric_rows": int(summary.get("rows") or 0),
        "last_metric_date": summary.get("last_date").strftime("%d.%m.%Y") if summary.get("last_date") else "-",
    }


def status_label(status):
    return {
        "ACTIVE": "Aktif",
        "ENABLED": "Aktif",
        "PAUSED": "Duraklatıldı",
        "DELETED": "Silindi",
        "ARCHIVED": "Arşivlendi",
        "ENDED": "Bitti",
        "UNKNOWN": "Bilinmiyor",
    }.get((status or "UNKNOWN").upper(), status or "Bilinmiyor")


def media_url_for_ad(ad):
    creative = getattr(ad, "creative", None)
    return (
        getattr(ad, "preview_image_url", None)
        or (getattr(creative, "thumbnail_url", None) if creative else None)
        or (getattr(creative, "image_url", None) if creative else None)
        or ""
    )


def campaign_card_payload(campaign, start_date=None, end_date=None):
    metrics = metric_qs_by_date(campaign.metric_history.all(), start_date, end_date)
    summary = aggregate_metrics(metrics)
    currency = getattr(campaign, "currency", "TRY") or "TRY"
    metrics_payload = metric_payload(summary, currency)

    ad_qs = campaign.ads.filter(source_type="OWN")
    ad_group_qs = campaign.ad_groups.all()
    creative_count = ad_qs.exclude(creative__isnull=True).values("creative_id").distinct().count()
    ad_count = ad_qs.count()
    ad_group_count = ad_group_qs.count()

    platform = "-"
    try:
        if campaign.platform_account and campaign.platform_account.platform:
            platform = campaign.platform_account.platform.name
    except Exception:
        pass

    return {
        "id": campaign.id,
        "name": campaign.name,
        "platform_campaign_id": campaign.platform_campaign_id,
        "platform": platform,
        "account_name": getattr(getattr(campaign, "platform_account", None), "account_name", "") or getattr(getattr(campaign, "platform_account", None), "account_id", "") or "-",
        "account_id": getattr(getattr(campaign, "platform_account", None), "account_id", "") or "-",
        "status": campaign.status,
        "status_label": status_label(campaign.status),
        "objective": campaign.objective or "UNKNOWN",
        "objective_label": campaign.get_objective_display() if hasattr(campaign, "get_objective_display") else (campaign.objective or "UNKNOWN"),
        "daily_budget": float(safe_decimal(campaign.daily_budget)),
        "daily_budget_label": fmt_money(campaign.daily_budget, currency),
        "lifetime_budget": float(safe_decimal(campaign.lifetime_budget)),
        "lifetime_budget_label": fmt_money(campaign.lifetime_budget, currency),
        "currency": currency,
        "start_time": campaign.start_time.strftime("%d.%m.%Y") if campaign.start_time else "-",
        "end_time": campaign.end_time.strftime("%d.%m.%Y") if campaign.end_time else "-",
        "last_synced_at": _date_label(campaign.last_synced_at),
        "created_at": _date_label(campaign.created_at),
        "updated_at": _date_label(campaign.updated_at),
        "is_active": bool(campaign.is_active),
        "raw_data_keys": sorted(list((campaign.raw_data or {}).keys()))[:24],
        "ad_group_count": ad_group_count,
        "ad_count": ad_count,
        "creative_count": creative_count,
        "metrics": metrics_payload,
        "rule_events": build_campaign_rule_events(campaign, metrics_payload),
    }


def severity_label(severity):
    return {
        "critical": "Kritik",
        "warning": "Uyarı",
        "info": "Bilgi",
        "opportunity": "Fırsat",
        "high": "Yüksek",
        "medium": "Orta",
        "low": "Düşük",
    }.get((severity or "").lower(), severity or "Bilgi")


def build_campaign_rule_events(campaign, metrics):
    task_qs = (
        OctoTaskInstance.objects
        .filter(user=campaign.user)
        .filter(
            Q(campaign=campaign)
            | Q(ad_group__campaign=campaign)
            | Q(ad__campaign=campaign)
        )
        .filter(Q(rule__isnull=True) | Q(rule__is_active=True))
        .exclude(status__in=["done", "dismissed"])
        .select_related("rule", "ad_group", "ad", "creative")
        .order_by("-priority_score", "-last_detected_at")[:8]
    )
    events = []
    seen_event_titles = set()
    for task in task_qs:
        rule = task.rule
        event_title = task.title_tr or (rule.title_tr if rule else "Kural olayı")
        event_key = _normalized_text_key(event_title)
        if event_key in seen_event_titles:
            continue
        seen_event_titles.add(event_key)
        events.append({
            "source": "Octo Kuralı",
            "module": task.get_module_display() if hasattr(task, "get_module_display") else task.module,
            "severity": task.severity,
            "severity_label": severity_label(task.severity),
            "event": task.title_tr or (rule.title_tr if rule else "Kural olayı"),
            "description": format_metric_text_tr(task.message_tr or (rule.message_tr if rule else "")),
            "solution": format_metric_text_tr(task.action_text_tr or (rule.action_text_tr if rule else "") or (rule.expected_result if rule else "") or "İlgili kampanya, reklam grubu ve reklam metriklerini kontrol et."),
            "root_cause": format_metric_text_tr((rule.root_cause if rule else "") or ""),
            "status": task.get_status_display() if hasattr(task, "get_status_display") else task.status,
            "detected_at": _date_label(task.last_detected_at),
        })

    if events:
        return events

    roas = float(metrics.get("roas") or 0)
    ctr = float(metrics.get("ctr") or 0)
    spend = float(metrics.get("spend") or 0)
    conversions = float(metrics.get("conversions") or 0)
    impressions = int(metrics.get("impressions") or 0)
    frequency = float(metrics.get("frequency") or 0)
    cpc = float(metrics.get("cpc") or 0)
    metric_rows = int(metrics.get("metric_rows") or 0)

    def add(severity, module, event, description, solution):
        events.append({
            "source": "Otomatik performans kontrolü",
            "module": module,
            "severity": severity,
            "severity_label": severity_label(severity),
            "event": event,
            "description": description,
            "solution": solution,
            "root_cause": "",
            "status": "Açık",
            "detected_at": metrics.get("last_metric_date") or "-",
        })

    if metric_rows == 0:
        add("warning", "Veri", "Metrik geçmişi yok", "Bu kampanya için seçili tarih aralığında CampaignMetricHistory kaydı bulunamadı.", "Önce kampanya senkronizasyonunu çalıştır, ardından metrik geçmişi ve dönüşüm alanlarının dolduğunu kontrol et.")
    if spend > 0 and conversions == 0:
        add("critical", "Dönüşüm", "Harcama var, dönüşüm yok", f"{metrics.get('spend_label')} harcama var fakat dönüşüm 0 görünüyor.", "Pixel/CAPI, dönüşüm aksiyonu eşlemesi, UTM ve landing page dönüşüm olaylarını kontrol et.")
    if spend > 0 and roas < 1:
        add("critical", "Bütçe", "ROAS hedefin altında", f"ROAS {metrics.get('roas_label')} seviyesinde; harcama verimli gelire dönüşmüyor.", "Bütçeyi geçici olarak kıs, en zayıf reklam gruplarını ayır ve kazanan kreatiflere kontrollü bütçe aktar.")
    if impressions > 0 and ctr < 1:
        add("warning", "Kreatif", "CTR düşük", f"CTR {metrics.get('ctr_label')} seviyesinde.", "Başlık, görsel/video ilk karesi, teklif ve hedef kitle kırılımları için A/B test oluştur.")
    if frequency >= 3:
        add("warning", "Kreatif", "Frekans yükselmiş", f"Frekans {metrics.get('frequency_label')} seviyesine çıkmış.", "Yorgun kreatifleri değiştir, yeni varyasyon ekle veya hedef kitleyi genişlet.")
    if cpc > 0 and ctr < 1.5:
        add("info", "Maliyet", "CPC izlenmeli", f"CPC {metrics.get('cpc_label')} ve CTR sınırlı.", "Tıklama maliyetini düşürmek için reklam metni, hedefleme ve yerleşim performansını karşılaştır.")

    if not events:
        add("info", "Performans", "Performans kontrolü", "Seçili aralıkta temel metrikler kontrol edildi.", "ROAS, CTR, CPC, dönüşüm ve frekans kırılımlarını günlük izleyip sapma oluşursa bütçe ve kreatif aksiyonlarını uygula.")
        add("opportunity", "Kreatif", "Kreatif yenileme kontrolü", "Kampanyada kritik düşüş görünmese bile kreatif yorgunluğu düzenli takip edilmeli.", "En iyi reklam metni/görsel kombinasyonundan yeni varyasyonlar üret ve düşük performanslı kreatifleri test dışına al.")
        if roas >= 2 and spend > 0:
            add("opportunity", "Bütçe", "Ölçekleme fırsatı", f"ROAS {metrics.get('roas_label')} seviyesinde.", "Bütçeyi tek seferde değil, kontrollü küçük artışlarla ölçekle ve sonraki 48 saatte ROAS/CPA etkisini takip et.")
    return events[:8]


def _plain_lines(items, limit=7):
    lines = []
    seen = set()
    for item in items or []:
        text = str(item or "").strip()
        key = _normalized_text_key(text)
        if text and key and key not in seen:
            lines.append(text)
            seen.add(key)
        if len(lines) >= limit:
            break
    return lines


def _text_lines(items, limit=12):
    return "\n".join(_plain_lines(items, limit))


def _summary_lines(text, limit=12):
    lines = []
    seen = set()
    ignored_headings = {
        "kanita dayali kampanya analizi",
        "oncelikli uygulanabilir oneriler",
        "kampanya metrikleri incelendi one cikan bulgular",
        "uygulanacak oncelikli aksiyonlar",
    }
    for raw_line in str(text or "").replace("\r", "\n").split("\n"):
        line = raw_line.strip().lstrip("-").strip()
        key = _normalized_text_key(line)
        if line and key and key not in ignored_headings and key not in seen:
            lines.append(line)
            seen.add(key)
        if len(lines) >= limit:
            break
    return lines


def _normalized_text_key(value):
    text = str(value or "").casefold().strip()
    translation = str.maketrans("çğıöşü", "cgiosu")
    return re.sub(r"[^a-z0-9]+", " ", text.translate(translation)).strip()


def _dedupe_recommendations(items, limit=12):
    result = []
    seen = set()
    for item in items or []:
        key = _normalized_text_key(item.get("title") or item.get("detail"))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _campaign_status_key(score):
    score = float(score or 0)
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 45:
        return "watch"
    if score >= 25:
        return "risky"
    return "critical"


def _campaign_risk_key(score):
    score = float(score or 0)
    if score >= 75:
        return "low"
    if score >= 55:
        return "medium"
    if score >= 30:
        return "high"
    return "critical"


def _campaign_success_key(score):
    score = float(score or 0)
    if score >= 70:
        return "success"
    if score >= 45:
        return "warning"
    if score >= 25:
        return "danger"
    return "learning"


def _recommendation_priority(items):
    text = " ".join(
        f"{item.get('priority', '')} {item.get('title', '')}" for item in items or []
    ).lower()
    if any(word in text for word in ["urgent", "acil", "kritik", "critical"]):
        return "urgent"
    if any(word in text for word in ["high", "yuksek", "yüksek"]):
        return "high"
    if any(word in text for word in ["low", "dusuk", "düşük"]):
        return "low"
    return "medium"


def _persist_campaign_ai_report(user, campaign, report):
    report_type = report.get("type") or "analysis"
    campaign_data = report.get("campaign") or {}
    metrics = report.get("metrics") or {}
    recommendations = report.get("recommendations") or []
    agents_payload = report.get("agent_ecosystem") or report.get("agents") or []
    score = float(report.get("score") or 0)
    budget = safe_decimal(campaign.daily_budget or campaign.lifetime_budget)

    if report_type == "analysis":
        analysis = CampaignOctoAnalysis.objects.create(
            user=user,
            campaign=campaign,
            campaign_name=campaign_data.get("name") or campaign.name,
            platform_name=campaign_data.get("platform") or "",
            account_name=campaign_data.get("account") or "",
            objective=campaign_data.get("objective") or "",
            octo_score=score,
            analysis_score=score,
            status=_campaign_status_key(score),
            risk_level=_campaign_risk_key(score),
            success_level=_campaign_success_key(score),
            success_label=report.get("score_label") or _score_label(score),
            success_reason=_text_lines(report.get("findings"), 4),
            roas=safe_decimal(metrics.get("roas")),
            ctr=safe_decimal(metrics.get("ctr")),
            cpc=safe_decimal(metrics.get("cpc")),
            cpm=safe_decimal(metrics.get("cpm")),
            spend=safe_decimal(metrics.get("spend")),
            budget=budget,
            conversions=safe_decimal(metrics.get("conversions")),
            conversion_value=safe_decimal(metrics.get("revenue")),
            analysis_text=report.get("summary") or _text_lines(report.get("findings"), 8),
            recommendation_text="",
            agents_payload=agents_payload,
            raw_ai_payload=report,
            strengths=_text_lines(report.get("strengths"), 8),
            weaknesses=_text_lines(report.get("weaknesses"), 8),
            next_actions="",
            expected_impact="",
            priority="medium",
            source="campaign_panel_ai",
        )
        return {"analysis_id": analysis.id, "recommendation_id": None}

    last_analysis = CampaignOctoAnalysis.objects.filter(user=user, campaign=campaign).order_by("-created_at").first()
    recommendation_text = _text_lines(
        [f"{item.get('title')}: {item.get('detail')}" for item in recommendations],
        12,
    )
    recommendation = CampaignOctoRecommendation.objects.create(
        user=user,
        campaign=campaign,
        analysis=last_analysis,
        campaign_name=campaign_data.get("name") or campaign.name,
        platform_name=campaign_data.get("platform") or "",
        account_name=campaign_data.get("account") or "",
        summary=report.get("summary") or recommendation_text,
        strengths=_text_lines(report.get("strengths"), 8),
        weaknesses=_text_lines(report.get("weaknesses"), 8),
        recommendations=recommendation_text,
        agents_payload=agents_payload,
        raw_ai_payload=report,
        expected_impact="AI yorum ve öneri çıktıktan sonra 3-7 gün içinde ROAS, CTR, CPC ve dönüşüm değişimi izlenmelidir.",
        priority=_recommendation_priority(recommendations),
        baseline_roas=safe_decimal(metrics.get("roas")),
        baseline_ctr=safe_decimal(metrics.get("ctr")),
        baseline_cpc=safe_decimal(metrics.get("cpc")),
        baseline_conversions=safe_decimal(metrics.get("conversions")),
        success_check_after_days=7,
        source="campaign_panel_ai",
    )
    return {
        "analysis_id": last_analysis.id if last_analysis else None,
        "recommendation_id": recommendation.id,
    }


def _split_saved_lines(text, limit=12):
    return _summary_lines(text, limit)


def _saved_metrics_payload(record, currency="TRY"):
    return {
        "roas": float(safe_decimal(getattr(record, "roas", 0))),
        "roas_label": fmt_number(getattr(record, "roas", 0), 2),
        "ctr": float(safe_decimal(getattr(record, "ctr", 0))),
        "ctr_label": fmt_percent(getattr(record, "ctr", 0)),
        "cpc": float(safe_decimal(getattr(record, "cpc", 0))),
        "cpc_label": fmt_money(getattr(record, "cpc", 0), currency),
        "cpm": float(safe_decimal(getattr(record, "cpm", 0))),
        "cpm_label": fmt_money(getattr(record, "cpm", 0), currency),
        "spend": float(safe_decimal(getattr(record, "spend", 0))),
        "spend_label": fmt_money(getattr(record, "spend", 0), currency),
        "revenue": float(safe_decimal(getattr(record, "conversion_value", 0))),
        "revenue_label": fmt_money(getattr(record, "conversion_value", 0), currency),
        "conversions": float(safe_decimal(getattr(record, "conversions", 0))),
        "conversions_label": fmt_number(getattr(record, "conversions", 0), 2),
    }


def _saved_recommendation_items(text, limit=12):
    items = []
    for line in _split_saved_lines(text, limit):
        title, sep, detail = line.partition(":")
        items.append({
            "title": title.strip() if sep else line,
            "detail": detail.strip() if sep else "",
            "priority": "Kayitli",
        })
    return items


def get_saved_campaign_ai_report(user, campaign, report_type="analysis"):
    currency = getattr(campaign, "currency", "TRY") or "TRY"
    account = getattr(campaign, "platform_account", None)
    platform = getattr(account, "platform", None)
    campaign_info = {
        "id": campaign.id,
        "name": campaign.name,
        "platform": getattr(platform, "name", "") or getattr(platform, "code", "") or "",
        "account": getattr(account, "account_name", "") or getattr(account, "account_id", "") or "",
        "status": campaign.get_status_display() if hasattr(campaign, "get_status_display") else getattr(campaign, "status", ""),
        "objective": campaign.get_objective_display() if hasattr(campaign, "get_objective_display") else getattr(campaign, "objective", ""),
    }

    if report_type == "recommendation":
        rec = CampaignOctoRecommendation.objects.filter(user=user, campaign=campaign).order_by("-created_at", "-id").first()
        if not rec:
            return None
        analysis = getattr(rec, "analysis", None)
        metrics_source = analysis or rec
        recommendations = _saved_recommendation_items(rec.recommendations or rec.summary)
        metrics_payload = _saved_metrics_payload(metrics_source, currency)
        current_rule_events = build_campaign_rule_events(campaign, metrics_payload)
        return {
            "success": True,
            "type": "recommendation",
            "title": "Yorum ve Aksiyon Önerileri",
            "generated_at": _date_label(rec.created_at),
            "campaign": campaign_info,
            "score": round(float(getattr(analysis, "analysis_score", 0) or getattr(analysis, "octo_score", 0) or 0), 1) if analysis else 0,
            "score_label": getattr(analysis, "success_label", "Kayitli") if analysis else "Kayitli",
            "metrics": metrics_payload,
            "summary": rec.summary,
            "summary_items": _split_saved_lines(rec.summary),
            "findings": [],
            "rule_events": current_rule_events,
            "trend": {},
            "strengths": _split_saved_lines(rec.strengths, 8),
            "weaknesses": _split_saved_lines(rec.weaknesses, 8),
            "recommendations": recommendations,
            "agents": [],
            "agent_ecosystem": getattr(rec, "agents_payload", []) or [],
            "top_ads": [],
            "octo_records": {},
            "data_source": "Kayitli CampaignOctoRecommendation",
            "analysis_id": rec.analysis_id,
            "recommendation_id": rec.id,
            "cached": True,
        }

    analysis = CampaignOctoAnalysis.objects.filter(user=user, campaign=campaign).order_by("-created_at", "-id").first()
    if not analysis:
        return None
    metrics_payload = _saved_metrics_payload(analysis, currency)
    current_rule_events = build_campaign_rule_events(campaign, metrics_payload)
    rule_title_keys = {_normalized_text_key(row.get("event")) for row in current_rule_events}
    findings = [
        line for line in _split_saved_lines(analysis.success_reason, 12)
        if not any(key and key in _normalized_text_key(line) for key in rule_title_keys)
    ][:8]
    return {
        "success": True,
        "type": "analysis",
        "title": "Derin Kampanya Analizi",
        "generated_at": _date_label(analysis.created_at),
        "campaign": campaign_info,
        "score": round(float(analysis.analysis_score or analysis.octo_score or 0), 1),
        "score_label": analysis.success_label,
        "metrics": metrics_payload,
        "summary": analysis.analysis_text,
        "summary_items": _split_saved_lines(analysis.analysis_text),
        "findings": findings,
        "rule_events": current_rule_events,
        "trend": {},
        "strengths": _split_saved_lines(analysis.strengths, 8),
        "weaknesses": _split_saved_lines(analysis.weaknesses, 8),
        "recommendations": [],
        "agents": [],
        "agent_ecosystem": getattr(analysis, "agents_payload", []) or [],
        "top_ads": [],
        "octo_records": {},
        "data_source": "Kayitli CampaignOctoAnalysis",
        "analysis_id": analysis.id,
        "recommendation_id": None,
        "cached": True,
    }


def _campaign_metric_findings(metrics, rule_events):
    findings = []
    roas = float(metrics.get("roas") or 0)
    ctr = float(metrics.get("ctr") or 0)
    spend = float(metrics.get("spend") or 0)
    conversions = float(metrics.get("conversions") or 0)
    revenue = float(metrics.get("revenue") or 0)
    impressions = int(metrics.get("impressions") or 0)
    frequency = float(metrics.get("frequency") or 0)
    cpc = float(metrics.get("cpc") or 0)
    cpa = float(metrics.get("cpa") or 0)

    if spend > 0:
        findings.append(f"Harcama {metrics.get('spend_label')} seviyesinde; gelir {metrics.get('revenue_label')} ve ROAS {metrics.get('roas_label')} olarak görünüyor.")
    if spend > 0 and conversions == 0:
        findings.append("Harcama olmasına rağmen dönüşüm kaydı yok; dönüşüm ölçümü ve kampanya hedefi birlikte kontrol edilmeli.")
    if revenue > 0 and roas < 2:
        findings.append("Gelir oluşmuş ancak ROAS hedef seviyeye göre zayıf; bütçe dağılımı ve reklam grubu kırılımı incelenmeli.")
    if impressions > 0 and ctr < 1:
        findings.append(f"CTR {metrics.get('ctr_label')} seviyesinde; kreatif mesaj veya hedef kitle ilgisi sınırlı kalıyor.")
    if cpc > 0:
        findings.append(f"CPC {metrics.get('cpc_label')} olarak görünüyor; tıklama maliyeti reklam metni ve yerleşim kırılımıyla karşılaştırılmalı.")
    if cpa > 0:
        findings.append(f"CPA {metrics.get('cpa_label')} seviyesinde; dönüşüm başı maliyet hedefle karşılaştırılmalı.")
    if frequency >= 3:
        findings.append(f"Frekans {metrics.get('frequency_label')} seviyesine çıkmış; kreatif yorgunluğu riski izlenmeli.")
    if not findings:
        findings.append("Kampanyada okunabilir metrik hacmi sınırlı; önce senkronizasyon ve dönüşüm verisi doğrulanmalı.")
    return _plain_lines(findings, 8)


def _campaign_action_plan(metrics, rule_events):
    actions = []
    for event in rule_events[:5]:
        actions.append({
            "title": event.get("event") or "Kontrol",
            "detail": event.get("solution") or event.get("description") or "Kampanya metriklerini kontrol et.",
            "priority": event.get("severity_label") or "Orta",
        })
    roas = float(metrics.get("roas") or 0)
    spend = float(metrics.get("spend") or 0)
    conversions = float(metrics.get("conversions") or 0)
    ctr = float(metrics.get("ctr") or 0)
    if spend > 0 and conversions == 0:
        actions.insert(0, {"title": "Dönüşüm ölçümünü doğrula", "detail": "Pixel/CAPI, platform dönüşüm aksiyonu, UTM ve landing page event akışını kontrol et.", "priority": "Kritik"})
    if spend > 0 and roas < 1:
        actions.insert(0, {"title": "Verimsiz harcamayı sınırla", "detail": "ROAS toparlanana kadar düşük performanslı reklam gruplarında bütçeyi azalt ve kazanan kreatifleri ayır.", "priority": "Kritik"})
    if ctr < 1:
        actions.append({"title": "Kreatif ve hedefleme testi aç", "detail": "İlk görsel/video karesi, başlık, teklif ve hedef kitle segmenti için en az iki yeni varyasyon test et.", "priority": "Yüksek"})
    if roas >= 2 and conversions > 0:
        actions.append({"title": "Kontrollü ölçekleme yap", "detail": "Bütçeyi küçük kademelerle artır, sonraki 48 saat ROAS ve CPA değişimini takip et.", "priority": "Fırsat"})
    return actions[:10]


def _campaign_creative_context(campaign, top_ads):
    creatives = []
    for ad in (top_ads or [])[:5]:
        image_url = ad.get("media_url") or ""
        video_url = ad.get("video_url") or ""
        creatives.append({
            "name": ad.get("name") or "",
            "headline": ad.get("headline") or "",
            "primary_text": ad.get("primary_text") or "",
            "description": ad.get("description") or "",
            "call_to_action": ad.get("call_to_action") or "",
            "landing_url": ad.get("landing_url") or "",
            "image_url": image_url,
            "video_url": video_url,
            "has_visual_input": bool(image_url or video_url),
            "media_type": "video" if video_url else ("image" if image_url else "text_only"),
        })
    return creatives


def _campaign_market_context(campaign, top_ads):
    try:
        from core.services.web_market_research import build_campaign_market_context
    except Exception:
        return {"enabled": False, "items": [], "note": "Piyasa arastirma servisi yuklenemedi."}
    return build_campaign_market_context(campaign, top_ads)


def _message_content_for_recommendation(user_prompt, creative_context):
    content = [{"type": "text", "text": user_prompt}]
    image_count = 0
    for creative in creative_context:
        image_url = creative.get("image_url")
        if image_url and image_url.startswith(("http://", "https://", "data:image/")):
            content.append({"type": "image_url", "image_url": {"url": image_url}})
            image_count += 1
        if image_count >= 3:
            break
    return content if image_count else user_prompt


def _openai_campaign_text(report_type, campaign, metrics, findings, actions, creative_context=None, market_context=None, user=None, organization=None):
    api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY tanımlı değil.")
    try:
        from openai import OpenAI
        from core.services.openai_usage import record_openai_token_usage
    except Exception as exc:
        raise RuntimeError(f"OpenAI istemcisi yüklenemedi: {exc}") from exc

    if report_type == "recommendation":
        instruction = "Sadece uygulanabilir aksiyon planı yaz. Teknik ajan adı, kaynak tablo adı ve API detayı yazma."
    else:
        instruction = "Sadece kampanya performans analizi yaz. Teknik ajan adı, kaynak tablo adı ve API detayı yazma."

    instruction = CAMPAIGN_RECOMMENDATION_SYSTEM_PROMPT if report_type == "recommendation" else CAMPAIGN_ANALYSIS_SYSTEM_PROMPT

    prompt = {
        "campaign": campaign.name,
        "metrics": {
            "roas": metrics.get("roas_label"),
            "ctr": metrics.get("ctr_label"),
            "spend": metrics.get("spend_label"),
            "revenue": metrics.get("revenue_label"),
            "conversions": metrics.get("conversions_label"),
            "cpc": metrics.get("cpc_label"),
            "cpm": metrics.get("cpm_label"),
            "frequency": metrics.get("frequency_label"),
        },
        "findings": findings,
        "actions": actions,
        "creative_context": creative_context or [],
        "market_context": market_context or {},
        "output_rules": [
            "Madde madde yaz.",
            "Her madde bagimsiz cumlelerden olussun.",
            "Paragraf gibi uzun blok yazma.",
            "PDF ciktisinda okunacak kadar net ve profesyonel yaz.",
        ],
    }
    try:
        client = OpenAI(api_key=api_key, timeout=30, max_retries=1)
        prompt["sixteen_agent_ecosystem"] = run_sixteen_agent_orchestration(
            client=client,
            model=getattr(settings, "OPENAI_MODEL", "gpt-4o"),
            task=f"Kampanya {report_type} çalışması için derin analiz ve uygulanabilir strateji üret.",
            context=prompt,
            modalities=["text", "image"] if creative_context else ["text"],
            reference=f"campaign_panel.{report_type}.ecosystem",
            user=user or getattr(campaign, "user", None),
            organization=organization,
            tariff_key=("campaign-panel-analysis" if report_type == "analysis" else "campaign-panel-recommendation"),
        )
        ecosystem = prompt["sixteen_agent_ecosystem"]
        agents = ecosystem.get("agents") or []
        if report_type == "recommendation":
            lines = [f"- {row.get('name')}: {row.get('recommendation')}" for row in agents if row.get("recommendation")]
            heading = "Öncelikli uygulanabilir öneriler"
        else:
            lines = [f"- {row.get('name')}: {row.get('finding')}" for row in agents if row.get("finding")]
            heading = "Kanıta dayalı kampanya analizi"
        return heading + "\n" + "\n".join(lines)
    except Exception as exc:
        raise RuntimeError(f"Gerçek kampanya AI raporu tamamlanamadı: {exc}") from exc


def build_platform_account_payload(user, platform_code="", accounts_queryset=None):
    platforms = Platform.objects.filter(is_active=True).order_by("name")
    data = []
    for platform in platforms:
        if platform_code and getattr(platform, "code", "") != platform_code:
            continue
        accounts = (
            accounts_queryset.filter(platform=platform, is_active=True)
            if accounts_queryset is not None
            else PlatformAccount.objects.filter(user=user, platform=platform, is_active=True)
        ).select_related("platform", "connection")
        account_items = []
        for account in accounts:
            campaigns = Campaign.objects.filter(platform_account=account)
            account_items.append({
                "id": account.id,
                "account_id": account.account_id,
                "account_name": account.account_name or account.account_id,
                "platform": getattr(platform, "code", platform.name),
                "platform_name": platform.name,
                "is_active": account.is_active,
                "last_sync": account.last_sync.isoformat() if account.last_sync else None,
                "campaign_count": campaigns.count(),
                "ad_group_count": AdGroup.objects.filter(campaign__platform_account=account).count(),
                "ad_count": Ad.objects.filter(platform_account=account, source_type="OWN").count(),
                "connection_status": account.connection.status if account.connection else "missing",
            })
        data.append({
            "id": platform.id,
            "code": getattr(platform, "code", platform.name),
            "name": platform.name,
            "accounts": account_items,
            "account_count": len(account_items),
        })
    return data


def build_campaign_list(user, account, start_date=None, end_date=None):
    campaigns = (
        Campaign.objects
        .filter(platform_account=account)
        .select_related("platform_account", "platform_account__platform")
        .prefetch_related("ad_groups", "ads")
        .order_by("-updated_at", "-created_at")
    )
    return [campaign_card_payload(campaign, start_date, end_date) for campaign in campaigns]


def ad_group_payload(ad_group, start_date=None, end_date=None):
    currency = getattr(getattr(ad_group, "campaign", None), "currency", "TRY") or "TRY"
    metrics = metric_qs_by_date(ad_group.metric_history.all(), start_date, end_date)
    summary = aggregate_metrics(metrics)
    ads = ad_group.ads.filter(source_type="OWN").select_related("creative").order_by("-updated_at", "-created_at")
    return {
        "id": ad_group.id,
        "name": ad_group.name,
        "status": ad_group.status,
        "status_label": status_label(ad_group.status),
        "optimization_goal": ad_group.optimization_goal or "-",
        "billing_event": ad_group.billing_event or "-",
        "daily_budget_label": fmt_money(ad_group.daily_budget, currency),
        "lifetime_budget_label": fmt_money(ad_group.lifetime_budget, currency),
        "ad_count": ads.count(),
        "creative_count": ads.exclude(creative__isnull=True).values("creative_id").distinct().count(),
        "metrics": metric_payload(summary, currency),
        "ads": [ad_payload(ad, start_date, end_date, currency) for ad in ads],
    }


def ad_payload(ad, start_date=None, end_date=None, currency="TRY"):
    metrics = metric_qs_by_date(ad.metric_history.all(), start_date, end_date)
    summary = aggregate_metrics(metrics)
    creative = getattr(ad, "creative", None)
    return {
        "id": ad.id,
        "name": ad.name or ad.headline or f"Reklam #{ad.id}",
        "status": ad.status,
        "status_label": status_label(ad.status),
        "format": ad.ad_format or (creative.creative_type if creative else "Reklam"),
        "objective": ad.objective or "-",
        "headline": ad.headline or "",
        "primary_text": ad.primary_text or "",
        "description": ad.description or "",
        "call_to_action": ad.call_to_action or "",
        "landing_url": ad.landing_url or "",
        "media_url": media_url_for_ad(ad),
        "video_url": ad.preview_video_url or (creative.video_url if creative else ""),
        "creative": creative_payload(creative, start_date, end_date, currency) if creative else None,
        "metrics": metric_payload(summary, currency),
    }


def creative_payload(creative, start_date=None, end_date=None, currency="TRY"):
    metrics = metric_qs_by_date(creative.metric_history.all(), start_date, end_date)
    summary = aggregate_metrics(metrics)
    return {
        "id": creative.id,
        "name": creative.name or creative.title or f"Kreatif #{creative.id}",
        "type": creative.creative_type,
        "title": creative.title or "",
        "body_text": creative.body_text or "",
        "description": creative.description or "",
        "call_to_action": creative.call_to_action or "",
        "image_url": creative.image_url or creative.thumbnail_url or "",
        "video_url": creative.video_url or "",
        "landing_url": creative.landing_url or "",
        "metrics": metric_payload(summary, currency),
    }


def build_campaign_detail(user, campaign, start_date=None, end_date=None):
    campaign_summary = campaign_card_payload(campaign, start_date, end_date)
    ad_groups = campaign.ad_groups.all().order_by("-updated_at", "-created_at")
    campaign_summary["ad_groups"] = [ad_group_payload(group, start_date, end_date) for group in ad_groups]
    campaign_summary["history"] = [
        metric_payload(aggregate_metrics(CampaignMetricHistory.objects.filter(id=row.id)), campaign.currency or "TRY") | {"date": row.date.strftime("%d.%m.%Y")}
        for row in metric_qs_by_date(campaign.metric_history.all(), start_date, end_date).order_by("-date")[:90]
    ]
    campaign_summary["info_rows"] = [
        {"label": "Platform", "value": campaign_summary["platform"]},
        {"label": "Hesap", "value": campaign_summary["account_name"]},
        {"label": "Platform Kampanya ID", "value": campaign_summary["platform_campaign_id"]},
        {"label": "Durum", "value": campaign_summary["status_label"]},
        {"label": "Hedef", "value": campaign_summary["objective_label"]},
        {"label": "Para Birimi", "value": campaign_summary["currency"]},
        {"label": "Günlük Bütçe", "value": campaign_summary["daily_budget_label"]},
        {"label": "Yaşam Boyu Bütçe", "value": campaign_summary["lifetime_budget_label"]},
        {"label": "Başlangıç", "value": campaign_summary["start_time"]},
        {"label": "Bitiş", "value": campaign_summary["end_time"]},
        {"label": "Son Senkronizasyon", "value": campaign_summary["last_synced_at"]},
        {"label": "Son Güncelleme", "value": campaign_summary["updated_at"]},
    ]
    campaign_summary["top_ads"] = sorted(
        [
            {
                "id": ad["id"],
                "name": ad["name"],
                "status_label": ad["status_label"],
                "roas": ad["metrics"]["roas"],
                "roas_label": ad["metrics"]["roas_label"],
                "spend_label": ad["metrics"]["spend_label"],
                "revenue_label": ad["metrics"]["revenue_label"],
                "ctr_label": ad["metrics"]["ctr_label"],
                "headline": ad.get("headline", ""),
                "primary_text": ad.get("primary_text", ""),
                "description": ad.get("description", ""),
                "call_to_action": ad.get("call_to_action", ""),
                "landing_url": ad.get("landing_url", ""),
                "media_url": ad.get("media_url", ""),
                "video_url": ad.get("video_url", ""),
            }
            for group in campaign_summary["ad_groups"]
            for ad in group.get("ads", [])
        ],
        key=lambda item: item["roas"],
        reverse=True,
    )[:8]
    last_analysis = CampaignOctoAnalysis.objects.filter(user=user, campaign=campaign).order_by("-created_at").first()
    last_recommendation = CampaignOctoRecommendation.objects.filter(user=user, campaign=campaign).order_by("-created_at").first()
    campaign_summary["octo_records"] = {
        "analysis": {
            "score": float(last_analysis.octo_score) if last_analysis else 0,
            "status": last_analysis.success_label if last_analysis else "-",
            "risk": last_analysis.risk_label or last_analysis.risk_level if last_analysis else "-",
            "summary": last_analysis.analysis_text if last_analysis else "",
            "recommendation": last_analysis.recommendation_text if last_analysis else "",
            "created_at": _date_label(last_analysis.created_at) if last_analysis else "-",
        },
        "recommendation": {
            "summary": last_recommendation.summary if last_recommendation else "",
            "recommendations": last_recommendation.recommendations if last_recommendation else "",
            "expected_impact": last_recommendation.expected_impact if last_recommendation else "",
            "priority": last_recommendation.get_priority_display() if last_recommendation else "-",
            "created_at": _date_label(last_recommendation.created_at) if last_recommendation else "-",
        },
    }
    return campaign_summary


def _metric_history_for_ai(campaign, start_date=None, end_date=None):
    return [
        {
            "date": row.date.isoformat(),
            "impressions": row.impressions,
            "clicks": row.clicks,
            "ctr": float(row.ctr or 0),
            "engagement_rate": float(row.engagement_rate or 0),
            "cost_per_click": float(row.cpc or 0),
            "likes": row.likes,
            "comments": row.comments,
            "shares": row.shares,
            "spend": float(row.spend or 0),
            "conversion_value": float(row.conversion_value or 0),
            "conversions": float(row.conversions or 0),
            "roas": float(row.roas or 0),
        }
        for row in metric_qs_by_date(campaign.metric_history.all(), start_date, end_date).order_by("date")
    ]


def _score_label(score):
    score = float(score or 0)
    if score >= 80:
        return "Güçlü"
    if score >= 60:
        return "İyi"
    if score >= 40:
        return "İzlenmeli"
    return "Riskli"


def build_campaign_ai_report(user, campaign, report_type="analysis", start_date=None, end_date=None, persist=False, allow_openai=True, organization=None):
    detail = build_campaign_detail(user, campaign, start_date, end_date)
    metrics = detail.get("metrics", {})
    history = _metric_history_for_ai(campaign, start_date, end_date)
    rule_events = detail.get("rule_events") or build_campaign_rule_events(campaign, metrics)

    try:
        from core.ai_agents.performance_analyzer import PerformanceAnalyzer
        analyzer = PerformanceAnalyzer(user=getattr(campaign, "user", None))
        analyzer.use_openai = False
        performance = analyzer.analyze_campaign_performance(
            {
                "campaign_name": campaign.name,
                "ad_type": detail.get("objective_label") or detail.get("objective"),
                "budget": float(safe_decimal(campaign.daily_budget or campaign.lifetime_budget)),
            },
            history,
        )
    except Exception as exc:
        performance = {
            "success": False,
            "performance_score": 0,
            "strengths": [],
            "weaknesses": ["Metrik hacmi ve dönem karşılaştırması sınırlı olduğu için analiz kural tabanlı değerlendirildi."],
            "trends": {"message": "Trend için yeterli net sinyal oluşmadı."},
            "ai_analysis": "",
            "recommendations": [],
        }

    roas = float(metrics.get("roas") or 0)
    ctr = float(metrics.get("ctr") or 0)
    spend = float(metrics.get("spend") or 0)
    conversions = float(metrics.get("conversions") or 0)
    score = float(performance.get("performance_score") or 0)

    budget_agent = {
        "title": "Bütçe Ajanı",
        "status": "İzle",
        "reason": "Bütçe için net sinyal oluşmadı.",
        "confidence": 0.62,
    }
    if roas >= 3 and conversions > 0:
        budget_agent.update({
            "status": "Artır",
            "reason": f"ROAS {metrics.get('roas_label')} ve dönüşüm var; bütçe kontrollü artırılabilir.",
            "confidence": 0.86,
        })
    elif spend > 0 and roas < 1:
        budget_agent.update({
            "status": "Azalt / durdur",
            "reason": f"Harcama {metrics.get('spend_label')} fakat ROAS {metrics.get('roas_label')}; verimsiz harcama riski var.",
            "confidence": 0.82,
        })

    creative_agent = {
        "title": "Kreatif Ajanı",
        "status": "Test öner",
        "reason": "En iyi reklam/kreatif varyasyonlarını yeni mesaj ve CTA testi için kullan.",
        "signals": [
            f"Kreatif sayısı: {detail.get('creative_count', 0)}",
            f"En iyi reklam: {(detail.get('top_ads') or [{'name': '-'}])[0].get('name', '-')}",
        ],
    }
    market_agent = {
        "title": "Pazar ve Rekabet Ajanı",
        "status": "Benchmark",
        "reason": "Kampanya metriklerini rakip hareketleri ve platform ortalamalarıyla karşılaştır.",
        "signals": [
            f"CTR: {metrics.get('ctr_label')}",
            f"CPC: {metrics.get('cpc_label')}",
            f"CPM: {metrics.get('cpm_label')}",
        ],
    }

    strengths = list(performance.get("strengths") or [])
    weaknesses = list(performance.get("weaknesses") or [])
    if roas >= 2:
        strengths.insert(0, f"ROAS {metrics.get('roas_label')}x seviyesi gelir verimliliği için olumlu.")
    if ctr < 1 and metrics.get("impressions", 0):
        weaknesses.insert(0, f"CTR {metrics.get('ctr_label')} seviyesinde; kreatif veya hedefleme yenilenmeli.")
    if spend > 0 and conversions == 0:
        weaknesses.insert(0, "Harcama var fakat dönüşüm görünmüyor; tracking ve teklif kontrolü gerekli.")

    findings = _campaign_metric_findings(metrics, rule_events)
    recommendations = []
    if report_type == "recommendation":
        recommendations.extend(_campaign_action_plan(metrics, rule_events))
        for item in performance.get("recommendations") or []:
            recommendations.append({
                "title": item.get("title", "AI önerisi"),
                "detail": item.get("description", ""),
                "priority": item.get("priority", "medium"),
            })

    recommendations = _dedupe_recommendations(recommendations)
    creative_context = _campaign_creative_context(campaign, detail.get("top_ads", []))
    market_context = _campaign_market_context(campaign, detail.get("top_ads", [])) if report_type == "recommendation" else {"enabled": False, "items": [], "note": "Analiz modu piyasa tavsiyesi uretmez."}
    openai_text = (
        _openai_campaign_text(
            report_type,
            campaign,
            metrics,
            findings,
            recommendations,
            creative_context=creative_context,
            market_context=market_context,
            user=user,
            organization=organization,
        )
        if allow_openai
        else ""
    )
    fallback_summary = (
        "Kampanya metrikleri incelendi. Öne çıkan bulgular:\n- " + "\n- ".join(findings)
        if report_type == "analysis"
        else "Uygulanacak öncelikli aksiyonlar:\n- " + "\n- ".join([f"{x.get('title')}: {x.get('detail')}" for x in recommendations[:6]])
    )

    report = {
        "success": True,
        "type": report_type,
        "title": "Derin Kampanya Analizi" if report_type == "analysis" else "Yorum ve Aksiyon Önerileri",
        "generated_at": _date_label(timezone.now()),
        "campaign": {
            "id": campaign.id,
            "name": campaign.name,
            "platform": detail.get("platform"),
            "account": detail.get("account_name"),
            "status": detail.get("status_label"),
            "objective": detail.get("objective_label"),
        },
        "score": round(score, 1),
        "score_label": _score_label(score),
        "metrics": metrics,
        "summary": openai_text or fallback_summary,
        "summary_items": _summary_lines(openai_text or fallback_summary, 12),
        "findings": findings,
        "rule_events": rule_events,
        "trend": performance.get("trends") or {},
        "strengths": strengths[:7],
        "weaknesses": weaknesses[:7],
        "recommendations": recommendations[:12],
        "agents": [
            {"name": "Performans Ajanı", "status": _score_label(score), "reason": performance.get("trends", {}).get("message", "Performans skoru üretildi."), "confidence": min(0.95, max(0.45, score / 100))},
            budget_agent,
            creative_agent,
            market_agent,
        ],
        "top_ads": detail.get("top_ads", []),
        "creative_context": creative_context,
        "market_context": market_context,
        "agent_ecosystem": build_campaign_agent_ecosystem(
            metrics,
            detail=detail,
            rule_events=rule_events,
            recommendations=recommendations,
        ),
        "octo_records": detail.get("octo_records", {}),
        "data_source": "Campaign, CampaignMetricHistory, AdGroup, Ad, Creative ve ilişkili metric history tabloları",
    }
    if persist:
        report.update(_persist_campaign_ai_report(user, campaign, report))
    return report


def build_campaign_ai_pdf_response(report):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except Exception:
        response = HttpResponse("PDF üretimi için reportlab paketi gerekli.", content_type="text/plain; charset=utf-8")
        response.status_code = 500
        return response

    def register_pdf_fonts():
        regular_candidates = [
            os.path.join(str(getattr(settings, "BASE_DIR", "")), "static", "fonts", "DejaVuSans.ttf"),
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        ]
        bold_candidates = [
            os.path.join(str(getattr(settings, "BASE_DIR", "")), "static", "fonts", "DejaVuSans-Bold.ttf"),
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        ]
        regular = next((path for path in regular_candidates if path and os.path.exists(path)), None)
        bold = next((path for path in bold_candidates if path and os.path.exists(path)), None)
        try:
            if regular:
                pdfmetrics.registerFont(TTFont("CPUnicode", regular))
            if bold:
                pdfmetrics.registerFont(TTFont("CPUnicode-Bold", bold))
        except Exception:
            return "Helvetica", "Helvetica-Bold"
        return ("CPUnicode" if regular else "Helvetica", "CPUnicode-Bold" if bold else "Helvetica-Bold")

    buffer = BytesIO()
    filename = f"octo-kampanya-{report['campaign']['id']}-{report['type']}.pdf"
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.4 * cm, leftMargin=1.4 * cm, topMargin=1.2 * cm, bottomMargin=1.2 * cm)
    font_regular, font_bold = register_pdf_fonts()
    styles = getSampleStyleSheet()
    title = ParagraphStyle("OctoTitle", parent=styles["Title"], fontName=font_bold, fontSize=18, textColor=colors.HexColor("#111827"), spaceAfter=10)
    h = ParagraphStyle("OctoH", parent=styles["Heading2"], fontName=font_bold, fontSize=12, textColor=colors.HexColor("#4f46e5"), spaceBefore=10, spaceAfter=6)
    p = ParagraphStyle("OctoP", parent=styles["BodyText"], fontName=font_regular, fontSize=9.5, leading=13)
    def pdf_text(value):
        return xml_escape(str(value or ""))

    story = [
        Paragraph(pdf_text(f"Octo AI - {report['title']}"), title),
        Paragraph(pdf_text(f"{report['campaign']['name']} | {report['campaign']['platform']} | {report['generated_at']}"), p),
        Spacer(1, 8),
    ]
    metrics = report.get("metrics", {})
    table = Table([
        ["Skor", "ROAS", "CTR", "Harcama", "Gelir", "Dönüşüm"],
        [f"{report.get('score')} ({report.get('score_label')})", metrics.get("roas_label"), metrics.get("ctr_label"), metrics.get("spend_label"), metrics.get("revenue_label"), metrics.get("conversions_label")],
    ], colWidths=[2.6 * cm, 2.2 * cm, 2.2 * cm, 3 * cm, 3 * cm, 2.6 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ("FONTNAME", (0, 0), (-1, 0), font_bold),
        ("FONTNAME", (0, 1), (-1, -1), font_regular),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story += [table, Paragraph("Yorum ve Öncelikli Aksiyonlar", h), Paragraph(pdf_text(report.get("summary", "")).replace("\n", "<br/>"), p)]
    if report.get("findings"):
        story.append(Paragraph("Bulgular", h))
        for item in report["findings"]:
            story.append(Paragraph(pdf_text(f"- {item}"), p))
    if report.get("rule_events"):
        story.append(Paragraph("Olaylar ve Çözümler", h))
        for event in report["rule_events"]:
            story.append(Paragraph(f"<b>{pdf_text(event.get('event'))}</b><br/>{pdf_text(event.get('description'))}<br/><b>Çözüm:</b> {pdf_text(event.get('solution'))}", p))
            story.append(Spacer(1, 4))
    if report.get("recommendations"):
        story.append(Paragraph("Uygulanacaklar", h))
        for item in report["recommendations"]:
            story.append(Paragraph(f"<b>{pdf_text(item.get('title'))}</b>: {pdf_text(item.get('detail'))} ({pdf_text(item.get('priority'))})", p))
    if report.get("top_ads"):
        story.append(Paragraph("En Verimli Reklamlar", h))
        for ad in report["top_ads"]:
            story.append(Paragraph(pdf_text(f"- {ad.get('name')} | ROAS {ad.get('roas_label')} | CTR {ad.get('ctr_label')} | {ad.get('spend_label')}"), p))
    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
