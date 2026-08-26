from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from core.models import (
    Ad,
    AdMetricHistory,
    Campaign,
    CampaignMetricHistory,
    ControlTowerActionItem,
    ControlTowerAIAnalysis,
    ControlTowerCardSnapshot,
    ControlTowerSnapshot,
)
from core.services.performance_metrics import aggregate_metric_queryset


def _num(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _pct_change(current, previous):
    current = _num(current)
    previous = _num(previous)
    if previous <= 0.01:
        return 0.0
    change = ((current - previous) / previous) * 100
    return round(max(min(change, 999), -999), 1)



def _json_safe(value):
    """Snapshot JSONField için model/date/Decimal nesnelerini güvenli payload'a çevirir."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    # Notification / AnomalyAlert gibi model nesneleri
    return {
        "id": getattr(value, "id", None),
        "message": getattr(value, "message", None) or getattr(value, "title", None) or str(value),
        "created_at": getattr(value, "created_at", None).isoformat() if getattr(value, "created_at", None) else None,
    }


def _direction(value, higher_is_good=True):
    value = _num(value)
    if abs(value) < 0.1:
        return {"state": "neutral", "icon": "▬", "label_tr": "Durağan", "label_en": "Stable"}
    good = value > 0 if higher_is_good else value < 0
    return {
        "state": "good" if good else "bad",
        "icon": "▲" if value > 0 else "▼",
        "label_tr": "Yükseldi" if value > 0 else "Düştü",
        "label_en": "Up" if value > 0 else "Down",
    }


def build_decision_center_from_context(context):
    summary = context.get("summary", {})
    campaign_health = context.get("campaign_health", []) or []
    critical_alerts = context.get("critical_alerts", []) or []
    ai_task_stats = context.get("ai_task_stats", {}) or {}
    competitor_rows = context.get("competitor_rows", []) or []
    competitor_intelligence = context.get("competitor_intelligence", {}) or {}

    total_spend = _num(summary.get("total_spend"))
    total_revenue = _num(summary.get("total_revenue"))
    avg_roas = _num(summary.get("avg_roas"))
    octo_score = _num(summary.get("octo_score"))

    risky_campaigns = [r for r in campaign_health if str(r.get("level", "")).lower() in {"bad", "risk", "critical", "danger"}]
    scalable_campaigns = [r for r in campaign_health if _num(r.get("roas")) >= max(avg_roas, 1.5) and _num(r.get("score")) >= 70]

    potential_loss = sum(_num(r.get("spend")) for r in risky_campaigns[:5]) * 0.18
    revenue_opportunity = sum(_num(r.get("revenue")) for r in scalable_campaigns[:5]) * 0.12
    competitor_pressure = _num(competitor_intelligence.get("pressure_score")) or sum(int(_num(r.get("new_ads"))) for r in competitor_rows[:5])

    items = []
    if risky_campaigns:
        row = risky_campaigns[0]
        items.append({
            "priority": "critical",
            "icon": "▼",
            "state": "bad",
            "title_tr": f"{row.get('name', 'Riskli kampanya')} için müdahale gerekiyor",
            "title_en": "Campaign intervention required",
            "detail_tr": row.get("reason") or "ROAS/CTR/CPC sinyalleri risk üretiyor.",
            "impact": round(potential_loss, 2),
        })
    if scalable_campaigns:
        row = scalable_campaigns[0]
        items.append({
            "priority": "high",
            "icon": "▲",
            "state": "good",
            "title_tr": f"{row.get('name', 'Başarılı kampanya')} ölçeklenebilir",
            "title_en": "Campaign can be scaled",
            "detail_tr": "ROAS ve sağlık skoru ortalamanın üzerinde.",
            "impact": round(revenue_opportunity, 2),
        })
    if critical_alerts:
        alert = critical_alerts[0]
        items.append({
            "priority": "high",
            "icon": "▼",
            "state": "bad",
            "title_tr": "Kritik uyarı öncelikli incelenmeli",
            "title_en": "Critical alert needs review",
            "detail_tr": getattr(alert, "message", None) or alert.get("message", "Kritik uyarı var."),
            "impact": 0,
        })
    if ai_task_stats.get("pending", 0):
        items.append({
            "priority": "medium",
            "icon": "▬",
            "state": "neutral",
            "title_tr": "Bekleyen Octo görevleri var",
            "title_en": "Pending Octo tasks",
            "detail_tr": f"{ai_task_stats.get('pending', 0)} görev karar bekliyor.",
            "impact": 0,
        })

    if not items:
        items.append({
            "priority": "low",
            "icon": "▬",
            "state": "neutral",
            "title_tr": "Sistem dengede, izleme devam ediyor",
            "title_en": "System stable, monitoring continues",
            "detail_tr": "Kritik müdahale gerektiren sinyal yok.",
            "impact": 0,
        })

    return {
        "title_tr": "OCTO KARAR MERKEZİ",
        "title_en": "OCTO DECISION CENTER",
        "tooltip_tr": "Veritabanına kaydedilen kampanya, kreatif, rakip, uyarı ve Octo görev sinyallerinden günlük karar özeti üretir.",
        "updated_at": timezone.localtime().strftime("%d.%m.%Y %H:%M"),
        "metrics": [
            {
                "key": "revenue_opportunity",
                "label_tr": "Gelir Fırsatı",
                "label_en": "Revenue Opportunity",
                "value": round(revenue_opportunity, 2),
                "prefix": "₺",
                "suffix": "",
                "direction": _direction(revenue_opportunity, True),
                "tooltip_tr": "Ölçeklenebilir kampanyalardaki tahmini ek gelir potansiyeli.",
            },
            {
                "key": "potential_loss",
                "label_tr": "Potansiyel Kayıp",
                "label_en": "Potential Loss",
                "value": round(potential_loss, 2),
                "prefix": "₺",
                "suffix": "",
                "direction": _direction(potential_loss, False),
                "tooltip_tr": "Riskli kampanyaların mevcut harcamasına göre tahmini kayıp riski.",
            },
            {
                "key": "scale_opportunities",
                "label_tr": "Ölçeklenebilir",
                "label_en": "Scalable",
                "value": len(scalable_campaigns),
                "prefix": "",
                "suffix": "",
                "direction": _direction(len(scalable_campaigns), True),
                "tooltip_tr": "ROAS ve sağlık skoru güçlü olan kampanya sayısı.",
            },
            {
                "key": "risk_campaigns",
                "label_tr": "Riskli Kampanya",
                "label_en": "Risk Campaigns",
                "value": len(risky_campaigns),
                "prefix": "",
                "suffix": "",
                "direction": _direction(len(risky_campaigns), False),
                "tooltip_tr": "Acil izlenmesi gereken kampanya sayısı.",
            },
            {
                "key": "competitor_pressure",
                "label_tr": "Rakip Baskısı",
                "label_en": "Competitor Pressure",
                "value": int(_num(competitor_pressure)),
                "prefix": "",
                "suffix": "/100",
                "direction": _direction(-_num(competitor_pressure), True),
                "tooltip_tr": "Rakip reklam yoğunluğu, momentum ve paylaşım sesi üzerinden üretilen baskı skoru.",
            },
        ],
        "items": items[:5],
        "health_state": "good" if octo_score >= 75 else "neutral" if octo_score >= 55 else "bad",
        "competitor_pressure": competitor_pressure,
        "competitor_intelligence": _json_safe(competitor_intelligence),
    }




def _money_text(value):
    value = _num(value)
    try:
        return f"₺{value:,.0f}".replace(",", ".")
    except Exception:
        return f"₺{int(value)}"


def _pct_text(value):
    value = _num(value)
    raw = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"%{raw.replace('.', ',')}"


def _ratio_text(value):
    value = _num(value)
    return f"{value:.1f}".replace(".", ",")


def _top_name(rows, default="ilgili kampanya"):
    if not rows:
        return default
    row = rows[0] or {}
    return row.get("name") or row.get("title") or row.get("campaign_name") or default



def _strategic_items(text, max_items=4):
    if not text:
        return []
    if isinstance(text, (list, tuple)):
        candidates = [str(x).strip() for x in text if str(x).strip()]
    else:
        raw = str(text).replace("\r", "\n")
        candidates = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            line = line.lstrip("•-* ").strip()
            if len(line) > 2 and line[0].isdigit() and "." in line[:4]:
                line = line.split(".", 1)[1].strip()
            candidates.append(line)
        if len(candidates) <= 1:
            import re
            candidates = [p.strip() for p in re.split(r"(?<=[.!?])\s+", raw.strip()) if p.strip()]
    items = []
    for item in candidates:
        item = " ".join(item.split())
        if not item:
            continue
        if item[-1] not in ".!?:":
            item += "."
        items.append(item)
        if len(items) >= max_items:
            break
    return items

def _strategic_payload(*, what, why, forecast, action, impact, expected_gain=0, expected_loss=0, action_type="İzle", confidence=84, extra=None):
    payload = {
        "what_happened": what,
        "why_happened": why,
        "what_will_happen": forecast,
        "recommended_action": action,
        "expected_impact_text": impact,
        "what_happened_items": _strategic_items(what),
        "why_happened_items": _strategic_items(why),
        "what_will_happen_items": _strategic_items(forecast),
        "recommended_action_items": _strategic_items(action, max_items=5),
        "expected_impact_items": _strategic_items(impact),
        "expected_gain": round(_num(expected_gain), 2),
        "expected_loss": round(_num(expected_loss), 2),
        "action_type": action_type,
        "confidence": int(_num(confidence)),
    }
    if extra:
        payload.update(extra)
    return payload


def _create_strategic_analysis(snapshot, *, card_key, title_tr, title_en, severity, confidence, what, why, forecast, action, impact, expected_gain=0, expected_loss=0, action_type="İzle", extra=None):
    payload = _strategic_payload(
        what=what,
        why=why,
        forecast=forecast,
        action=action,
        impact=impact,
        expected_gain=expected_gain,
        expected_loss=expected_loss,
        action_type=action_type,
        confidence=confidence,
        extra=extra,
    )
    analysis_text = (
        f"Ne oldu? {what}\n\n"
        f"Neden oldu? {why}\n\n"
        f"Ne olacak? {forecast}\n\n"
        f"Ne yapmalıyım? {action}\n\n"
        f"Beklenen etki: {impact}"
    )
    action_items = _strategic_items(action, max_items=5)
    impact_items = _strategic_items(impact)
    recommendation_lines = []
    for idx, line in enumerate(action_items, 1):
        recommendation_lines.append(f"{idx}. {line}")
    if impact_items:
        recommendation_lines.append(f"Beklenen etki: {impact_items[0]}")
    recommendation_text = "\n".join(recommendation_lines) if recommendation_lines else f"{action} Beklenen etki: {impact}"
    analysis_type_map = {
        ControlTowerCardSnapshot.CARD_KPI: "octo_score",
        ControlTowerCardSnapshot.CARD_CAMPAIGN_HEALTH: "campaign_health",
        ControlTowerCardSnapshot.CARD_CREATIVE: "creative_wall",
        ControlTowerCardSnapshot.CARD_COMPETITOR: "competitor_intelligence",
        ControlTowerCardSnapshot.CARD_PLATFORM: "platform_status",
        ControlTowerCardSnapshot.CARD_ALERT: "critical_alerts",
        ControlTowerCardSnapshot.CARD_DECISION: "decision_center",
    }
    priority = "critical" if severity == "critical" else "high" if severity == "warning" else "medium" if severity == "info" else "low"
    ai_analysis = ControlTowerAIAnalysis.objects.create(
        snapshot=snapshot,
        card_key=card_key,
        title_tr=title_tr,
        title_en=title_en,
        analysis_tr=analysis_text,
        recommendation_tr=recommendation_text,
        severity=severity,
        confidence=int(_num(confidence)),
        payload=_json_safe(payload),
        analysis_type=analysis_type_map.get(card_key, card_key),
        what_happened=what,
        root_cause=why,
        forecast=forecast,
        action_plan=recommendation_text,
        expected_impact=impact,
        expected_revenue_gain=Decimal(str(round(_num(expected_gain), 2))),
        expected_revenue_loss=Decimal(str(round(_num(expected_loss), 2))),
        expected_roas_change=Decimal(str(round(_num((extra or {}).get("expected_roas_change")), 2))),
        expected_ctr_change=Decimal(str(round(_num((extra or {}).get("expected_ctr_change")), 2))),
        priority=priority,
        status="active",
    )
    return ai_analysis

def save_snapshot_from_context(user, period, date_from, date_to, context, agency_client=None):
    decision_center = build_decision_center_from_context(context)
    summary = {
        **(context.get("summary", {}) or {}),
        "agency_client_id": agency_client.id if agency_client else None,
        "agency_client_name": agency_client.name if agency_client else "",
    }
    snapshot = ControlTowerSnapshot.objects.create(
        user=user,
        period=period or ControlTowerSnapshot.PERIOD_CUSTOM,
        date_from=date_from,
        date_to=date_to,
        octo_score=int(_num(summary.get("octo_score"))),
        summary=_json_safe(summary),
        decision_center=_json_safe(decision_center),
    )

    cards = [
        (ControlTowerCardSnapshot.CARD_KPI, "KPI Şeridi", "KPI Strip", summary),
        (ControlTowerCardSnapshot.CARD_DECISION, "Octo Karar Merkezi", "Octo Decision Center", decision_center),
        (ControlTowerCardSnapshot.CARD_CAMPAIGN_HEALTH, "Kampanya Sağlık Merkezi", "Campaign Health Center", {"rows": context.get("campaign_health", [])}),
        (ControlTowerCardSnapshot.CARD_CREATIVE, "Creative Performans Duvarı", "Creative Performance Wall", {"rows": context.get("creative_wall", [])}),
        (ControlTowerCardSnapshot.CARD_COMPETITOR, "Rakip İstihbarat Merkezi", "Competitor Intelligence Center", {"rows": context.get("competitor_rows", []), "intelligence": context.get("competitor_intelligence", {})}),
        (ControlTowerCardSnapshot.CARD_PLATFORM, "Platform Durum Merkezi", "Platform Status Center", {"rows": context.get("platform_status_cards", [])}),
        (ControlTowerCardSnapshot.CARD_TASK, "Octo Görev Merkezi", "Octo Task Center", {"stats": context.get("ai_task_stats", {}), "rows": context.get("ai_recommendations", [])}),
        (ControlTowerCardSnapshot.CARD_ALERT, "Kritik Uyarılar", "Critical Alerts", {"rows": context.get("critical_alerts", [])}),
    ]
    for key, title_tr, title_en, payload in cards:
        ControlTowerCardSnapshot.objects.create(
            snapshot=snapshot,
            card_key=key,
            title_tr=title_tr,
            title_en=title_en,
            status=decision_center.get("health_state", "stable") if key == ControlTowerCardSnapshot.CARD_DECISION else "stable",
            score=int(_num(summary.get("octo_score"))) if key == ControlTowerCardSnapshot.CARD_KPI else 0,
            payload=_json_safe(payload),
        )

    for item in decision_center.get("items", []):
        ControlTowerActionItem.objects.create(
            snapshot=snapshot,
            user=user,
            card_key=ControlTowerCardSnapshot.CARD_DECISION,
            title_tr=item.get("title_tr", "Octo aksiyonu"),
            title_en=item.get("title_en", "Octo action"),
            description_tr=item.get("detail_tr", ""),
            expected_impact=Decimal(str(item.get("impact", 0) or 0)),
            priority=item.get("priority", "medium"),
            action_payload=item,
        )

    # Premium Strategic Advisor: Her ana kart için 5 bloklu danışman analizi üretir.
    # Format: Ne oldu / Neden oldu / Ne olacak / Ne yapmalıyım / Beklenen etki.
    campaign_rows = context.get("campaign_health", []) or []
    creative_rows = context.get("creative_wall", []) or []
    platform_rows = context.get("platform_status_cards", []) or []
    alerts = context.get("critical_alerts", []) or []
    competitor_intel = context.get("competitor_intelligence", {}) or {}
    competitor_rows = context.get("competitor_rows", []) or []

    roas = _num(summary.get("avg_roas"))
    ctr = _num(summary.get("avg_ctr"))
    cpc = _num(summary.get("avg_cpc"))
    revenue = _num(summary.get("total_revenue"))
    spend = _num(summary.get("total_spend"))
    conversion_rate = _num(summary.get("conversion_rate"))
    roas_delta = _num(summary.get("roas_delta"))
    ctr_delta = _num(summary.get("ctr_delta"))
    cpc_delta = _num(summary.get("cpc_delta"))
    octo_score = _num(summary.get("octo_score"))

    risky = [r for r in campaign_rows if str(r.get("level", "")).lower() in {"bad", "risk", "critical", "danger", "mid"}]
    strong = [r for r in campaign_rows if _num(r.get("score")) >= 70]
    top_risky = _top_name(risky, "riskli kampanya")
    top_strong = _top_name(strong, "güçlü kampanya")

    campaign_loss = sum(_num(r.get("spend")) for r in risky[:5]) * 0.16 if risky else max(0, spend * 0.08 if roas < 1.5 else 0)
    campaign_gain = sum(_num(r.get("revenue")) for r in strong[:5]) * 0.10 if strong else max(0, revenue * 0.05 if roas >= 1.5 else 0)
    perf_gain = max(0, revenue * 0.08) if roas >= 1.5 else 0
    perf_loss = max(0, spend * 0.18) if roas < 1.5 else max(0, spend * 0.06 if roas_delta < 0 else 0)

    perf_severity = "success" if roas >= 3 and roas_delta >= 0 else "warning" if roas >= 1.5 else "critical"
    _create_strategic_analysis(
        snapshot,
        card_key=ControlTowerCardSnapshot.CARD_KPI,
        title_tr="Executive KPI ve Octo Skor Stratejik Analizi",
        title_en="Executive KPI and Octo Score Strategic Analysis",
        severity=perf_severity,
        confidence=90,
        what=(
            f"Octo {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')} dönemini taradı. "
            f"Genel Octo skoru {int(octo_score)}/100, ROAS {_ratio_text(roas)}, CTR {_pct_text(ctr)}, CPC {_money_text(cpc)} seviyesinde. "
            f"ROAS değişimi {_pct_text(roas_delta)}, CTR değişimi {_pct_text(ctr_delta)}, CPC değişimi {_pct_text(cpc_delta)}."
        ),
        why=(
            "Genel skorun ana belirleyicisi yalnızca tek bir KPI değil; harcama verimliliği, dönüşüm kalitesi, kreatif performans, rakip baskısı ve kritik uyarı yoğunluğu birlikte skoru şekillendiriyor. "
            "ROAS düşerken CPC yükseliyorsa problem çoğu zaman bütçe ölçeği değil, trafik kalitesi ve hedefleme dağılımıdır."
        ),
        forecast=(
            f"Mevcut eğilim korunursa kısa vadede yaklaşık {_money_text(perf_loss)} risk oluşabilir. "
            f"Pozitif senaryoda ölçeklenebilir alanlardan {_money_text(perf_gain)} ek gelir fırsatı yakalanabilir."
        ),
        action=(
            "Önce düşük verimli harcama noktalarını dondurun, sonra ROAS ve dönüşüm kalitesi güçlü kampanyalara kontrollü bütçe aktarın. "
            "CPC artışı varsa bütçe artırmadan önce hedef kitle, yerleşim ve dönüşüm kırılımlarını doğrulayın."
        ),
        impact=f"Beklenen net etki: {_money_text(perf_gain)} fırsat, {_money_text(perf_loss)} korunması gereken risk.",
        expected_gain=perf_gain,
        expected_loss=perf_loss,
        action_type="Optimize Et" if perf_severity != "success" else "Ölçekle",
        extra={"roas": roas, "ctr": ctr, "cpc": cpc, "octo_score": octo_score},
    )

    _create_strategic_analysis(
        snapshot,
        card_key=ControlTowerCardSnapshot.CARD_CAMPAIGN_HEALTH,
        title_tr="Kampanya Sağlık Merkezi Stratejik Analizi",
        title_en="Campaign Health Center Strategic Analysis",
        severity="critical" if risky else "success" if strong else "info",
        confidence=88,
        what=(
            f"Octo {len(campaign_rows)} kampanya sağlık sinyalini inceledi. "
            f"Riskli/izlenmesi gereken kampanya sayısı {len(risky)}, ölçeklenebilir kampanya sayısı {len(strong)}. "
            f"Öne çıkan risk: {top_risky}. Öne çıkan fırsat: {top_strong}."
        ),
        why=(
            "Kampanya sağlığını düşüren ana sinyaller ROAS zayıflaması, dönüşüm kalitesi düşüşü, harcama verimsizliği ve kritik uyarı yoğunluğudur. "
            "Sağlıklı kampanyalarda ise yüksek ROAS tek başına yeterli değildir; veri güveni ve trend devamlılığı da aranır."
        ),
        forecast=(
            f"Riskli kampanyalara müdahale edilmezse yaklaşık {_money_text(campaign_loss)} kayıp riski oluşabilir. "
            f"Sağlıklı kampanyalar kontrollü ölçeklenirse yaklaşık {_money_text(campaign_gain)} ek gelir potansiyeli vardır."
        ),
        action=(
            "İlk aksiyon olarak düşük skorlu kampanyalarda bütçe artışını durdurun. "
            "Ardından güçlü kampanyalarda küçük oranlı bütçe artışı yapın ve sonuçları bir sonraki snapshot döneminde tekrar ölçün."
        ),
        impact=f"Beklenen etki: {_money_text(campaign_gain)} fırsat, {_money_text(campaign_loss)} risk azaltımı.",
        expected_gain=campaign_gain,
        expected_loss=campaign_loss,
        action_type="Acil Müdahale" if risky else "Kontrollü Ölçekle",
        extra={"risk_count": len(risky), "strong_count": len(strong)},
    )

    fatigue_count = len([c for c in creative_rows if _num(c.get("fatigue")) >= 70 or str(c.get("level", "")).lower() in {"bad", "risk", "critical"}])
    creative_gain = max(0, revenue * 0.06) if creative_rows else max(0, revenue * 0.03)
    _create_strategic_analysis(
        snapshot,
        card_key=ControlTowerCardSnapshot.CARD_CREATIVE,
        title_tr="Creative Performans ve Yorgunluk Stratejik Analizi",
        title_en="Creative Performance and Fatigue Strategic Analysis",
        severity="warning" if fatigue_count else "info",
        confidence=84,
        what=(
            f"Octo {len(creative_rows)} kreatif sinyalini değerlendirdi. "
            f"Yorgunluk veya performans riski taşıyan kreatif sayısı {fatigue_count}."
        ),
        why=(
            "Kreatif yorgunluğu yalnızca CTR düşüşüyle anlaşılmaz. ROAS düşüşü CTR düşüşünden daha hızlıysa sorun kreatifin dikkat çekmesi değil, getirdiği trafiğin dönüşüm kalitesi olabilir. "
            "Bu yüzden kreatif performansı kampanya sağlığıyla birlikte okunmalıdır."
        ),
        forecast=(
            f"Yorgun kreatifler yenilenmezse mevcut gelir üzerinde baskı devam edebilir. "
            f"Yeni varyasyon ve video/UGC testleriyle yaklaşık {_money_text(creative_gain)} fırsat üretilebilir."
        ),
        action=(
            "Kazandıran kreatifleri koruyun, yorgun kreatiflere yeni varyasyon hazırlayın. "
            "Rakip baskısı artıyorsa video ve UGC ağırlıklı hızlı test planı oluşturun."
        ),
        impact=f"Beklenen etki: kreatif yenileme ile {_money_text(creative_gain)} potansiyel gelir iyileşmesi.",
        expected_gain=creative_gain,
        expected_loss=0,
        action_type="Kreatif Yenile",
        extra={"fatigue_count": fatigue_count},
    )

    pressure = int(_num(competitor_intel.get("pressure_score"))) if competitor_intel else 0
    top_threat = competitor_intel.get("top_threat") or _top_name(competitor_rows, "ana rakip")
    competitor_gain = max(0, revenue * 0.05) if pressure >= 40 else max(0, revenue * 0.02)
    competitor_loss = max(0, spend * (0.12 if pressure >= 70 else 0.06 if pressure >= 40 else 0.02))
    _create_strategic_analysis(
        snapshot,
        card_key=ControlTowerCardSnapshot.CARD_COMPETITOR,
        title_tr="Rakip İstihbarat ve Pazar Baskısı Stratejik Analizi",
        title_en="Competitor Intelligence and Market Pressure Strategic Analysis",
        severity="critical" if pressure >= 72 else "warning" if pressure >= 45 else "info",
        confidence=90 if pressure >= 45 else 80,
        what=(
            f"Rakip baskı skoru {pressure}/100 seviyesinde. "
            f"Öne çıkan rakip: {top_threat}. "
            f"Octo, yeni reklam yoğunluğu, share of voice ve momentum sinyallerini birlikte değerlendirdi."
        ),
        why=(
            "Rakip baskısı arttığında maliyet artışı çoğu zaman hemen ROAS'a yansımaz; önce CPM/CPC tarafında baskı başlar, sonra CTR ve dönüşüm kalitesine etki eder. "
            "Bu nedenle rakip sinyali sadece gözlem değil, bütçe ve kreatif planlama girdisi olmalıdır."
        ),
        forecast=(
            competitor_intel.get("forecast_tr") or
            f"Bu trend devam ederse önümüzdeki 7-14 günde medya maliyetlerinde baskı oluşabilir. Tahmini korunması gereken risk {_money_text(competitor_loss)}."
        ),
        action=(
            competitor_intel.get("recommendation_tr") or
            "Rakiplerin yoğunlaştığı formatları takip edin, video/UGC testlerini hızlandırın ve remarketing bütçesini koruma altına alın."
        ),
        impact=f"Beklenen etki: {_money_text(competitor_gain)} fırsat, {_money_text(competitor_loss)} rekabet riski azaltımı.",
        expected_gain=competitor_gain,
        expected_loss=competitor_loss,
        action_type="Rakip Hamlesi",
        extra={"pressure_score": pressure, "top_threat": top_threat},
    )

    unhealthy_platforms = len([p for p in platform_rows if str(p.get("status", "")).lower() not in {"ok", "active", "connected", "good", "healthy"}])
    _create_strategic_analysis(
        snapshot,
        card_key=ControlTowerCardSnapshot.CARD_PLATFORM,
        title_tr="Platform ve Veri Güvenilirliği Stratejik Analizi",
        title_en="Platform and Data Reliability Strategic Analysis",
        severity="warning" if unhealthy_platforms else "info",
        confidence=82,
        what=f"Octo {len(platform_rows)} bağlantı/senkron sinyalini kontrol etti. Riskli veya izlenmesi gereken bağlantı sayısı {unhealthy_platforms}.",
        why="Veri bağlantısı zayıflarsa dashboard doğru görünse bile AI önerileri eksik sinyal ile üretilebilir. Bu nedenle veri tazeliği performans kadar kritik bir güven katmanıdır.",
        forecast="Senkron gecikmesi devam ederse snapshot ve AI analizleri eski veriyle karar üretebilir; bu da bütçe kararlarında gecikme veya yanlış pozitif uyarı riski yaratır.",
        action="Senkron hatası veya gecikmesi olan platformları önce düzeltin. AI analizden önce veri tazeliğini doğrulayın.",
        impact="Beklenen etki: daha güvenilir snapshot, daha doğru AI önerisi ve daha düşük yanlış karar riski.",
        expected_gain=0,
        expected_loss=0,
        action_type="Veri Sağlığını Doğrula",
        extra={"unhealthy_platforms": unhealthy_platforms},
    )

    alert_count = len(alerts)
    alert_loss = round(spend * 0.05, 2) if alert_count else 0
    _create_strategic_analysis(
        snapshot,
        card_key=ControlTowerCardSnapshot.CARD_ALERT,
        title_tr="Kritik Uyarı ve Risk Stratejik Analizi",
        title_en="Critical Alerts and Risk Strategic Analysis",
        severity="critical" if alert_count >= 3 else "warning" if alert_count else "info",
        confidence=86,
        what=f"Octo bu dönemde {alert_count} kritik uyarı sinyali gördü. Kritik uyarılar aksiyon değil, riskin nerede oluştuğunu gösteren erken uyarı katmanıdır.",
        why="Bir kampanya hem kritik uyarı hem düşük sağlık skoru üretiyorsa sorun tek metrikte değil, performans zincirinde oluşmuştur. Bu durumda bütçe, kreatif ve hedefleme birlikte ele alınmalıdır.",
        forecast=f"Uyarılar izlenmezse kısa vadeli risk {_money_text(alert_loss)} seviyesine çıkabilir. Uyarı yoksa sistem izleme modunda kalmalıdır.",
        action="Kırmızı uyarıları ilk sıraya alın. Aynı kampanya uyarı ve düşük sağlık skoru üretiyorsa görev merkezindeki aksiyonla eşleştirin.",
        impact=f"Beklenen etki: {_money_text(alert_loss)} potansiyel kaybın erken kontrolü.",
        expected_gain=0,
        expected_loss=alert_loss,
        action_type="Risk Kontrolü",
        extra={"alert_count": alert_count},
    )

    return snapshot


def build_lightweight_snapshot_for_user(user, period="monthly", days=30, agency_client=None):
    today = timezone.localdate()
    date_from = today - timedelta(days=days - 1)
    current = CampaignMetricHistory.objects.filter(campaign__user=user, date__range=(date_from, today))
    previous_from = date_from - timedelta(days=days)
    previous_to = date_from - timedelta(days=1)
    previous = CampaignMetricHistory.objects.filter(campaign__user=user, date__range=(previous_from, previous_to))
    if agency_client:
        current = current.filter(campaign__platform_account__agency_client=agency_client)
        previous = previous.filter(campaign__platform_account__agency_client=agency_client)

    totals = aggregate_metric_queryset(current)
    prev = aggregate_metric_queryset(previous)

    spend = _num(totals.get("spend"))
    revenue = _num(totals.get("conversion_value"))
    clicks = _num(totals.get("clicks"))
    conversions = _num(totals.get("conversions"))
    roas = _num(totals.get("roas"))
    ctr = _num(totals.get("ctr"))
    cpc = _num(totals.get("cpc"))
    conversion_rate = _num(totals.get("conversion_rate"))
    octo_score = int(max(0, min(100, (roas * 18) + (ctr * 5) + (conversion_rate * 3))))

    context = {
        "summary": {
            "total_spend": spend,
            "total_revenue": revenue,
            "total_clicks": clicks,
            "total_impressions": _num(totals.get("impressions")),
            "total_conversions": conversions,
            "avg_roas": round(roas, 2),
            "avg_ctr": round(ctr, 2),
            "avg_cpc": round(cpc, 2),
            "conversion_rate": round(conversion_rate, 2),
            "octo_score": octo_score,
            "roas_delta": _pct_change(roas, prev.get("roas")),
            "ctr_delta": _pct_change(ctr, prev.get("ctr")),
            "cpc_delta": _pct_change(cpc, prev.get("cpc")),
        },
        "campaign_health": [],
        "critical_alerts": [],
        "ai_task_stats": {},
        "competitor_rows": [],
        "creative_wall": [],
        "platform_status_cards": [],
        "ai_recommendations": [],
    }
    return save_snapshot_from_context(user, period, date_from, today, context, agency_client=agency_client)
