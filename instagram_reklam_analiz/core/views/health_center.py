from datetime import date, timedelta
from decimal import Decimal
import json
import re

from django.apps import apps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Max, Q, Sum
from django.shortcuts import render
from django.utils import timezone

from core.models import (
    FeatureUsageLedger,
    HealthCenterAIAnalysis,
    OctoRuleEngineRun,
    OctoTaskInstance,
    OctoTaskRule,
)
from core.services.cache_service import CacheService
from core.services.agency_scope import get_agency_scope, platform_accounts_for_request, scope_queryset
from core.services.openai_usage import consume_openai_operation, record_openai_token_usage, refund_ai_tariff_credits
from core.services.ai_agent_ecosystem import run_sixteen_agent_orchestration
from core.utils.metric_text import format_metric_text_tr
from core.tasks.admin_ops import generate_octo_tasks


HEALTH_CENTER_CACHE_TIMEOUT = 180


def _sentence_list(value, limit=8):
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    if not cleaned:
        return []
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
    return (parts or [cleaned])[:limit]


def _normalize_text_key(value):
    return re.sub(
        r"[^\w]+",
        " ",
        format_metric_text_tr(value),
        flags=re.UNICODE,
    ).strip().casefold()


def _unique_texts(values, limit=12):
    result = []
    seen = set()
    for value in values:
        text = format_metric_text_tr(value)
        key = _normalize_text_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _attach_rule_findings(ad_rows):
    """Attach persisted rule-engine matches in one query, without per-ad queries."""
    active_rule_count = OctoTaskRule.objects.filter(is_active=True).count()
    if not ad_rows:
        return active_rule_count, 0

    ad_ids = [row["id"] for row in ad_rows]
    campaign_ids = {row["campaign_id"] for row in ad_rows if row.get("campaign_id")}
    ad_group_ids = {row["ad_group_id"] for row in ad_rows if row.get("ad_group_id")}
    account_ids = {row["platform_account_id"] for row in ad_rows if row.get("platform_account_id")}
    matches = list(
        OctoTaskInstance.objects.filter(
            Q(ad_id__in=ad_ids)
            | Q(ad_group_id__in=ad_group_ids)
            | Q(campaign_id__in=campaign_ids)
            | Q(platform_account_id__in=account_ids),
            status__in=["open", "viewed", "snoozed"],
        )
        .select_related("rule")
        .order_by("-priority_score", "-last_detected_at")
    )

    by_ad, by_ad_group, by_campaign, by_account = {}, {}, {}, {}
    for match in matches:
        if match.ad_id:
            by_ad.setdefault(match.ad_id, []).append(match)
        elif match.ad_group_id:
            by_ad_group.setdefault(match.ad_group_id, []).append(match)
        elif match.campaign_id:
            by_campaign.setdefault(match.campaign_id, []).append(match)
        elif match.platform_account_id:
            by_account.setdefault(match.platform_account_id, []).append(match)

    unique_matches = set()
    for row in ad_rows:
        candidates = (
            by_ad.get(row["id"], [])
            + by_ad_group.get(row.get("ad_group_id"), [])
            + by_campaign.get(row.get("campaign_id"), [])
            + by_account.get(row.get("platform_account_id"), [])
        )
        winners = {}
        for match in {item.id: item for item in candidates}.values():
            if match.ad_id == row["id"]:
                scope_rank = 0
            elif match.ad_group_id and match.ad_group_id == row.get("ad_group_id"):
                scope_rank = 1
            elif match.campaign_id and match.campaign_id == row.get("campaign_id"):
                scope_rank = 2
            else:
                scope_rank = 3
            semantic_key = match.rule.code if match.rule else f"{match.module}:{(match.title_tr or '').strip().casefold()}"
            detected_at = match.last_detected_at or match.created_at
            candidate_key = (scope_rank, -detected_at.timestamp(), -match.priority_score)
            current = winners.get(semantic_key)
            if current is None or candidate_key < current[0]:
                winners[semantic_key] = (candidate_key, match)

        row_matches = [item[1] for item in winners.values()]
        row_matches.sort(
            key=lambda match: (match.priority_score, match.last_detected_at or match.created_at),
            reverse=True,
        )
        row_matches = row_matches[:8]
        unique_matches.update(
            (
                match.ad_id,
                match.ad_group_id,
                match.campaign_id,
                match.platform_account_id,
                match.rule.code if match.rule else f"{match.module}:{match.title_tr}",
            )
            for match in row_matches
        )

        detection_points = list(row["reason_points"])
        risk_points = list(row["risk_points"])
        action_points = list(row["action_points"])
        prompt_findings = []
        for match in row_matches:
            title = format_metric_text_tr((match.title_tr or "").strip())
            findings = ([title] if title else []) + _sentence_list(format_metric_text_tr(match.message_tr))
            prompt_findings.extend(findings)
            if match.severity in {"critical", "warning"}:
                risk_points.extend(findings)
            else:
                detection_points.extend(findings)
            action_points.extend(_sentence_list(format_metric_text_tr(match.action_text_tr)))

        row["rule_match_count"] = len(row_matches)
        row["rule_findings"] = _unique_texts(prompt_findings, limit=6)
        row["reason_points"] = _unique_texts(detection_points)
        row["risk_points"] = _unique_texts(risk_points)
        row["action_points"] = _unique_texts(action_points)

    return active_rule_count, len(unique_matches)


