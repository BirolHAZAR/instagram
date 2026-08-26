from datetime import timedelta
import csv
import math
from decimal import Decimal

from django.http import HttpResponse
from django.db.models import Avg, Count, Max, Sum, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.models import (
    Ad,
    AdGroup,
    AdMetricHistory,
    CreativeMetricHistory,
    CampaignMetricHistory,
    AIRecommendationHistory,
    Campaign,
    Creative,
    OctoScoreHistory,
    PlatformAccount,
    PlatformConnection,
    PlatformSyncJob,
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
    from core.models import CampaignOctoRecommendation, CampaignOctoAnalysis
except Exception:
    CampaignOctoRecommendation = None
    CampaignOctoAnalysis = None

try:
    from core.models import ControlTowerSnapshot
except Exception:
    ControlTowerSnapshot = None

try:
    from core.models import ControlTowerAIAnalysis
except Exception:
    ControlTowerAIAnalysis = None

try:
    from core.services.control_tower_snapshot import build_decision_center_from_context, build_lightweight_snapshot_for_user, save_snapshot_from_context
except Exception:
    build_decision_center_from_context = None
    build_lightweight_snapshot_for_user = None
    save_snapshot_from_context = None

from core.services.performance_metrics import aggregate_metric_queryset


def _num(value):
    try:
        return float(value or 0)
    except Exception:
        return 0

def _pct_change(current, previous):
    current = _num(current)
    previous = _num(previous)

    # Önceki dönem yoksa veya çok küçükse yüzde değişim yanıltıcı olur.
    # Bu durumda 0 gösterilir; böylece +20920% gibi gerçek dışı görünen sapmalar engellenir.
    if previous <= 0.01:
        return 0

    change = ((current - previous) / previous) * 100

    # Görsel dashboard için aşırı uç değerleri sınırla.
    if change > 999:
        return 999
    if change < -999:
        return -999

    return round(change, 1)

def _format_dashboard_number(value, prefix="", suffix="", decimals=1, force_decimal=False):
    try:
        number = float(value or 0)
    except Exception:
        number = 0.0
    decimals = max(0, int(decimals or 0))
    rounded = round(number, decimals)
    has_decimal = force_decimal or (decimals > 0 and abs(rounded - int(rounded)) > 1e-9)
    if has_decimal:
        raw = f"{rounded:,.{decimals}f}"
        if not force_decimal:
            raw = raw.rstrip("0").rstrip(".")
    else:
        raw = f"{int(round(rounded)):,}"
    raw = raw.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{prefix}{raw}{suffix}"

def _fmt_money(value):
    return _format_dashboard_number(value, suffix=" TL", decimals=1)

def _fmt_percent(value):
    return _format_dashboard_number(value, suffix="%", decimals=1)

def _fmt_ratio(value):
    return _format_dashboard_number(value, decimals=1, force_decimal=True)

def _trend_signal(delta, higher_is_better=True):
    delta = _num(delta)
    if abs(delta) < 0.1:
        return {"state": "neutral", "icon": "▬", "label": "Durağan"}
    good = delta > 0 if higher_is_better else delta < 0
    return {"state": "good" if good else "bad", "icon": "▲" if delta > 0 else "▼", "label": "Yükseldi" if delta > 0 else "Düştü"}

def _campaign_expected_gain(health):
    """Kampanya sağlık kartı için kaba finansal aksiyon etkisi.
    Canlı API çağırmaz; mevcut DB metriklerinden hesaplanır.
    """
    revenue = _num(health.get("revenue"))
    spend = _num(health.get("spend"))
    score = _num(health.get("score"))
    roas = _num(health.get("roas"))
    if score >= 70 and roas >= 1.5:
        return round(revenue * 0.08, 2)
    if score < 55 and spend > 0:
        return round(spend * 0.16, 2)
    return 0

def _campaign_ai_summary(health):
    level = str(health.get("level", "")).lower()
    if level == "bad":
        return "Öncelik: ROAS/CVR düşüşü ve harcama verimliliği kontrol edilmeli."
    if level in {"mid", "warn"}:
        return "İzleme: Trend zayıflarsa kreatif ve bütçe aksiyonu hazırlanmalı."
    return "Fırsat: Sağlıklı kampanya, kontrollü ölçekleme adayı."

def _competitor_pressure_score(total_ads, share):
    """Rakip baskısını 0-100 skorlar.
    Yeni reklam sayısı ve share of voice birlikte değerlendirilir.
    """
    total_ads = _num(total_ads)
    share = _num(share)
    score = min(100, int(round((min(total_ads, 25) / 25 * 55) + (min(share, 100) * 0.45))))
    if score >= 70:
        return score, "bad", "Yüksek Baskı"
    if score >= 40:
        return score, "neutral", "İzlenmeli"
    return score, "good", "Düşük Baskı"

def _build_competitor_intelligence(*, competitor_rows, total_competitor, current_count, previous_count, selected_days):
    """Control Tower için premium rakip istihbarat katmanı.

    Canlı scrape/API çağırmaz. Mevcut DB'deki COMPETITOR reklamları ve
    snapshot dönem sinyallerinden baskı, momentum, forecast ve aksiyon üretir.
    """
    rows = competitor_rows or []
    total_competitor = int(_num(total_competitor))
    current_count = int(_num(current_count))
    previous_count = int(_num(previous_count))
    growth_rate = _pct_change(current_count, previous_count)
    top = rows[0] if rows else {}
    top_name = top.get("name") or "Rakip verisi bekleniyor"
    top_share = _num(top.get("share"))
    avg_pressure = int(round(sum(_num(r.get("pressure_score")) for r in rows) / len(rows))) if rows else 0

    # Baskı skoru sadece reklam sayısı değil; momentum + paylaşım sesi + lider rakip etkisi.
    activity_score = min(100, int(round((min(current_count, 60) / 60) * 40)))
    momentum_score = min(30, max(0, int(round(growth_rate / 3)))) if growth_rate > 0 else 0
    share_score = min(30, int(round(top_share * 0.30)))
    pressure_score = max(avg_pressure, min(100, activity_score + momentum_score + share_score))

    if pressure_score >= 72:
        state, threat_label, threat_icon = "bad", "Yüksek Tehdit", "🔴"
    elif pressure_score >= 45:
        state, threat_label, threat_icon = "neutral", "Orta Baskı", "🟠"
    else:
        state, threat_label, threat_icon = "good", "Düşük Baskı", "🟢"

    cpm_min = 8 if pressure_score >= 72 else 4 if pressure_score >= 45 else 0
    cpm_max = 12 if pressure_score >= 72 else 7 if pressure_score >= 45 else 3
    ctr_risk = 9 if pressure_score >= 72 else 5 if pressure_score >= 45 else 2
    opportunity_ctr = 12 if pressure_score >= 45 else 6

    if not rows:
        forecast = "Rakip reklam verisi henüz yeterli değil. Octo bu alanı gözlem modunda tutuyor; veri arttıkça baskı, momentum ve fırsat tahmini üretilecek."
        opportunity = "İlk hedef, rakip reklam verisini düzenli toplamak ve en az 7 günlük benchmark havuzu oluşturmaktır."
        recommendation = "Rakip hesap bağlantıları ve veri toplama görevleri doğrulanmalı. Gerçek rakip reklam sağlayıcısı bağlanmadan rakip reklam geçmişi üretilmez."
    else:
        forecast = (
            f"{selected_days} günlük pencerede {current_count} rakip reklam sinyali okundu. "
            f"En güçlü baskı {top_name} tarafında. Momentum {growth_rate:+.1f}% seviyesinde. "
            f"Bu eğilim devam ederse CPM tarafında %{cpm_min}-{cpm_max} arası baskı, CTR tarafında yaklaşık %{ctr_risk} kalite riski oluşabilir."
        )
        opportunity = (
            f"Rakip yoğunluğu artarken kreatif çeşitliliği düşük kalan alanlarda fırsat oluşur. "
            f"UGC/video varyasyonları ve remarketing mesajlarıyla yaklaşık +%{opportunity_ctr} CTR potansiyeli hedeflenebilir."
        )
        recommendation = (
            f"Öncelik: {top_name} kreatifleri izlenmeli, aynı gün içinde karşı kreatif varyasyonu hazırlanmalı. "
            "İkinci öncelik: remarketing bütçesi korunmalı; üçüncü öncelik: CPM artışına karşı kreatif tazeleme planı açılmalı."
        )

    heatmap = []
    for r in rows[:5]:
        score = int(_num(r.get("pressure_score")))
        heatmap.append({
            "name": r.get("name"),
            "activity": int(_num(r.get("new_ads"))),
            "momentum": r.get("growth_label") or ("▲" if int(_num(r.get("new_ads"))) else "▬"),
            "share": r.get("share_label"),
            "threat_score": score,
            "state": r.get("pressure_state") or ("bad" if score >= 70 else "neutral" if score >= 40 else "good"),
        })

    return {
        "pressure_score": pressure_score,
        "state": state,
        "threat_label": threat_label,
        "threat_icon": threat_icon,
        "new_ads": current_count,
        "new_ads_label": _format_dashboard_number(current_count, decimals=0),
        "growth_rate": growth_rate,
        "growth_label": _fmt_percent(abs(growth_rate)),
        "growth_icon": "▲" if growth_rate > 0 else "▼" if growth_rate < 0 else "▬",
        "growth_state": "bad" if growth_rate > 0 else "good" if growth_rate < 0 else "neutral",
        "share_of_voice": top_share,
        "share_of_voice_label": _fmt_percent(top_share),
        "top_threat": top_name,
        "cpm_forecast_label": f"%{cpm_min}-{cpm_max}" if cpm_max else "%0-3",
        "ctr_risk_label": f"%{ctr_risk}",
        "forecast_tr": forecast,
        "opportunity_tr": opportunity,
        "recommendation_tr": recommendation,
        "heatmap": heatmap,
    }

def _safe_aware_datetime(value):
    """DB'den gelen naive/aware datetime değerlerini güvenli karşılaştırılabilir hale getirir."""
    if not value:
        return None
    try:
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value
    except Exception:
        return None

def _score_from_roas_ctr(roas, ctr):
    score = 50
    score += min(_num(roas) * 8, 30)
    score += min(_num(ctr) * 4, 20)
    return int(max(0, min(100, score)))

def _model_has_field(model, field_name):
    try:
        return any(field.name == field_name for field in model._meta.get_fields())
    except Exception:
        return False

def _campaign_health_score_engine(*, campaign, metrics, prev_metrics, alert_count=0):
    """Profesyonel kampanya sağlık skoru.

    Skor yalnızca reklam veritabanındaki kampanya metriklerinden üretilir.
    ROAS + CTR basitliği yerine maliyet, dönüşüm, trend, veri güveni, durum
    ve uyarı riski birlikte değerlendirilir.
    """
    impressions = _num(metrics.get("total_impressions"))
    clicks = _num(metrics.get("total_clicks"))
    spend = _num(metrics.get("total_spend"))
    conversions = _num(metrics.get("total_conversions"))
    revenue = _num(metrics.get("total_revenue"))

    roas = _num(metrics.get("avg_roas"))
    ctr = _num(metrics.get("avg_ctr"))
    cpc = _num(metrics.get("avg_cpc"))
    cpm = _num(metrics.get("avg_cpm"))
    conversion_rate = (conversions / clicks * 100) if clicks else 0

    prev_roas = _num(prev_metrics.get("avg_roas"))
    prev_ctr = _num(prev_metrics.get("avg_ctr"))
    prev_clicks = _num(prev_metrics.get("total_clicks"))
    prev_conversions = _num(prev_metrics.get("total_conversions"))
    prev_conversion_rate = (prev_conversions / prev_clicks * 100) if prev_clicks else 0
    prev_spend = _num(prev_metrics.get("total_spend"))

    roas_score = _score(roas, 4)
    ctr_score = _score(ctr, 3)
    conversion_score = _score(conversion_rate, 5)
    cpc_score = _inverse_score(cpc, 3, 25) if cpc else 50
    cpm_score = _inverse_score(cpm, 80, 350) if cpm else 50

    # Harcama verimliliği: Para harcanıyor ama dönüşüm/gelir üretmiyorsa risk artar.
    if spend > 0 and conversions <= 0 and revenue <= 0:
        spend_efficiency_score = 20
    elif spend > 0:
        spend_efficiency_score = int(round((roas_score * 0.70) + (cpc_score * 0.30)))
    else:
        spend_efficiency_score = 50

    roas_delta = _pct_change(roas, prev_roas)
    ctr_delta = _pct_change(ctr, prev_ctr)
    conversion_delta = _pct_change(conversion_rate, prev_conversion_rate)
    spend_delta = _pct_change(spend, prev_spend)

    trend_score = 50
    trend_score += max(-18, min(18, roas_delta / 4))
    trend_score += max(-12, min(12, ctr_delta / 5))
    trend_score += max(-12, min(12, conversion_delta / 5))
    if spend_delta > 20 and (roas_delta < 0 or conversion_delta < 0):
        trend_score -= 14
    trend_score = int(max(0, min(100, round(trend_score))))

    status_raw = str(getattr(campaign, "status", "") or "").upper()
    status_penalty = 0
    if status_raw and status_raw not in {"ACTIVE", "ENABLED"}:
        status_penalty = 8

    data_signals = sum([impressions > 0, clicks > 0, spend > 0, conversions > 0, revenue > 0])
    data_confidence = int((data_signals / 5) * 100)
    if impressions >= 1000 and clicks >= 20:
        data_confidence = max(data_confidence, 80)
    elif impressions >= 300 or clicks >= 10:
        data_confidence = max(data_confidence, 60)

    alert_penalty = min(15, int(_num(alert_count)) * 5)

    weighted = (
        roas_score * 0.25 +
        ctr_score * 0.15 +
        conversion_score * 0.15 +
        cpc_score * 0.10 +
        spend_efficiency_score * 0.10 +
        cpm_score * 0.05 +
        trend_score * 0.15 +
        data_confidence * 0.05
    )

    # Veri zayıfsa skoru aşırı iyi/kötü göstermeyip temkinli alana çeker.
    if data_confidence < 60:
        weighted = (weighted * 0.72) + (50 * 0.28)

    score = int(max(0, min(100, round(weighted - alert_penalty - status_penalty))))

    if score >= 85:
        level = "good"
        label = "Mükemmel"
    elif score >= 70:
        level = "good"
        label = "Sağlıklı"
    elif score >= 55:
        level = "mid"
        label = "İzlenmeli"
    elif score >= 40:
        level = "mid"
        label = "Riskli"
    else:
        level = "bad"
        label = "Kritik"

    if alert_penalty:
        reason = "Kritik uyarı skoru aşağı çekiyor"
    elif spend > 0 and conversions <= 0:
        reason = "Harcama var, dönüşüm zayıf"
    elif roas_delta < -10 or conversion_delta < -10:
        reason = "Son dönem trendi zayıflıyor"
    elif roas >= 2 and ctr >= 1 and conversion_rate > 0:
        reason = "Performans ve dönüşüm dengesi iyi"
    elif data_confidence < 60:
        reason = "Veri güveni düşük, izlenmeli"
    else:
        reason = "Optimizasyon potansiyeli var"

    detail = (
        f"ROAS skoru {roas_score}, CTR skoru {ctr_score}, dönüşüm skoru {conversion_score}, "
        f"CPC skoru {cpc_score}, trend skoru {trend_score}, veri güveni {data_confidence}. "
        f"Uyarı cezası {alert_penalty}, durum cezası {status_penalty}."
    )

    cpa = (spend / conversions) if conversions else 0

    return {
        "score": score,
        "level": level,
        "label": label,
        "reason": reason,
        "detail": detail,
        "delta": int(round(roas_delta)),
        "delta_abs": abs(int(round(roas_delta))),
        "roas": roas,
        "ctr": ctr,
        "conversion_rate": conversion_rate,
        "cpc": cpc,
        "cpa": cpa,
        "cpm": cpm,
        "spend": spend,
        "revenue": revenue,
        "conversions": conversions,
        "impressions": impressions,
        "clicks": clicks,
        "data_confidence": data_confidence,
    }

def _octo_ai_score_engine(
    *,
    roas,
    ctr,
    cpc,
    conversion_rate,
    spend_delta,
    creative_score,
    competitor_ad_count,
    critical_alert_count,
    pending_ai_tasks,
    high_ai_tasks,
):
    """
    Octo AI Skoru V2.1

    GA4 kullanmaz. Skor yalnızca reklam veritabanı metriklerinden ve
    Control Tower içindeki gerçek aksiyon/uyarı sinyallerinden oluşur.

    Önemli davranış:
    - Veri yoksa 0 skor döner.
    - Veri varsa skor alt limite yapışmaz; periyoda göre doğal değişir.
    - Uyarı ve görevler skoru tamamen sıfıra çakmaz, sadece risk etkisi verir.
    """

    roas_v = _num(roas)
    ctr_v = _num(ctr)
    cpc_v = _num(cpc)
    conversion_v = _num(conversion_rate)
    creative_v = _num(creative_score)
    spend_delta_v = _num(spend_delta)

    metric_signal = any([
        roas_v > 0,
        ctr_v > 0,
        cpc_v > 0,
        conversion_v > 0,
        creative_v > 0,
    ])

    if not metric_signal:
        return {
            "score": 0,
            "label": "Hazır",
            "components": {
                "roas": 0,
                "ctr": 0,
                "conversion": 0,
                "cpc": 0,
                "budget": 0,
                "creative": 0,
                "competitor": 0,
                "alert_penalty": 0,
                "task_penalty": 0,
                "high_task_penalty": 0,
                "data_confidence": 0,
            }
        }

    # Reklam performansı için okunabilir hedefler.
    # Bunlar skor hedefidir; para birimi veya GA4 içermez.
    roas_score = _score(roas_v, 4)                         # ROAS 4 = 100
    ctr_score = _score(ctr_v, 3)                           # CTR %3 = 100
    conversion_score = _score(conversion_v, 5)             # Dönüşüm %5 = 100
    cpc_score = _inverse_score(cpc_v, 3, 25) if cpc_v else 50

    # Harcama değişimi tek başına kötü/iyi değildir. Aşırı oynaklık risk kabul edilir.
    budget_score = _inverse_score(abs(spend_delta_v), 15, 80)

    creative_health = int(max(0, min(100, creative_v))) if creative_v else _score_from_roas_ctr(roas_v, ctr_v)

    # Rakip reklam sayısı tek başına performans bozukluğu değildir; etkisi yumuşak tutulur.
    competitor_score = (
        _inverse_score(competitor_ad_count, 15, 100)
        if competitor_ad_count
        else 100
    )

    # Eksik metrik varsa skor yine çalışır ama güven düşük olur.
    signal_count = sum([
        roas_v > 0,
        ctr_v > 0,
        cpc_v > 0,
        conversion_v > 0,
        creative_v > 0,
    ])
    data_confidence = int((signal_count / 5) * 100)

    # Cezalar yumuşatıldı. Aksi halde skor 25 civarına yapışıyordu.
    alert_penalty = min(16, _num(critical_alert_count) * 4)
    task_penalty = min(6, _num(pending_ai_tasks) * 0.35)
    high_task_penalty = min(8, _num(high_ai_tasks) * 2.5)

    weighted_score = (
        roas_score * 0.26 +
        ctr_score * 0.17 +
        conversion_score * 0.15 +
        cpc_score * 0.10 +
        budget_score * 0.08 +
        creative_health * 0.16 +
        competitor_score * 0.08
    )

    # Veri güveni düşükse skoru sıfıra değil, temkinli aralığa çeker.
    if data_confidence < 60:
        weighted_score = (weighted_score * 0.75) + (50 * 0.25)

    final_score = weighted_score - alert_penalty - task_penalty - high_task_penalty
    final_score = int(max(0, min(100, round(final_score))))

    if final_score >= 90:
        label = "Mükemmel"
    elif final_score >= 80:
        label = "Çok Güçlü"
    elif final_score >= 70:
        label = "Sağlıklı"
    elif final_score >= 55:
        label = "Dikkat Gerekli"
    elif final_score >= 40:
        label = "Riskli"
    else:
        label = "Kritik"

    return {
        "score": final_score,
        "label": label,
        "components": {
            "roas": roas_score,
            "ctr": ctr_score,
            "conversion": conversion_score,
            "cpc": cpc_score,
            "budget": budget_score,
            "creative": creative_health,
            "competitor": competitor_score,
            "alert_penalty": alert_penalty,
            "task_penalty": task_penalty,
            "high_task_penalty": high_task_penalty,
            "data_confidence": data_confidence,
        }
    }

def _level(score):
    if score >= 75:
        return "good"
    if score >= 50:
        return "mid"
    return "bad"

def _label(delta):
    if delta > 0:
        return f"↑ {abs(delta)}%"
    if delta < 0:
        return f"↓ {abs(delta)}%"
    return "0%"

def _delta_class(delta, higher_is_better=True):
    """Template için canlı renk sınıfı üretir.
    good = yeşil, bad = kırmızı, neutral = gri.
    CPC gibi düşük olması iyi olan metriklerde higher_is_better=False kullanılır.
    """
    delta = _num(delta)
    if abs(delta) < 0.05:
        return "neutral"
    is_good = delta > 0 if higher_is_better else delta < 0
    return "good" if is_good else "bad"

def _delta_text(delta):
    delta = _num(delta)
    if delta > 0:
        return f"↑ {abs(delta)}%"
    if delta < 0:
        return f"↓ {abs(delta)}%"
    return "→ 0%"

def _score_level_class(score):
    """Octo skoru değer seviyesine göre renk sınıfı.
    high/good = yeşil, warn = sarı/turuncu, risk = kırmızı.
    """
    score = _num(score)
    if score >= 70:
        return "good"
    if score >= 50:
        return "warn"
    return "bad"

def _safe_div(num, den):
    return round(_num(num) / _num(den), 2) if _num(den) else 0

def _aggregate_performance(metric_qs):
    """Campaign Center ile aynı formülle metrik üretir.

    Satır ortalaması yerine toplamlar kullanılır:
    CTR = toplam tıklama / toplam gösterim * 100
    CPC = toplam harcama / toplam tıklama
    ROAS = toplam dönüşüm değeri / toplam harcama
    """
    data = metric_qs.aggregate(
        total_impressions=Sum("impressions"),
        total_clicks=Sum("clicks"),
        total_spend=Sum("spend"),
        total_conversions=Sum("conversions"),
        total_revenue=Sum("conversion_value"),
        avg_cpm=Avg("cpm"),
        avg_engagement_rate=Avg("engagement_rate"),
    )
    impressions = data["total_impressions"] or 0
    clicks = data["total_clicks"] or 0
    spend = data["total_spend"] or Decimal("0")
    conversions = data["total_conversions"] or Decimal("0")
    revenue = data["total_revenue"] or Decimal("0")
    ctr = Decimal(clicks) / Decimal(impressions) * Decimal("100") if impressions else Decimal("0")
    cpc = Decimal(spend) / Decimal(clicks) if clicks else Decimal("0")
    roas = Decimal(revenue) / Decimal(spend) if spend else Decimal("0")
    cpm = Decimal(spend) / Decimal(impressions) * Decimal("1000") if impressions else Decimal("0")
    return {
        **data,
        "total_impressions": impressions,
        "total_clicks": clicks,
        "total_spend": spend,
        "total_conversions": conversions,
        "total_revenue": revenue,
        "avg_ctr": ctr,
        "avg_cpc": cpc,
        "avg_roas": roas,
        # Satır ortalaması değil, toplam harcama / toplam gösterim x 1000.
        # Campaign Center ile tutarlı ve 0 CPM sorununa karşı daha güvenli.
        "avg_cpm": cpm,
        "avg_engagement_rate": data.get("avg_engagement_rate") or 0,
    }

def _aggregate_performance(metric_qs):
    """Control Tower ozetini merkezi metrik servisiyle uretir."""
    summary = aggregate_metric_queryset(metric_qs)
    return {
        "total_impressions": summary.get("impressions") or 0,
        "total_clicks": summary.get("clicks") or 0,
        "total_spend": summary.get("spend") or Decimal("0"),
        "total_conversions": summary.get("conversions") or Decimal("0"),
        "total_revenue": summary.get("conversion_value") or Decimal("0"),
        "avg_ctr": summary.get("ctr") or Decimal("0"),
        "avg_cpc": summary.get("cpc") or Decimal("0"),
        "avg_roas": summary.get("roas") or Decimal("0"),
        "avg_cpm": summary.get("cpm") or Decimal("0"),
        "avg_engagement_rate": summary.get("engagement_rate") or Decimal("0"),
    }


def _performance_queryset(user, start_date, end_date):
    """Control Tower ve Campaign Center raporlarını tutarlı tutmak için ana kaynak.

    Öncelik CampaignMetricHistory'dedir. Kampanya merkezi de kampanya geçmişinden
    beslendiği için aynı tarih aralığında özet KPI'lar denk gelir. Kampanya geçmişi
    boşsa Control Tower'ın boş kalmaması için AdMetricHistory fallback kullanılır.
    """
    campaign_qs = CampaignMetricHistory.objects.filter(
        campaign__user=user,
        date__gte=start_date,
        date__lte=end_date,
    )
    if campaign_qs.exists():
        return campaign_qs, "campaign"
    return AdMetricHistory.objects.filter(
        ad__user=user,
        ad__source_type="OWN",
        date__gte=start_date,
        date__lte=end_date,
    ), "ad"

def _campaign_metric_queryset(campaign, start_date, end_date):
    """Tek kampanya sağlık kartı için güvenli metrik kaynağı.

    Öncelik CampaignMetricHistory'dedir. Eğer backfill/senkron sırasında kampanya
    geçmişi boş kalmışsa aynı kampanyaya bağlı OWN reklamların AdMetricHistory
    kayıtları kullanılır. Böylece genel Control Tower doluyken kampanya sağlık
    kartının ROAS/CTR/CVR değerleri 0 görünmez.
    """
    campaign_metrics = CampaignMetricHistory.objects.filter(
        campaign=campaign,
        date__gte=start_date,
        date__lte=end_date,
    )

    if campaign_metrics.exists():
        return campaign_metrics, "campaign"

    ad_metrics = AdMetricHistory.objects.filter(
        ad__user=campaign.user,
        ad__source_type="OWN",
        date__gte=start_date,
        date__lte=end_date,
    ).filter(
        Q(ad__campaign=campaign) | Q(ad__ad_group__campaign=campaign)
    )

    return ad_metrics, "ad_fallback"

def _bar_heights(values):
    values = [_num(v) for v in values]
    max_v = max(values) if values else 0
    if max_v <= 0:
        return [12 for _ in values] or [12, 12, 12]
    return [max(12, min(92, int((v / max_v) * 92))) for v in values]

def _period_days(period):
    # Sayfanın tamamında kullanılan otomatik tarih aralığı.
    # Kullanıcı tarih seçmez; periyot seçimi tarihi kendisi belirler.
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

def _score(value, target):
    """0-100 radar skoru. target değeri 100 puan kabul eder."""
    value = _num(value)
    target = _num(target)
    if target <= 0:
        return 0
    return int(max(0, min(100, round((value / target) * 100))))

def _inverse_score(value, good_at_or_below, bad_at_or_above):
    """Düşük olması iyi olan metrikler için 0-100 skor."""
    value = _num(value)
    good = _num(good_at_or_below)
    bad = _num(bad_at_or_above)
    if bad <= good:
        return 0
    if value <= good:
        return 100
    if value >= bad:
        return 0
    return int(max(0, min(100, round(100 - ((value - good) / (bad - good) * 100)))))

def _radar_state(score):
    score = int(max(0, min(100, _num(score))))
    if score >= 75:
        return "good", "İyi"
    if score >= 45:
        return "warn", "Orta"
    return "bad", "Zayıf"

def _weighted_avg(pairs):
    total_weight = sum(_num(weight) for _, weight in pairs)
    if total_weight <= 0:
        return 0
    return int(round(sum(_num(value) * _num(weight) for value, weight in pairs) / total_weight))

def _radar_polygon(scores, center=120, radius=78):
    """6 eksenli radar için SVG polygon point üretir."""
    angles = [-90, -30, 30, 90, 150, 210]
    points = []
    for score, angle in zip(scores, angles):
        r = radius * (max(0, min(100, _num(score))) / 100)
        rad = math.radians(angle)
        x = round(center + math.cos(rad) * r, 2)
        y = round(center + math.sin(rad) * r, 2)
        points.append(f"{x},{y}")
    return " ".join(points)

def _polyline(values, width=640, height=215):
    values = [_num(v) for v in values]
    if not values:
        return ""
    max_v = max(values) or 1
    min_v = min(values)
    span = max_v - min_v or 1
    step = width / max(len(values) - 1, 1)
    points = []

    for i, value in enumerate(values):
        x = round(i * step, 2)
        y = round(height - ((value - min_v) / span * (height - 30)) - 15, 2)
        points.append(f"{x},{y}")

    return " ".join(points)

def _strategic_items(text, max_items=4):
    """AI analiz metnini dashboard/PDF için numaralı maddelere böler.

    Serbest paragraf halinde gelen metinleri daha profesyonel göstermek için
    kısa, temiz ve noktalama uyumlu liste maddelerine dönüştürür.
    """
    if not text:
        return []
    if isinstance(text, (list, tuple)):
        raw_items = [str(x).strip() for x in text if str(x).strip()]
    else:
        raw = str(text).replace("\r", "\n")
        # Önceden numaralandırılmış veya madde işaretli metinleri koru.
        parts = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            cleaned = line.lstrip("•-* ").strip()
            if len(cleaned) > 2 and cleaned[0].isdigit() and "." in cleaned[:4]:
                cleaned = cleaned.split(".", 1)[1].strip()
            parts.append(cleaned)
        if len(parts) <= 1:
            import re
            sentence_parts = re.split(r"(?<=[.!?])\s+", raw.strip())
            parts = [p.strip() for p in sentence_parts if p.strip()]
        raw_items = parts
    items = []
    for item in raw_items:
        item = " ".join(item.split())
        if not item:
            continue
        if item[-1] not in ".!?":
            item += "."
        items.append(item)
        if len(items) >= max_items:
            break
    return items

def _ensure_numbered_report_items(items, fallback=None, max_items=6):
    """Executive Summary ve PDF için maddeleri kurumsal rapor formatına çevirir.

    Amaç: tek satırlık zayıf özetleri 1, 2, 3 şeklinde okunabilir
    yönetici maddelerine dönüştürmek.
    """
    cleaned = []
    raw_items = items if isinstance(items, (list, tuple)) else _strategic_items(items or "", max_items=max_items)
    for item in raw_items or []:
        text = " ".join(str(item or "").split())
        if not text:
            continue
        if len(text) > 2 and text[0].isdigit() and "." in text[:4]:
            text = text.split(".", 1)[1].strip()
        if text and text[-1] not in ".!?":
            text += "."
        cleaned.append(text)
        if len(cleaned) >= max_items:
            break
    if not cleaned and fallback:
        cleaned = _strategic_items(fallback, max_items=max_items)
    return cleaned[:max_items]

def _executive_opportunity_items(item, gain=0):
    title = item.get("title_tr") or "Öne çıkan fırsat"
    action_items = _ensure_numbered_report_items(item.get("recommended_action_items") or item.get("recommended_action"), max_items=3)
    impact_items = _ensure_numbered_report_items(item.get("expected_impact_items") or item.get("expected_impact_text"), max_items=2)
    what_items = _ensure_numbered_report_items(item.get("what_happened_items") or item.get("what_happened"), max_items=2)
    result = []
    if what_items:
        result.append(what_items[0])
    else:
        result.append(f"{title} gelir potansiyeli açısından öne çıkan analiz alanıdır.")
    if gain and gain > 0:
        result.append(f"Bu fırsat doğru aksiyonla yaklaşık {_fmt_money(gain)} ek gelir potansiyeli taşır.")
    elif impact_items:
        result.append(impact_items[0])
    if action_items:
        result.append(action_items[0])
    if len(action_items) > 1:
        result.append(action_items[1])
    if impact_items and (not gain or len(result) < 4):
        result.append(impact_items[-1])
    result.append("Müdahale önceliği: Yüksek; ilk 24 saat içinde değerlendirilmelidir.")
    return _ensure_numbered_report_items(result, max_items=6)

def _executive_risk_items(item, loss=0):
    title = item.get("title_tr") or "Öne çıkan risk"
    what_items = _ensure_numbered_report_items(item.get("what_happened_items") or item.get("what_happened") or item.get("analysis_tr"), max_items=2)
    why_items = _ensure_numbered_report_items(item.get("why_happened_items") or item.get("why_happened"), max_items=2)
    forecast_items = _ensure_numbered_report_items(item.get("what_will_happen_items") or item.get("what_will_happen"), max_items=2)
    action_items = _ensure_numbered_report_items(item.get("recommended_action_items") or item.get("recommended_action"), max_items=2)
    result = []
    if what_items:
        result.append(what_items[0])
    else:
        result.append(f"{title} mevcut performans görünümünde öncelikli risk alanıdır.")
    if why_items:
        result.append(why_items[0])
    if loss and loss > 0:
        result.append(f"Bu risk devam ederse yaklaşık {_fmt_money(loss)} gelir kaybı oluşabilir.")
    elif forecast_items:
        result.append(forecast_items[0])
    if action_items:
        result.append(action_items[0])
    result.append("Müdahale önceliği: Kritik; aynı gün içinde aksiyon planına alınmalıdır.")
    return _ensure_numbered_report_items(result, max_items=6)

def _build_octo_ai_analysis_pdf(report, branding=None):
    """Kayıtlı Octo AI kart analizlerini PDF olarak indirir."""
    try:
        import os
        from xml.sax.saxutils import escape
        from django.conf import settings
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Image, SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    except Exception as exc:
        response = HttpResponse(str(exc), content_type="text/plain; charset=utf-8")
        response.status_code = 500
        return response

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="octo-ai-analiz-raporu.pdf"'
    doc = SimpleDocTemplate(response, pagesize=A4, rightMargin=1.25*cm, leftMargin=1.25*cm, topMargin=1.2*cm, bottomMargin=1.2*cm)
    def _register_pdf_fonts():
        # ReportLab'in varsayılan Helvetica fontu Türkçe karakterleri düzgün gömmez.
        # Font dosyası pakete eklenmez; çalıştığı işletim sistemindeki yaygın Unicode fontları aranır.
        candidates_regular = [
            os.path.join(getattr(settings, "BASE_DIR", ""), "static", "fonts", "DejaVuSans.ttf"),
            r"C:\\Windows\\Fonts\\arial.ttf",
            r"C:\\Windows\\Fonts\\segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        ]
        candidates_bold = [
            os.path.join(getattr(settings, "BASE_DIR", ""), "static", "fonts", "DejaVuSans-Bold.ttf"),
            r"C:\\Windows\\Fonts\\arialbd.ttf",
            r"C:\\Windows\\Fonts\\segoeuib.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        ]
        regular = next((x for x in candidates_regular if x and os.path.exists(x)), None)
        bold = next((x for x in candidates_bold if x and os.path.exists(x)), None)
        if regular:
            pdfmetrics.registerFont(TTFont("CTUnicode", regular))
        if bold:
            pdfmetrics.registerFont(TTFont("CTUnicode-Bold", bold))
        return ("CTUnicode" if regular else "Helvetica", "CTUnicode-Bold" if bold else "Helvetica-Bold")

    font_regular, font_bold = _register_pdf_fonts()

    def _p(value):
        return escape(str(value or ""))

    styles = getSampleStyleSheet()
    title = ParagraphStyle("OctoTitle", parent=styles["Title"], fontName=font_bold, fontSize=18, leading=22, textColor=colors.HexColor("#111827"))
    h2 = ParagraphStyle("OctoH2", parent=styles["Heading2"], fontName=font_bold, fontSize=12, leading=15, textColor=colors.HexColor("#312E81"))
    body = ParagraphStyle("OctoBody", parent=styles["BodyText"], fontName=font_regular, fontSize=9.5, leading=13, textColor=colors.HexColor("#111827"))
    muted = ParagraphStyle("OctoMuted", parent=styles["BodyText"], fontName=font_regular, fontSize=8.5, leading=12, textColor=colors.HexColor("#4B5563"))

    story = []
    if branding and getattr(branding, "logo_path", ""):
        try:
            logo = Image(branding.logo_path)
            logo._restrictSize(4.2 * cm, 1.45 * cm)
            story.append(logo)
            story.append(Spacer(1, 8))
        except Exception:
            pass
    if branding and getattr(branding, "brand_name", ""):
        story.append(Paragraph(_p(branding.brand_name), muted))
    story.append(Paragraph("OCTO AI ANALİZ RAPORU", title))
    story.append(Paragraph(f"Dönem: {_p(report.get('date_label', '-'))} · Üretim: {_p(report.get('created_at', '-'))}", muted))
    if report.get("executive_summary"):
        es = report.get("executive_summary") or {}
        story.append(Spacer(1, 8))
        story.append(Paragraph("Executive Summary", h2))
        story.append(Paragraph(f"Durum: <b>{_p(es.get('status_label', ''))}</b> — {_p(es.get('status_text', ''))}", body))
        story.append(Paragraph(f"Fırsat: {_p(_fmt_money(es.get('potential_gain', 0)))} · Risk: {_p(_fmt_money(es.get('potential_loss', 0)))} · AI Güven: %{int(_num(es.get('confidence', 0)))}", muted))
        for label, block in (("En Kritik Fırsat", es.get("top_opportunity") or {}), ("En Kritik Risk", es.get("top_risk") or {})):
            story.append(Spacer(1, 4))
            story.append(Paragraph(f"<b>{_p(label)} — {_p(block.get('title', ''))}</b>", body))
            for idx, line in enumerate(block.get("items") or _strategic_items(block.get("detail", ""), max_items=5), start=1):
                story.append(Paragraph(f"{idx}. {_p(line)}", muted))
    story.append(Spacer(1, 10))
    summary_data = [
        ["Octo Skoru", str(report.get("octo_score", 0)), "AI Güven", f"%{report.get('avg_confidence', 0)}"],
        ["Gelir Fırsatı", _fmt_money(report.get("total_gain", 0)), "Potansiyel Kayıp", _fmt_money(report.get("total_loss", 0))],
        ["Kritik", str(report.get("critical_count", 0)), "Uyarı", str(report.get("warning_count", 0))],
    ]
    table = Table(summary_data, colWidths=[3.0*cm, 3.6*cm, 3.0*cm, 3.6*cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#F3F4F6")),
        ("BOX", (0,0), (-1,-1), .5, colors.HexColor("#D1D5DB")),
        ("INNERGRID", (0,0), (-1,-1), .25, colors.HexColor("#E5E7EB")),
        ("FONTNAME", (0,0), (-1,-1), font_regular),
        ("FONTNAME", (0,0), (0,-1), font_bold),
        ("FONTNAME", (2,0), (2,-1), font_bold),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("PADDING", (0,0), (-1,-1), 7),
    ]))
    story.append(table)
    story.append(Spacer(1, 10))
    story.append(Paragraph(_p(report.get("headline", "")), body))
    story.append(Spacer(1, 12))

    for item in report.get("analyses", []):
        story.append(Paragraph(_p(item.get("title_tr", "Kart Analizi")), h2))
        story.append(Paragraph(f"Önem: {_p(item.get('severity', '-'))} · Güven: %{_p(item.get('confidence', 0))}", muted))
        strategic_rows = [
            ("Ne oldu?", item.get("what_happened_items") or _strategic_items(item.get("what_happened") or item.get("analysis_tr", ""))),
            ("Neden oldu?", item.get("why_happened_items") or _strategic_items(item.get("why_happened", ""))),
            ("Ne olacak?", item.get("what_will_happen_items") or _strategic_items(item.get("what_will_happen", ""))),
            ("Ne yapmalıyım?", item.get("recommended_action_items") or _strategic_items(item.get("recommended_action") or item.get("recommendation_tr", ""), max_items=5)),
            ("Beklenen etki", item.get("expected_impact_items") or _strategic_items(item.get("expected_impact_text", ""))),
        ]
        for label, items in strategic_rows:
            if items:
                story.append(Paragraph(f"<b>{_p(label)}</b>", muted))
                for idx, line in enumerate(items, 1):
                    story.append(Paragraph(f"{idx}. {_p(line)}", body))
        story.append(Spacer(1, 8))

    if report.get("actions"):
        story.append(Paragraph("Aksiyonlar", h2))
        for action in report.get("actions", []):
            impact = _fmt_money(action.get("expected_impact", 0))
            story.append(Paragraph(f"• <b>{_p(action.get('title_tr',''))}</b> — Etki: {_p(impact)}", body))
            if action.get("description_tr"):
                story.append(Paragraph(_p(action.get("description_tr")), muted))

    if branding and getattr(branding, "footer_note", ""):
        story.append(Spacer(1, 8))
        story.append(Paragraph(_p(branding.footer_note), muted))

    doc.build(story)
    return response

def _build_octo_ai_report_from_latest_snapshot(user, period, date_from, date_to, agency_client=None):
    """Dashboard'u yavaşlatmadan en son kayıtlı Octo AI analiz özetini okur.

    Önemli: Bu fonksiyon yeni analiz üretmez. Analiz üretimi Celery task ile
    arka planda yapılır. Dashboard sadece DB'de hazır olan son sonucu gösterir.
    """
    if ControlTowerSnapshot is None:
        return None, None

    qs = ControlTowerSnapshot.objects.filter(user=user)
    qs = qs.filter(summary__agency_client_id=agency_client.id if agency_client else None)
    if period:
        qs = qs.filter(period=period)
    if date_from and date_to:
        qs = qs.filter(date_from=date_from, date_to=date_to)
    snapshot = qs.order_by("-snapshot_date", "-created_at").first()
    if not snapshot:
        snapshot = (
            ControlTowerSnapshot.objects
            .filter(user=user, summary__agency_client_id=agency_client.id if agency_client else None)
            .order_by("-snapshot_date", "-created_at")
            .first()
        )
    if not snapshot:
        return None, None

    # Tek tablo kaynak: ControlTowerAIAnalysis hem kısa özet hem Strategic Advisor alanlarını taşır.
    analyses_qs = list(snapshot.ai_analyses.filter(status="active").order_by("-confidence", "analysis_type", "-created_at"))
    if not analyses_qs:
        analyses_qs = list(snapshot.ai_analyses.all().order_by("-severity", "-confidence", "-created_at"))
    analyses = []
    total_gain = 0
    total_loss = 0
    severity_state = "neutral"

    severity_map = {
        "critical": "bad",
        "warning": "neutral",
        "success": "good",
        "info": "info",
    }
    for item in analyses_qs:
        payload = item.payload or {}
        # Tek tablo kaynak: ControlTowerAIAnalysis.
        # Eski ControlTowerStrategicAnalysis / using_strategic_table ayrımı kaldırıldı.
        expected_gain = _num(getattr(item, "expected_revenue_gain", 0) or payload.get("expected_gain") or payload.get("revenue_opportunity") or payload.get("impact"))
        expected_loss = _num(getattr(item, "expected_revenue_loss", 0) or payload.get("expected_loss") or payload.get("potential_loss"))
        what_text = getattr(item, "what_happened", "") or payload.get("what_happened") or item.analysis_tr
        why_text = getattr(item, "root_cause", "") or payload.get("why_happened") or "Bu karttaki metrikler diğer Control Tower sinyalleriyle birlikte değerlendirildi."
        forecast_text = getattr(item, "forecast", "") or payload.get("what_will_happen") or "Trend devam ederse mevcut risk/fırsat seviyesi bir sonraki snapshot döneminde yeniden ölçülmelidir."
        action_text = getattr(item, "action_plan", "") or payload.get("recommended_action") or item.recommendation_tr
        impact_text = getattr(item, "expected_impact", "") or payload.get("expected_impact_text") or "Beklenen etki kayıtlı metriklere göre izlenmelidir."
        analysis_text = (
            f"Ne oldu? {what_text}\n\n"
            f"Neden oldu? {why_text}\n\n"
            f"Ne olacak? {forecast_text}\n\n"
            f"Ne yapmalıyım? {action_text}\n\n"
            f"Beklenen etki: {impact_text}"
        )
        recommendation_text = action_text or item.recommendation_tr
        severity = item.severity

        total_gain += max(0, expected_gain)
        total_loss += max(0, expected_loss)
        state = severity_map.get(severity, "info")
        if state == "bad":
            severity_state = "bad"
        elif state == "neutral" and severity_state != "bad":
            severity_state = "neutral"
        elif state == "good" and severity_state not in {"bad", "neutral"}:
            severity_state = "good"
        analyses.append({
            "title_tr": item.title_tr,
            "analysis_tr": analysis_text,
            "recommendation_tr": recommendation_text,
            "confidence": item.confidence,
            "severity": severity,
            "state": state,
            "expected_gain": expected_gain,
            "expected_loss": expected_loss,
            "what_happened": what_text,
            "why_happened": why_text,
            "what_will_happen": forecast_text,
            "recommended_action": action_text,
            "expected_impact_text": impact_text,
            "what_happened_items": payload.get("what_happened_items") or _strategic_items(what_text),
            "why_happened_items": payload.get("why_happened_items") or _strategic_items(why_text),
            "what_will_happen_items": payload.get("what_will_happen_items") or _strategic_items(forecast_text),
            "recommended_action_items": payload.get("recommended_action_items") or _strategic_items(action_text, max_items=5),
            "expected_impact_items": payload.get("expected_impact_items") or _strategic_items(impact_text),
            "action_type": payload.get("action_type") or ("Acil" if state == "bad" else "Ölçekle" if state == "good" else "İzle"),
        })

    decision = snapshot.decision_center or {}
    summary = snapshot.summary or {}
    avg_conf = int(round(sum([a["confidence"] for a in analyses]) / len(analyses))) if analyses else 0
    octo_score = int(_num(snapshot.octo_score or summary.get("octo_score")))

    if severity_state == "bad":
        headline = "Octo kritik riskleri tespit etti; öncelikli aksiyon gerekiyor."
    elif total_gain > 0:
        headline = "Octo gelir fırsatları ve izlenmesi gereken sinyalleri özetledi."
    else:
        headline = "Octo sistemi dengede görüyor; izleme devam ediyor."

    actions = []
    try:
        action_qs = snapshot.action_items.all().order_by("status", "-expected_impact", "-created_at")[:8]
        for action in action_qs:
            actions.append({
                "title_tr": action.title_tr,
                "description_tr": action.description_tr,
                "expected_impact": float(action.expected_impact or 0),
                "priority": action.priority,
                "status": action.status,
            })
    except Exception:
        actions = []

    report = {
        "headline": headline,
        "created_at": timezone.localtime(snapshot.snapshot_date).strftime("%d.%m.%Y %H:%M"),
        "date_label": f"{snapshot.date_from.strftime('%d.%m.%Y')} - {snapshot.date_to.strftime('%d.%m.%Y')}",
        "overall_state": "bad" if octo_score < 50 else "neutral" if octo_score < 70 else "good",
        "octo_score": octo_score,
        "avg_confidence": avg_conf,
        "total_gain": total_gain or _num(decision.get("revenue_opportunity")),
        "total_loss": total_loss or _num(decision.get("potential_loss")),
        "analyses": analyses,
        "actions": actions,
        "snapshot_id": snapshot.id,
    }
    return report, snapshot

def _build_executive_summary_from_context(context):
    """Control Tower Executive Summary kartı için tek kaynaklı yönetici özeti.

    Yeni tablo açmaz. Öncelik kayıtlı Octo AI analiz raporundadır.
    Rapor yoksa Decision Center ve mevcut context metrikleriyle güvenli fallback üretir.
    """
    if context.get("has_performance_data") is False:
        return None

    report = context.get("octo_ai_report") or {}
    analyses = report.get("analyses") or []
    decision = context.get("decision_center") or {}
    today_summary = context.get("today_summary") or {}

    opportunities = 0
    risks = 0
    top_opportunity = None
    top_risk = None

    for item in analyses:
        state = str(item.get("state") or "").lower()
        severity = str(item.get("severity") or "").lower()
        gain = _num(item.get("expected_gain"))
        loss = _num(item.get("expected_loss"))
        title = item.get("title_tr") or "Octo analizi"
        action = item.get("recommended_action") or item.get("recommendation_tr") or "Aksiyon planı izlenmeli."

        if state == "good" or gain > 0 or severity == "success":
            opportunities += 1
            if top_opportunity is None or gain > _num(top_opportunity.get("amount")):
                top_opportunity = {
                    "title": title,
                    "detail": action,
                    "amount": gain,
                    "items": _executive_opportunity_items(item, gain),
                }

        if state == "bad" or loss > 0 or severity in {"critical", "warning"}:
            risks += 1
            if top_risk is None or loss > _num(top_risk.get("amount")):
                top_risk = {
                    "title": title,
                    "detail": item.get("what_happened") or item.get("analysis_tr") or "Risk sinyali izlenmeli.",
                    "amount": loss,
                    "items": _executive_risk_items(item, loss),
                }

    potential_gain = _num(report.get("total_gain"))
    potential_loss = _num(report.get("total_loss"))
    if potential_gain <= 0:
        potential_gain = _num(decision.get("revenue_opportunity"))
    if potential_loss <= 0:
        potential_loss = _num(decision.get("potential_loss"))

    confidence = int(_num(report.get("avg_confidence"))) if report else 0
    if confidence <= 0:
        confidence = 80 if analyses else 0

    octo_score = _num(report.get("octo_score"))
    if octo_score <= 0:
        try:
            octo_score = _num((context.get("summary") or {}).get("octo_score"))
        except Exception:
            octo_score = 0

    if risks >= 3 or potential_loss > potential_gain:
        status = "risk"
        status_label = "RİSKLİ"
        status_icon = "fa-triangle-exclamation"
        status_text = "Öncelik risk azaltma ve aksiyon takibinde olmalı."
    elif opportunities > 0 or potential_gain > 0 or octo_score >= 70:
        status = "positive"
        status_label = "POZİTİF"
        status_icon = "fa-circle-check"
        status_text = "Fırsatlar öne çıkıyor; kontrollü ölçekleme yapılabilir."
    else:
        status = "neutral"
        status_label = "İZLEMEDE"
        status_icon = "fa-eye"
        status_text = "Kritik sinyal sınırlı; veriler düzenli izlenmeli."

    if not top_opportunity:
        top_opportunity = {
            "title": "Ölçeklenebilir fırsat izleniyor",
            "detail": "Octo yeni gelir fırsatlarını sonraki snapshot döneminde yeniden ölçecek.",
            "amount": potential_gain,
            "items": _ensure_numbered_report_items([
                "Mevcut snapshot içinde yüksek güvenli fırsatlar izlenmeye devam ediyor.",
                "Yeni gelir potansiyeli oluştuğunda Octo bu alanı öncelikli fırsat olarak işaretleyecek.",
                "Kampanya, kreatif ve rakip sinyalleri sonraki analiz döneminde tekrar karşılaştırılmalıdır.",
            ]),
        }
    if not top_risk:
        top_risk = {
            "title": "Kritik risk sınırlı",
            "detail": "Acil müdahale gerektiren büyük bir risk sinyali öne çıkmadı.",
            "amount": potential_loss,
            "items": _ensure_numbered_report_items([
                "Mevcut analizde acil müdahale gerektiren büyük bir risk öne çıkmadı.",
                "Risk seviyesi düşük olsa bile kreatif yorgunluğu, bütçe verimliliği ve rakip baskısı izlenmelidir.",
                "Yeni kritik sinyal oluşursa Octo bunu sonraki analizde risk alanına taşıyacaktır.",
            ]),
        }

    return {
        "status": status,
        "status_label": status_label,
        "status_icon": status_icon,
        "status_text": status_text,
        "opportunities": opportunities,
        "risks": risks,
        "potential_gain": potential_gain,
        "potential_loss": potential_loss,
        "confidence": confidence,
        "octo_score": int(octo_score) if octo_score else 0,
        "top_opportunity": top_opportunity,
        "top_risk": top_risk,
        "campaigns": today_summary.get("campaigns", 0),
        "pending_tasks": today_summary.get("pending_tasks", 0),
        "critical_alerts": today_summary.get("critical_alerts", 0),
        "updated_at": report.get("created_at") or "Henüz analiz yok",
    }

def _control_tower_refresh_meta(user, period, date_from, date_to, agency_client=None):
    """Control Tower üst bilgi alanı için son snapshot / AI analiz güncellik bilgisi."""
    meta = {
        "snapshot_time": "Henüz kayıt yok",
        "snapshot_age": "-",
        "snapshot_state": "warn",
        "ai_time": "Henüz analiz yok",
        "ai_age": "-",
        "ai_state": "warn",
        "period_label": _period_label(period),
        "snapshot_refresh_label": "15 dk",
        "ai_refresh_label": "24 saat",
        "status_label": "İzlenmeli",
        "status_state": "warn",
    }
    if ControlTowerSnapshot is None:
        meta["status_label"] = "Snapshot modeli yok"
        meta["status_state"] = "bad"
        return meta

    def _age_label(dt):
        if not dt:
            return "-"
        now = timezone.localtime()
        dt = timezone.localtime(dt)
        minutes = max(0, int((now - dt).total_seconds() // 60))
        if minutes < 1:
            return "şimdi"
        if minutes < 60:
            return f"{minutes} dk önce"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} saat önce"
        return f"{hours // 24} gün önce"

    snapshot = ControlTowerSnapshot.objects.filter(
        user=user,
        period=period,
        date_from=date_from,
        date_to=date_to,
        summary__agency_client_id=agency_client.id if agency_client else None,
    ).order_by("-snapshot_date", "-created_at").first()
    if not snapshot:
        snapshot = (
            ControlTowerSnapshot.objects
            .filter(user=user, summary__agency_client_id=agency_client.id if agency_client else None)
            .order_by("-snapshot_date", "-created_at")
            .first()
        )

    if snapshot:
        meta["snapshot_time"] = timezone.localtime(snapshot.snapshot_date).strftime("%d.%m.%Y %H:%M")
        meta["snapshot_age"] = _age_label(snapshot.snapshot_date)
        age_min = max(0, int((timezone.localtime() - timezone.localtime(snapshot.snapshot_date)).total_seconds() // 60))
        meta["snapshot_state"] = "good" if age_min <= 30 else "warn" if age_min <= 180 else "bad"
        meta["status_label"] = "Güncel" if meta["snapshot_state"] == "good" else "Güncelleme gerekli"
        meta["status_state"] = meta["snapshot_state"]

        last_ai = snapshot.ai_analyses.order_by("-created_at").first()
        if not last_ai:
            last_ai = (
                ControlTowerSnapshot.objects
                .filter(user=user, summary__agency_client_id=agency_client.id if agency_client else None)
                .exclude(ai_analyses=None)
                .order_by("-snapshot_date")
                .first()
            )
            if last_ai:
                last_ai = last_ai.ai_analyses.order_by("-created_at").first()
        if last_ai:
            meta["ai_time"] = timezone.localtime(last_ai.created_at).strftime("%d.%m.%Y %H:%M")
            meta["ai_age"] = _age_label(last_ai.created_at)
            ai_age_min = max(0, int((timezone.localtime() - timezone.localtime(last_ai.created_at)).total_seconds() // 60))
            meta["ai_state"] = "good" if ai_age_min <= 24 * 60 else "warn" if ai_age_min <= 72 * 60 else "bad"
    return meta

def _analysis_model_field_names():
    if ControlTowerAIAnalysis is None:
        return set()
    try:
        return {field.name for field in ControlTowerAIAnalysis._meta.get_fields()}
    except Exception:
        return set()

def _safe_create_ai_analysis(**kwargs):
    """ControlTowerAIAnalysis alanları sürümler arasında değişebildiği için
    yalnızca modelde bulunan alanlarla kayıt oluşturur.
    """
    if ControlTowerAIAnalysis is None:
        return None
    field_names = _analysis_model_field_names()
    clean = {key: value for key, value in kwargs.items() if key in field_names}
    return ControlTowerAIAnalysis.objects.create(**clean)

def _save_executive_summary_ai_record(snapshot, executive_summary):
    """Executive Summary dashboardda hesaplanıp uçmamalı; arşiv ve PDF için
    aynı ControlTowerAIAnalysis tablosuna ayrı bir kayıt olarak yazılır.
    """
    if not snapshot or ControlTowerAIAnalysis is None or not executive_summary:
        return None

    opportunity = executive_summary.get("top_opportunity") or {}
    risk = executive_summary.get("top_risk") or {}
    status = executive_summary.get("status") or "neutral"
    severity = "success" if status == "positive" else "critical" if status == "risk" else "info"

    what_items = _ensure_numbered_report_items([
        f"Genel durum {executive_summary.get('status_label', 'İZLEMEDE')} olarak değerlendirildi.",
        f"Analizde {executive_summary.get('opportunities', 0)} fırsat ve {executive_summary.get('risks', 0)} risk sinyali öne çıktı.",
        f"Toplam potansiyel kazanç {_fmt_money(executive_summary.get('potential_gain', 0))}, risk altındaki gelir {_fmt_money(executive_summary.get('potential_loss', 0))} seviyesinde hesaplandı.",
        f"AI güven skoru %{executive_summary.get('confidence', 0)} olarak ölçüldü.",
    ])
    root_items = _ensure_numbered_report_items([
        "Fırsat ve risk değerlendirmesi ControlTowerAIAnalysis kayıtlarındaki kart bazlı sinyallerden üretildi.",
        "Beklenen kazanç/kayıp alanları Strategic Advisor, Decision Center ve kart analizlerinin finansal etkileriyle birlikte değerlendirildi.",
        "Genel durum, risklerin toplam etkisi ile fırsatların toplam etkisi karşılaştırılarak belirlendi.",
    ])
    forecast_items = _ensure_numbered_report_items([
        f"Fırsatlar uygulanırsa kısa vadede {_fmt_money(executive_summary.get('potential_gain', 0))} seviyesinde ek değer potansiyeli oluşabilir.",
        f"Riskler takip edilmezse {_fmt_money(executive_summary.get('potential_loss', 0))} seviyesinde gelir kaybı riski oluşabilir.",
        "Önümüzdeki analiz döneminde aynı sinyaller tekrar ölçülerek durum güncellenecektir.",
    ])
    action_items = _ensure_numbered_report_items([
        f"Öncelikle '{opportunity.get('title', 'En kritik fırsat')}' alanındaki fırsat incelenmelidir.",
        f"Ardından '{risk.get('title', 'En kritik risk')}' alanındaki risk için müdahale planı hazırlanmalıdır.",
        "Aksiyonlar uygulandıktan sonra bir sonraki snapshot ve AI analiz sonucu ile etkisi karşılaştırılmalıdır.",
    ])
    impact_items = _ensure_numbered_report_items([
        f"Beklenen pozitif etki: {_fmt_money(executive_summary.get('potential_gain', 0))} potansiyel kazanç.",
        f"Önlenmesi gereken negatif etki: {_fmt_money(executive_summary.get('potential_loss', 0))} risk altındaki gelir.",
        f"Öncelik: {executive_summary.get('status_label', 'İZLEMEDE')}; güven skoru %{executive_summary.get('confidence', 0)}.",
    ])

    payload = {
        "analysis_type": "executive_summary",
        "executive_summary": executive_summary,
        "what_happened_items": what_items,
        "root_cause_items": root_items,
        "forecast_items": forecast_items,
        "recommended_action_items": action_items,
        "expected_impact_items": impact_items,
    }

    return _safe_create_ai_analysis(
        snapshot=snapshot,
        card_key="executive_summary",
        analysis_type="executive_summary",
        title_tr="Octo Executive Summary",
        title_en="Octo Executive Summary",
        analysis_tr="\n".join(what_items),
        recommendation_tr="\n".join(action_items),
        what_happened="\n".join(what_items),
        root_cause="\n".join(root_items),
        forecast="\n".join(forecast_items),
        action_plan="\n".join(action_items),
        expected_impact="\n".join(impact_items),
        expected_revenue_gain=Decimal(str(executive_summary.get("potential_gain", 0) or 0)),
        expected_revenue_loss=Decimal(str(executive_summary.get("potential_loss", 0) or 0)),
        expected_roas_change=Decimal("0"),
        expected_ctr_change=Decimal("0"),
        severity=severity,
        priority="high" if status in {"positive", "risk"} else "medium",
        status="active",
        confidence=int(_num(executive_summary.get("confidence", 0))),
        payload=payload,
    )

def _archive_analysis_to_row(item):
    """ControlTowerAIAnalysis kaydını arşiv ekranının okuyacağı rapor formatına çevirir."""
    payload = getattr(item, "payload", None) or {}
    created_at = timezone.localtime(item.created_at) if getattr(item, "created_at", None) else timezone.localtime()
    severity = str(getattr(item, "severity", "info") or "info")
    state_map = {
        "critical": "bad",
        "warning": "neutral",
        "success": "good",
        "info": "info",
    }
    state = state_map.get(severity, "info")
    analysis_type = getattr(item, "analysis_type", "") or payload.get("analysis_type") or getattr(item, "card_key", "general")

    what_happened = getattr(item, "what_happened", "") or payload.get("what_happened") or getattr(item, "analysis_tr", "") or ""
    root_cause = getattr(item, "root_cause", "") or payload.get("root_cause") or payload.get("why_happened") or ""
    forecast = getattr(item, "forecast", "") or payload.get("forecast") or payload.get("what_will_happen") or ""
    action_plan = getattr(item, "action_plan", "") or payload.get("action_plan") or payload.get("recommended_action") or getattr(item, "recommendation_tr", "") or ""
    expected_impact = getattr(item, "expected_impact", "") or payload.get("expected_impact") or payload.get("expected_impact_text") or ""

    expected_gain = _num(getattr(item, "expected_revenue_gain", 0) or payload.get("expected_gain") or payload.get("revenue_opportunity"))
    expected_loss = _num(getattr(item, "expected_revenue_loss", 0) or payload.get("expected_loss") or payload.get("potential_loss"))

    return {
        "id": item.id,
        "title_tr": getattr(item, "title_tr", "") or "Octo AI Analizi",
        "title_en": getattr(item, "title_en", "") or "Octo AI Analysis",
        "card_key": getattr(item, "card_key", "general"),
        "analysis_type": analysis_type,
        "severity": severity,
        "state": state,
        "confidence": int(_num(getattr(item, "confidence", 0))),
        "priority": getattr(item, "priority", "medium") or payload.get("priority") or "medium",
        "status": getattr(item, "status", "active") or payload.get("status") or "active",
        "created_at": created_at,
        "created_label": created_at.strftime("%d.%m.%Y %H:%M"),
        "expected_gain": expected_gain,
        "expected_loss": expected_loss,
        "what_happened": what_happened,
        "root_cause": root_cause,
        "forecast": forecast,
        "action_plan": action_plan,
        "expected_impact": expected_impact,
        "what_happened_items": payload.get("what_happened_items") or _strategic_items(what_happened, max_items=6),
        "root_cause_items": payload.get("root_cause_items") or payload.get("why_happened_items") or _strategic_items(root_cause, max_items=6),
        "forecast_items": payload.get("forecast_items") or payload.get("what_will_happen_items") or _strategic_items(forecast, max_items=6),
        "recommended_action_items": payload.get("recommended_action_items") or _strategic_items(action_plan, max_items=6),
        "expected_impact_items": payload.get("expected_impact_items") or _strategic_items(expected_impact, max_items=6),
    }