def _ensure_rule_scans(ad_rows, days):
    """Queue stale rule scans once per data owner and expose a compact UI state."""
    user_ids = sorted({row["owner_user_id"] for row in ad_rows if row.get("owner_user_id")})
    if not user_ids:
        return {"status": "idle", "queued": False, "last_run_at": None, "error": ""}

    latest_by_user = {}
    for run in OctoRuleEngineRun.objects.filter(user_id__in=user_ids).order_by("user_id", "-started_at"):
        latest_by_user.setdefault(run.user_id, run)

    stale_before = timezone.now() - timedelta(minutes=15)
    queued = False
    running = False
    pending = False
    errors = []
    latest_times = []
    for user_id in user_ids:
        run = latest_by_user.get(user_id)
        if run:
            latest_times.append(run.started_at)
            if run.status == "running":
                running = True
                continue
        needs_scan = run is None or run.status == "failed" or run.started_at < stale_before
        guard_parts = ("user", user_id)
        if needs_scan and not CacheService.get("health_center_rule_scan", *guard_parts):
            try:
                generate_octo_tasks.apply_async(
                    kwargs={"user_id": user_id, "trigger": "manual", "days": min(days, 30)},
                    queue="ai",
                )
                CacheService.set("health_center_rule_scan", *guard_parts, value=True, timeout=90)
                queued = True
            except Exception as exc:
                errors.append(str(exc))
        elif needs_scan:
            pending = True

    status = "queued" if queued else "running" if running else "pending" if pending else "completed"
    return {
        "status": status,
        "queued": queued,
        "last_run_at": max(latest_times) if latest_times else None,
        "error": " ".join(errors),
    }


def _model(name):
    try:
        return apps.get_model("core", name)
    except LookupError:
        return None


def _num(value):
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_div(a, b):
    a = _num(a)
    b = _num(b)
    return a / b if b else 0.0


def _fmt_tr_decimal(value, decimals=2):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    text = f"{number:,.{decimals}f}"
    return text.replace(",", "TMP").replace(".", ",").replace("TMP", ".")


def _score_high_good(value, target):
    value = _num(value)
    target = _num(target)
    if target <= 0:
        return 0
    return int(max(0, min(96, (value / target) * 82 + 10)))


def _score_low_good(value, good, bad):
    value = _num(value)
    good = _num(good)
    bad = _num(bad)
    if value <= 0:
        return 0
    if value <= good:
        return 94
    if value >= bad:
        return 15
    return int(100 - ((value - good) / (bad - good)) * 85)


def _score_frequency(freq):
    freq = _num(freq)
    if freq <= 0:
        return 0
    if 1.15 <= freq <= 3.25:
        return 94
    if 3.25 < freq <= 4.5:
        return 78
    if 4.5 < freq <= 6:
        return 52
    if freq > 6:
        return 25
    return 72


def _status(score, has_data=True):
    if not has_data:
        return "Veri Bekliyor"
    if score >= 80:
        return "Sağlıklı"
    if score >= 60:
        return "İzlenmeli"
    if score >= 40:
        return "Riskli"
    return "Kritik"


def _delta(current, previous):
    current = _num(current)
    previous = _num(previous)
    if previous == 0:
        return 0.0
    return ((current - previous) / previous) * 100


def _totals_from_dict(data):
    impressions = _num(data.get("impressions"))
    reach = _num(data.get("reach"))
    clicks = _num(data.get("clicks"))
    spend = _num(data.get("spend"))
    conversions = _num(data.get("conversions"))
    conversion_value = _num(data.get("conversion_value"))
    engagement = _num(data.get("engagement")) or (
        _num(data.get("likes")) + _num(data.get("comments")) + _num(data.get("shares")) + _num(data.get("saves"))
    )
    frequency = _num(data.get("avg_frequency")) or _safe_div(impressions, reach)
    return {
        "impressions": impressions,
        "reach": reach,
        "clicks": clicks,
        "spend": spend,
        "conversions": conversions,
        "conversion_value": conversion_value,
        "engagement": engagement,
        "ctr": _safe_div(clicks, impressions) * 100,
        "cpc": _safe_div(spend, clicks),
        "cpm": _safe_div(spend, impressions) * 1000,
        "cpa": _safe_div(spend, conversions),
        "roas": _safe_div(conversion_value, spend),
        "conversion_rate": _safe_div(conversions, clicks) * 100,
        "engagement_rate": _safe_div(engagement, impressions) * 100,
        "frequency": frequency,
    }


def _metric_totals(qs):
    data = qs.aggregate(
        impressions=Sum("impressions"),
        reach=Sum("reach"),
        clicks=Sum("clicks"),
        spend=Sum("spend"),
        conversions=Sum("conversions"),
        conversion_value=Sum("conversion_value"),
        likes=Sum("likes"),
        comments=Sum("comments"),
        shares=Sum("shares"),
        saves=Sum("saves"),
        engagement=Sum("engagement"),
        avg_frequency=Avg("frequency"),
    )
    return _totals_from_dict(data)


def _health_score(totals):
    parts = {
        "ctr": _score_high_good(totals["ctr"], 2.5),
        "cpc": _score_low_good(totals["cpc"], 6, 25),
        "cpa": _score_low_good(totals["cpa"], 75, 300),
        "roas": _score_high_good(totals["roas"], 3),
        "frequency": _score_frequency(totals["frequency"]),
        "engagement": _score_high_good(totals["engagement_rate"], 4),
        "conversion": _score_high_good(totals["conversion_rate"], 3),
    }
    weights = {"ctr": 15, "cpc": 12, "cpa": 18, "roas": 22, "frequency": 10, "engagement": 10, "conversion": 13}
    score = sum(parts[k] * weights[k] for k in parts) / sum(weights.values())
    return int(max(0, min(96, round(score)))), parts


def _explain_ad(totals, parts, score, has_data):
    strengths = []
    risks = []
    actions = []

    if not has_data:
        return {
            "reason": "Bu reklam aktif görünüyor ancak seçilen tarih aralığında metrik geçmişi yok. Bu yüzden performans sağlığı net ölçülemedi.",
            "risk_reason": "Veri olmadığı için reklamın para kazandırıp kazandırmadığı, tıklama isteği ve yorgunluk seviyesi görülemiyor.",
            "action": "Önce ilgili platform hesabından metrik senkronizasyonunu çalıştır; ardından aynı tarih filtresiyle tekrar analiz et.",
        }

    if parts["roas"] >= 75:
        strengths.append(f"ROAS {_fmt_tr_decimal(totals['roas'])}x; harcamaya göre dönüşüm değeri güçlü.")
    elif parts["roas"] < 55:
        risks.append(f"ROAS {_fmt_tr_decimal(totals['roas'])}x; reklam harcamayı yeterince geri döndürmüyor.")
        actions.append("Bütçeyi artırma; önce teklif, hedef kitle ve açılış sayfası uyumunu kontrol et.")

    if parts["ctr"] >= 70:
        strengths.append(f"CTR %{_fmt_tr_decimal(totals['ctr'])}; kreatif ve mesaj kullanıcıda tıklama isteği oluşturuyor.")
    elif parts["ctr"] < 55:
        risks.append(f"CTR %{_fmt_tr_decimal(totals['ctr'])}; reklam ilgi çekmekte zorlanıyor.")
        actions.append("İlk cümleyi, görsel/video hook'unu ve CTA mesajını daha net hale getir.")

    if parts["cpa"] >= 70 and totals["conversions"] > 0:
        strengths.append(f"CPA {_fmt_tr_decimal(totals['cpa'])} TL; sonuç maliyeti kabul edilebilir seviyede.")
    elif parts["cpa"] < 55:
        risks.append(f"CPA {_fmt_tr_decimal(totals['cpa'])} TL; müşteri kazanım maliyeti yüksek.")
        actions.append("Düşük dönüşümlü reklam gruplarını azalt, yüksek dönüşüm getiren kitlelere bütçe kaydır.")

    if totals["frequency"] > 4.5:
        risks.append(f"Frekans {_fmt_tr_decimal(totals['frequency'])}; aynı kişiler reklamı fazla görüyor, reklam yorgunluğu başlayabilir.")
        actions.append("Yeni kreatif varyasyonları ekle veya hedef kitleyi genişlet/yenile.")
    elif parts["frequency"] >= 75:
        strengths.append(f"Frekans {_fmt_tr_decimal(totals['frequency'])}; tekrar gösterim seviyesi sağlıklı aralıkta.")

    if parts["conversion"] >= 70:
        strengths.append(f"Dönüşüm oranı %{_fmt_tr_decimal(totals['conversion_rate'])}; tıklayan kullanıcıların önemli kısmı sonuç üretiyor.")
    elif parts["conversion"] < 50 and totals["clicks"] > 0:
        risks.append(f"Dönüşüm oranı %{_fmt_tr_decimal(totals['conversion_rate'])}; tıklama var ama sonuç zayıf.")
        actions.append("Landing page, teklif, fiyat, form/checkout adımlarını kontrol et.")

    if parts["engagement"] >= 70:
        strengths.append(f"Etkileşim oranı %{_fmt_tr_decimal(totals['engagement_rate'])}; reklam sosyal sinyal alıyor.")
    elif parts["engagement"] < 50:
        risks.append(f"Etkileşim oranı %{_fmt_tr_decimal(totals['engagement_rate'])}; yorum, kaydetme ve paylaşım zayıf.")
        actions.append("Sosyal kanıt, fayda odaklı metin ve karşılaştırmalı kreatif test et.")

    if not strengths and score >= 60:
        strengths.append("Metrikler genel olarak dengeli; reklam izlenmeye devam edebilir.")
    if not risks and score >= 80:
        risks.append("Belirgin kritik risk görünmüyor; yine de frekans ve CPA günlük takip edilmeli.")
    if not actions:
        actions.append("Bütçe, frekans, CPA ve dönüşüm kalitesi aynı ekranda izlenerek kontrollü karar verilmeli.")

    return {
        "reason": " ".join(strengths[:3]),
        "risk_reason": " ".join(risks[:3]),
        "action": " ".join(actions[:3]),
    }


def _global_recommendations(totals, parts, active_count, measured_count):
    recs = []
    if measured_count < active_count:
        recs.append({"level": "warning", "title": "Bazı aktif reklamlarda metrik yok", "text": f"{active_count} aktif reklamın {measured_count} tanesinde seçilen dönemde metrik bulundu. Eksik olanlar için platform senkronizasyonunu kontrol et."})
    if parts["roas"] < 60:
        recs.append({"level": "critical", "title": "ROAS baskısı", "text": "Dönüşüm değeri harcamayı yeterince karşılamıyor. ROAS yüksek reklamları ölçekle, düşük ROAS reklamları revize et."})
    if parts["cpa"] < 60:
        recs.append({"level": "critical", "title": "CPA yükseliyor", "text": "Sonuç maliyeti yüksek. Kampanya amacı, teklif stratejisi ve hedef kitle kırılımlarını yeniden kontrol et."})
    if parts["ctr"] < 60:
        recs.append({"level": "warning", "title": "Kreatif ilgi zayıf", "text": "CTR hedefin altında. İlk 3 saniye/hook, başlık, görsel kontrast ve CTA daha net olmalı."})
    if totals["frequency"] > 4.5:
        recs.append({"level": "warning", "title": "Reklam yorgunluğu riski", "text": "Frekans yükselmiş. Aynı reklamı döndürmek yerine yeni kreatif ve yeni kitle varyasyonları aç."})
    if not recs:
        recs.append({"level": "success", "title": "Genel sağlık iyi", "text": "Aktif reklamlar genel olarak dengeli. En yüksek skorlu reklamları kontrollü ölçekleyip yeni varyasyonlarla testi büyütebilirsin."})
    return recs[:6]


HEALTH_AI_AGENTS = [
    "Veri Bütünlüğü Ajanı",
    "Hesap Sağlığı Ajanı",
    "ROAS ve Gelir Ajanı",
    "CTR ve Mesaj İlgisi Ajanı",
    "CPA ve Maliyet Ajanı",
    "Frekans ve Yorgunluk Ajanı",
    "Dönüşüm Kalitesi Ajanı",
    "Etkileşim Sinyali Ajanı",
    "Platform Kıyas Ajanı",
    "Bütçe Verimliliği Ajanı",
    "Trend ve Momentum Ajanı",
    "Risk Erken Uyarı Ajanı",
    "Kreatif Performans Ajanı",
    "Kampanya Yapısı Ajanı",
    "Hesap Segment Ajanı",
    "Yönetici Özet Ajanı",
]


def _fallback_ai_result(totals, score, recommendations, account_label, reason=""):
    severity = "success" if score >= 80 else "watch" if score >= 60 else "risk"
    agents = [{
            "name": "Yerel Sağlık Motoru",
            "severity": severity,
            "finding": (
                f"{account_label} kapsamında skor {score}/100; "
                f"CTR %{_fmt_tr_decimal(totals['ctr'])}, ROAS {_fmt_tr_decimal(totals['roas'])}x, CPA {_fmt_tr_decimal(totals['cpa'])} TL."
            ),
        }]
    return {
        "source": "local",
        "error": reason,
        "headline": "Derin analiz yanıtı alınamadı; ekran yerel metrik analiziyle güncellendi.",
        "summary": " ".join([r.get("text", "") for r in recommendations[:2]]) or "Metrikler yerel sağlık motoru ile yorumlandı.",
        "agents": agents,
        "decision_notes": recommendations[:4],
    }


def _latest_analysis_context(*, user, days, platform_code, account_id, status_filter):
    latest = (
        HealthCenterAIAnalysis.objects
        .filter(
            user=user,
            days=days,
            platform_code=platform_code or "",
            account_id=str(account_id or ""),
            status_filter=status_filter or "ACTIVE",
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if not latest:
        return {
            "last_health_analysis_at": None,
            "last_health_analysis_source": "",
            "saved_ai_result": None,
        }
    return {
        "last_health_analysis_at": latest.created_at,
        "last_health_analysis_source": latest.source,
        "saved_ai_result": {
            "source": latest.source,
            "error": latest.error,
            "headline": latest.headline,
            "summary": latest.summary,
            "agents": latest.agents_payload or [],
            "decision_notes": latest.decision_notes or [],
        },
    }


def _save_health_ai_analysis(*, user, ai_result, ai_error, totals, score, score_delta, active_count, measured_count, days, platform_code, platform_label, account_id, account_label, status_filter):
    return HealthCenterAIAnalysis.objects.create(
        user=user,
        platform_code=platform_code or "",
        platform_label=platform_label or "",
        account_id=str(account_id or ""),
        account_label=account_label or "",
        days=days,
        status_filter=status_filter or "ACTIVE",
        score=score,
        score_delta=score_delta,
        active_count=active_count,
        measured_count=measured_count,
        source=(ai_result or {}).get("source", "local"),
        headline=(ai_result or {}).get("headline", "")[:255],
        summary=(ai_result or {}).get("summary", ""),
        error=ai_error or (ai_result or {}).get("error", ""),
        agents_payload=(ai_result or {}).get("agents", []) or [],
        decision_notes=(ai_result or {}).get("decision_notes", []) or [],
        metrics_payload={
            "impressions": round(totals["impressions"], 2),
            "clicks": round(totals["clicks"], 2),
            "spend_tl": round(totals["spend"], 2),
            "conversions": round(totals["conversions"], 2),
            "conversion_value_tl": round(totals["conversion_value"], 2),
            "ctr_percent": round(totals["ctr"], 2),
            "cpc_tl": round(totals["cpc"], 2),
            "cpa_tl": round(totals["cpa"], 2),
            "roas": round(totals["roas"], 2),
            "frequency": round(totals["frequency"], 2),
            "conversion_rate_percent": round(totals["conversion_rate"], 2),
            "engagement_rate_percent": round(totals["engagement_rate"], 2),
        },
        raw_payload=ai_result or {},
    )


def _compact_health_ai_context(
    *, totals, score, score_delta, active_count, measured_count, ad_rows,
    days, account_label, platform_label, active_rule_count, matched_rule_count,
):
    """Build a bounded account context without repeating every ad's long texts."""
    campaign_map = {}
    for row in ad_rows:
        key = row.get("campaign_id") or f"name:{row.get('campaign') or '-'}"
        campaign = campaign_map.setdefault(key, {
            "campaign": row.get("campaign") or "Kampanya yok",
            "platform": row.get("platform") or "-",
            "ads": 0,
            "measured_ads": 0,
            "score_sum": 0,
            "impressions": 0.0,
            "clicks": 0.0,
            "spend_tl": 0.0,
            "conversions": 0.0,
            "conversion_value_tl": 0.0,
            "rule_findings": [],
        })
        campaign["ads"] += 1
        if row.get("has_data"):
            campaign["measured_ads"] += 1
            campaign["score_sum"] += int(row.get("score") or 0)
        for field in ("impressions", "clicks", "spend", "conversions", "conversion_value"):
            target = {
                "spend": "spend_tl",
                "conversion_value": "conversion_value_tl",
            }.get(field, field)
            campaign[target] += float(row.get(field) or 0)
        campaign["rule_findings"].extend(row.get("rule_findings") or [])

    campaigns = []
    for campaign in campaign_map.values():
        spend = campaign.pop("spend_tl")
        conversion_value = campaign.pop("conversion_value_tl")
        impressions = campaign.pop("impressions")
        clicks = campaign.pop("clicks")
        conversions = campaign.pop("conversions")
        score_sum = campaign.pop("score_sum")
        measured = campaign["measured_ads"]
        campaigns.append({
            **campaign,
            "score": round(score_sum / measured) if measured else 0,
            "impressions": round(impressions),
            "spend_tl": round(spend, 2),
            "conversions": round(conversions, 2),
            "ctr_percent": round(_safe_div(clicks, impressions) * 100, 2),
            "cpa_tl": round(_safe_div(spend, conversions), 2),
            "roas": round(_safe_div(conversion_value, spend), 2),
            "rule_findings": _unique_texts(campaign["rule_findings"], limit=3),
        })
    campaigns.sort(key=lambda row: (row["score"], -row["spend_tl"], row["campaign"]))

    # Normal hesaplarda kampanyaların tamamını tek tek gönder. Çok büyük
    # hesaplarda giriş bütçesini korumak için yalnızca 80 sonrası toplulaştırılır.
    detailed_campaigns = campaigns[:80]
    overflow_campaigns = campaigns[80:]
    overflow_summary = None
    if overflow_campaigns:
        overflow_summary = {
            "campaign_count": len(overflow_campaigns),
            "ads": sum(row["ads"] for row in overflow_campaigns),
            "measured_ads": sum(row["measured_ads"] for row in overflow_campaigns),
            "spend_tl": round(sum(row["spend_tl"] for row in overflow_campaigns), 2),
            "conversions": round(sum(row["conversions"] for row in overflow_campaigns), 2),
            "note": "Token tasarrufu için kalan kampanyalar toplu hesap özetiyle temsil edildi.",
        }

    risky_ads = sorted(
        ad_rows,
        key=lambda row: (row["score"], -row["spend"], row["name"]),
    )[:8]
    return {
        "data_scope": "all_filtered_campaigns",
        "scope": {
            "account": account_label,
            "platform": platform_label,
            "days": days,
            "active_ads": active_count,
            "measured_ads": measured_count,
            "campaign_count": len(campaigns),
            "score": score,
            "score_delta": score_delta,
            "active_rule_count": active_rule_count,
            "matched_rule_count": matched_rule_count,
        },
        "totals": {
            "impressions": round(totals["impressions"], 2),
            "clicks": round(totals["clicks"], 2),
            "spend_tl": round(totals["spend"], 2),
            "conversions": round(totals["conversions"], 2),
            "conversion_value_tl": round(totals["conversion_value"], 2),
            "ctr_percent": round(totals["ctr"], 2),
            "cpc_tl": round(totals["cpc"], 2),
            "cpa_tl": round(totals["cpa"], 2),
            "roas": round(totals["roas"], 2),
            "frequency": round(totals["frequency"], 2),
        },
        "campaigns": detailed_campaigns,
        "remaining_campaigns_summary": overflow_summary,
        "riskiest_ads": [{
            "name": row["name"],
            "campaign": row["campaign"],
            "score": row["score"],
            "spend_tl": round(row["spend"], 2),
            "conversions": round(row["conversions"], 2),
            "ctr_percent": round(row["ctr"], 2),
            "cpa_tl": round(row["cpa"], 2),
            "roas": round(row["roas"], 2),
            "rule_findings": _unique_texts(row.get("rule_findings") or [], limit=3),
        } for row in risky_ads],
    }


def _build_health_ai_payload(
    *, user, totals, score, score_delta, active_count, measured_count, ad_rows,
    days, account_label, platform_label, active_rule_count, matched_rule_count, organization=None
):
    api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
    if not api_key:
        return None, "OPENAI_API_KEY tanımlı değil."

    guard = consume_openai_operation(
        user=user,
        organization=organization,
        operation=FeatureUsageLedger.OP_OPENAI_ANALYSIS,
        credit_amount=5,
        tariff_key="health-center-deep-analysis",
        reference="health_center.deep_account_analysis",
        reason="Reklam Sağlık Merkezi hesap analizi",
        metadata={"days": days, "account": account_label, "platform": platform_label},
    )
    if not guard.allowed:
        return None, guard.reason

    prompt = _compact_health_ai_context(
        totals=totals,
        score=score,
        score_delta=score_delta,
        active_count=active_count,
        measured_count=measured_count,
        ad_rows=ad_rows,
        days=days,
        account_label=account_label,
        platform_label=platform_label,
        active_rule_count=active_rule_count,
        matched_rule_count=matched_rule_count,
    )
    try:
        from openai import OpenAI
    except Exception as exc:
        return None, f"Analiz paketi yüklenemedi: {exc}"

    try:
        parsed = run_sixteen_agent_orchestration(
            client=OpenAI(api_key=api_key, timeout=60, max_retries=2),
            model=getattr(settings, "OPENAI_MODEL", "gpt-4o"),
            task=(
                "Filtre kapsamindaki tum kampanyalarin guncel veritabani metriklerini ve "
                "kural motoru eslesmelerini topluca analiz et. Yalnizca verilen veriyi kullan; "
                "ayni tespit veya oneriyi tekrarlama. Kampanyalar arasi en onemli riskleri, "
                "firsatlari ve olculebilir aksiyonlari kisa yaz. Degisiklik uygulama."
            ),
            context=prompt,
            modalities=["text"],
            reference="health_center.deep_account_analysis",
            user=user,
            organization=organization,
            max_workers=4,
            max_tokens_per_agent=160,
            tariff_key="health-center-deep-analysis",
        )
        agents = parsed.get("agents") or []
        parsed["headline"] = "Octo AI hesap analizini tamamladı."
        findings = _unique_texts(
            [row.get("finding", "") for row in agents if row.get("finding")],
            limit=4,
        )
        recommendations = _unique_texts(
            [row.get("recommendation", "") for row in agents if row.get("recommendation")],
            limit=6,
        )
        parsed["summary"] = " ".join(findings[:3]) or "AI analizi tamamlandı."
        parsed["decision_notes"] = [
            {
                "level": "info",
                "title": "Önerilen aksiyon",
                "points": [recommendation],
            }
            for recommendation in recommendations[:4]
        ]
        parsed["source"] = "openai"
        return parsed, ""
    except Exception as exc:
        refund_ai_tariff_credits(
            user=user, organization=organization, tariff_key="health-center-deep-analysis", reason=str(exc),
            reference="health_center.deep_account_analysis",
        )
        return None, str(exc)


@login_required
def health_center(request):
    AdMetricHistory = _model("AdMetricHistory")
    Ad = _model("Ad")
    Platform = _model("Platform")
    PlatformAccount = _model("PlatformAccount")

    today = date.today()  # timezone.localdate/localtime yok; naive datetime hatası üretmez.
    try:
        days = int(request.GET.get("gun", 30) or 30)
    except ValueError:
        days = 30
    if days not in [1, 3, 7, 14, 30, 60, 90, 180]:
        days = 30
    start = today - timedelta(days=days - 1)
    prev_start = start - timedelta(days=days)
    prev_end = start - timedelta(days=1)

    platform_code = request.GET.get("platform", "").strip()
    account_id = request.GET.get("hesap", "").strip()
    status_filter = request.GET.get("durum", "ACTIVE").strip().upper() or "ACTIVE"
    order = request.GET.get("sirala", "date_desc").strip()
    run_ai = request.GET.get("ai") == "1"
    agency_scope = get_agency_scope(request)
    analysis_account_id = account_id or (
        f"agency:{agency_scope.selected_client.id}" if agency_scope.selected_client else ""
    )
    version = CacheService.get_version("health_center", request.user.id)
    cache_key_parts = (
        "scorev9-rules",
        "user",
        request.user.id,
        "agency_client",
        agency_scope.cache_key,
        "gun",
        days,
        "platform",
        platform_code or "all",
        "hesap",
        account_id or "all",
        "durum",
        status_filter,
        "sirala",
        order,
    )
    cached_context = CacheService.get("health_center", *cache_key_parts, version=version)
    if cached_context is not None and not run_ai:
        cached_context = dict(cached_context)
        cached_context["agency_scope"] = agency_scope
        latest_cached_analysis = _latest_analysis_context(
            user=request.user,
            days=days,
            platform_code=platform_code,
            account_id=analysis_account_id,
            status_filter=status_filter,
        )
        cached_context.update(latest_cached_analysis)
        if latest_cached_analysis.get("saved_ai_result"):
            cached_context["ai_result"] = latest_cached_analysis["saved_ai_result"]
        return render(request, "reports/health_center.html", cached_context)

    if not AdMetricHistory or not Ad:
        return render(request, "reports/health_center.html", {"empty": True})

    metric_base = scope_queryset(
        request,
        AdMetricHistory.objects.filter(ad__source_type="OWN"),
        account_lookup="ad__platform_account",
        user_lookup="ad__user",
    )
    ad_qs = scope_queryset(request, Ad.objects.filter(source_type="OWN")).select_related(
        "platform_account", "platform_account__platform", "campaign", "ad_group", "creative"
    )

    if status_filter == "ACTIVE":
        ad_qs = ad_qs.filter(Q(status__iexact="ACTIVE") | Q(is_active=True))
        metric_base = metric_base.filter(Q(ad__status__iexact="ACTIVE") | Q(ad__is_active=True))
    elif status_filter != "ALL":
        ad_qs = ad_qs.filter(status__iexact=status_filter)
        metric_base = metric_base.filter(ad__status__iexact=status_filter)

    if platform_code:
        ad_qs = ad_qs.filter(platform_account__platform__code=platform_code)
        metric_base = metric_base.filter(ad__platform_account__platform__code=platform_code)
    if account_id:
        ad_qs = ad_qs.filter(platform_account_id=account_id)
        metric_base = metric_base.filter(ad__platform_account_id=account_id)

    current_metric_qs = metric_base.filter(date__gte=start, date__lte=today)
    previous_metric_qs = metric_base.filter(date__gte=prev_start, date__lte=prev_end)

    totals = _metric_totals(current_metric_qs)
    prev_totals = _metric_totals(previous_metric_qs)
    score, parts = _health_score(totals)
    prev_score, _ = _health_score(prev_totals)

    active_count = ad_qs.count()

    period_filter = Q(metric_history__date__gte=start, metric_history__date__lte=today)
    ads_annotated = ad_qs.annotate(
        m_impressions=Sum("metric_history__impressions", filter=period_filter),
        m_reach=Sum("metric_history__reach", filter=period_filter),
        m_clicks=Sum("metric_history__clicks", filter=period_filter),
        m_spend=Sum("metric_history__spend", filter=period_filter),
        m_conversions=Sum("metric_history__conversions", filter=period_filter),
        m_conversion_value=Sum("metric_history__conversion_value", filter=period_filter),
        m_likes=Sum("metric_history__likes", filter=period_filter),
        m_comments=Sum("metric_history__comments", filter=period_filter),
        m_shares=Sum("metric_history__shares", filter=period_filter),
        m_saves=Sum("metric_history__saves", filter=period_filter),
        m_engagement=Sum("metric_history__engagement", filter=period_filter),
        m_frequency=Avg("metric_history__frequency", filter=period_filter),
        last_metric_date=Max("metric_history__date", filter=period_filter),
    )

    ad_rows = []
    for ad in ads_annotated:
        t = _totals_from_dict({
            "impressions": ad.m_impressions,
            "reach": ad.m_reach,
            "clicks": ad.m_clicks,
            "spend": ad.m_spend,
            "conversions": ad.m_conversions,
            "conversion_value": ad.m_conversion_value,
            "likes": ad.m_likes,
            "comments": ad.m_comments,
            "shares": ad.m_shares,
            "saves": ad.m_saves,
            "engagement": ad.m_engagement,
            "avg_frequency": ad.m_frequency,
        })
        has_data = t["impressions"] > 0 or t["spend"] > 0 or t["clicks"] > 0
        ad_score, ad_parts = _health_score(t) if has_data else (0, {"ctr": 0, "cpc": 0, "cpa": 0, "roas": 0, "frequency": 0, "engagement": 0, "conversion": 0})
        explanation = _explain_ad(t, ad_parts, ad_score, has_data)
        ad_rows.append({
            "id": ad.id,
            "owner_user_id": ad.user_id,
            "platform_account_id": ad.platform_account_id,
            "campaign_id": ad.campaign_id,
            "ad_group_id": ad.ad_group_id,
            "name": ad.name or ad.headline or f"Reklam #{ad.id}",
            "status": ad.status or "UNKNOWN",
            "platform": ad.platform_account.platform.name if ad.platform_account and ad.platform_account.platform else "Platform yok",
            "account": ad.platform_account.account_name or ad.platform_account.account_id if ad.platform_account else "Hesap yok",
            "campaign": ad.campaign.name if ad.campaign else "Kampanya yok",
            "ad_group": ad.ad_group.name if ad.ad_group else "Reklam grubu yok",
            "creative_type": ad.creative.creative_type if ad.creative else "UNKNOWN",
            "last_metric_date": ad.last_metric_date,
            "score": ad_score,
            "parts": ad_parts,
            "status_text": _status(ad_score, has_data),
            "has_data": has_data,
            "reason_points": _sentence_list(explanation.get("reason")),
            "risk_points": _sentence_list(explanation.get("risk_reason")),
            "action_points": _sentence_list(explanation.get("action")),
            **t,
            **explanation,
        })

    active_rule_count, matched_rule_count = _attach_rule_findings(ad_rows)
    rule_engine = _ensure_rule_scans(ad_rows, days)

    if order == "score_asc":
        ad_rows.sort(key=lambda item: (item["score"], item["name"]))
    elif order == "score_desc":
        ad_rows.sort(key=lambda item: (-item["score"], item["name"]))
    elif order == "spend_desc":
        ad_rows.sort(key=lambda item: (-item["spend"], item["name"]))
    else:
        ad_rows.sort(key=lambda x: (x["last_metric_date"] is None, x["last_metric_date"] or date.min), reverse=True)

    measured_count = sum(1 for a in ad_rows if a["has_data"])
    has_health_data = active_count > 0 and measured_count > 0
    healthy_ads = [a for a in ad_rows if a["score"] >= 60 and a["has_data"]]
    sorted_ads = sorted(
    ad_rows,
    key=lambda item: (item["score"], item["name"])
)

    risky_ads = [
    ad for ad in sorted_ads
    if ad["score"] < 60 or not ad["has_data"]
]
    kpis = [
        {"label": "Aktif Reklam", "value": active_count, "suffix": "", "delta": 0, "score": 96 if active_count else 0, "hint": "Filtreye uyan reklam"},
        {"label": "Metrikli Reklam", "value": measured_count, "suffix": "", "delta": 0, "score": min(96, int(_safe_div(measured_count, active_count) * 100)) if active_count else 0, "hint": "Seçilen dönemde veri var"},
        {"label": "CTR", "value": totals["ctr"], "suffix": "%", "delta": _delta(totals["ctr"], prev_totals["ctr"]), "score": parts["ctr"], "hint": "Tıklama isteği"},
        {"label": "CPA", "value": totals["cpa"], "suffix": " TL", "delta": -_delta(totals["cpa"], prev_totals["cpa"]), "score": parts["cpa"], "hint": "Sonuç maliyeti"},
        {"label": "ROAS", "value": totals["roas"], "suffix": "x", "delta": _delta(totals["roas"], prev_totals["roas"]), "score": parts["roas"], "hint": "Gelir / harcama"},
        {"label": "Frekans", "value": totals["frequency"], "suffix": "", "delta": -_delta(totals["frequency"], prev_totals["frequency"]), "score": parts["frequency"], "hint": "Reklam yorgunluğu"},
    ]

    daily_metric_rows = current_metric_qs.values("date").annotate(
        impressions=Sum("impressions"), reach=Sum("reach"), clicks=Sum("clicks"),
        spend=Sum("spend"), conversions=Sum("conversions"),
        conversion_value=Sum("conversion_value"), likes=Sum("likes"),
        comments=Sum("comments"), shares=Sum("shares"), saves=Sum("saves"),
        engagement=Sum("engagement"), avg_frequency=Avg("frequency"),
    )
    daily_totals = {row["date"]: _totals_from_dict(row) for row in daily_metric_rows}
    labels, ctr_data, roas_data, cpa_data, score_data, spend_data = [], [], [], [], [], []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        day_totals = daily_totals.get(day, _totals_from_dict({}))
        day_score, _ = _health_score(day_totals)
        labels.append(day.strftime("%d.%m"))
        ctr_data.append(round(day_totals["ctr"], 2))
        roas_data.append(round(day_totals["roas"], 2))
        cpa_data.append(round(day_totals["cpa"], 2))
        spend_data.append(round(day_totals["spend"], 2))
        score_data.append(day_score)

    platforms = list(Platform.objects.filter(is_active=True).order_by("name")) if Platform else []
    platform_accounts = list(platform_accounts_for_request(request, active_only=True).select_related("platform").order_by("platform__name", "account_name")) if PlatformAccount else []
    platform_label = "Tüm platformlar"
    account_label = "Tüm hesaplar"
    if platform_code:
        platform_label = next((p.name for p in platforms if getattr(p, "code", "") == platform_code), platform_code)
    if account_id:
        selected_account = next((acc for acc in platform_accounts if str(acc.id) == str(account_id)), None)
        if selected_account:
            account_label = selected_account.account_name or selected_account.account_id or f"Hesap #{selected_account.id}"

    recommendations = _global_recommendations(totals, parts, active_count, measured_count) if has_health_data else []
    for recommendation in recommendations:
        recommendation["points"] = _sentence_list(recommendation.get("text"))
    ai_result = None
    ai_error = ""
    if run_ai and has_health_data:
        ai_result, ai_error = _build_health_ai_payload(
            user=request.user,
            totals=totals,
            score=score,
            score_delta=score - prev_score,
            active_count=active_count,
            measured_count=measured_count,
            ad_rows=ad_rows,
            days=days,
            account_label=account_label,
            platform_label=platform_label,
            active_rule_count=active_rule_count,
            matched_rule_count=matched_rule_count,
            organization=(agency_scope.selected_client.organization if agency_scope.selected_client else None),
        )
        if ai_result is None:
            ai_result = _fallback_ai_result(totals, score, recommendations, account_label, ai_error)
        if ai_result:
            _save_health_ai_analysis(
                user=request.user,
                ai_result=ai_result,
                ai_error=ai_error,
                totals=totals,
                score=score,
                score_delta=score - prev_score,
                active_count=active_count,
                measured_count=measured_count,
                days=days,
                platform_code=platform_code,
                platform_label=platform_label,
                account_id=analysis_account_id,
                account_label=account_label,
                status_filter=status_filter,
            )

    latest_context = (
        _latest_analysis_context(
            user=request.user,
            days=days,
            platform_code=platform_code,
            account_id=analysis_account_id,
            status_filter=status_filter,
        )
        if has_health_data
        else {
            "last_health_analysis_at": None,
            "last_health_analysis_source": "",
            "saved_ai_result": None,
        }
    )
    if not run_ai and latest_context.get("saved_ai_result"):
        ai_result = latest_context["saved_ai_result"]
    if ai_result:
        unique_agents = []
        seen_agent_outputs = set()
        for agent in ai_result.get("agents", []) or []:
            output_key = _normalize_text_key(
                f"{agent.get('finding', '')} {agent.get('recommendation', '')}"
            )
            if output_key and output_key in seen_agent_outputs:
                continue
            if output_key:
                seen_agent_outputs.add(output_key)
            unique_agents.append(agent)
        ai_result["agents"] = unique_agents

        seen_notes = set()
        unique_notes = []
        for note in ai_result.get("decision_notes", []) or []:
            points = _unique_texts(
                (note.get("points") or []) + _sentence_list(note.get("text")),
                limit=4,
            )
            note_key = _normalize_text_key(" ".join(points))
            if not points or note_key in seen_notes:
                continue
            seen_notes.add(note_key)
            note["points"] = points
            unique_notes.append(note)
        ai_result["decision_notes"] = unique_notes

    context = {
        "empty": False,
        "days": days,
        "start": start,
        "today": today,
        "totals": totals,
        "score": score,
        "score_delta": score - prev_score,
        "score_status": _status(score, measured_count > 0),
        "parts": parts,
        "kpis": kpis,
        "recommendations": recommendations,
        "ai_result": ai_result,
        "ai_error": ai_error,
        "run_ai": run_ai,
        "agency_scope": agency_scope,
        "active_rule_count": active_rule_count,
        "matched_rule_count": matched_rule_count,
        "rule_engine": rule_engine,
        **latest_context,
        "account_label": account_label,
        "platform_label": platform_label,
        "all_ads": ad_rows,
        "healthy_ads": healthy_ads,
        "risky_ads": risky_ads,
        "active_count": active_count,
        "measured_count": measured_count,
        "has_health_data": has_health_data,
        "platforms": platforms,
        "platform_accounts": platform_accounts,
        "filtre_platform": platform_code,
        "filtre_hesap": account_id,
        "filtre_durum": status_filter,
        "sirala": order,
        "chart_labels_json": json.dumps(labels),
        "chart_ctr_json": json.dumps(ctr_data),
        "chart_roas_json": json.dumps(roas_data),
        "chart_cpa_json": json.dumps(cpa_data),
        "chart_spend_json": json.dumps(spend_data),
        "chart_score_json": json.dumps(score_data),
    }
    if not run_ai and rule_engine["status"] == "completed":
        CacheService.set(
            "health_center",
            *cache_key_parts,
            value=context,
            timeout=HEALTH_CENTER_CACHE_TIMEOUT,
            version=version,
        )
    return render(request, "reports/health_center.html", context)
