from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Max, Sum
from django.shortcuts import render
from django.apps import apps
from django.utils import timezone

from core.services.agency_scope import get_agency_scope, scope_queryset


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


def _aware_datetime(value):
    """
    Template tarafında localtime/timesince hatası oluşmaması için
    naive datetime değerlerini mevcut timezone'a aware yapar.
    """
    if not value:
        return None


def _num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _fmt(value, digits=2):
    text = f"{_num(value):,.{digits}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_int(value):
    return f"{int(round(_num(value))):,}".replace(",", ".")


def _success_score(metrics, fallback_score=0):
    impressions = _num(metrics.get("impressions"))
    ctr = _num(metrics.get("ctr"))
    roas = _num(metrics.get("roas"))
    conversions = _num(metrics.get("conversions"))
    engagement_rate = _num(metrics.get("engagement_rate"))
    base = _num(fallback_score)
    score = 0
    score += min(30, ctr * 8)
    score += min(30, roas * 10)
    score += min(18, conversions * 1.4)
    score += min(12, engagement_rate * 4)
    score += min(10, impressions / 12000)
    return round(max(score, base), 1)


def _rule_adjustment(tasks):
    adjustment = 0.0
    for task in tasks:
        priority = max(0, min(100, _num(getattr(task, "priority_score", 50))))
        severity = getattr(task, "severity", "info")
        if severity == "opportunity":
            adjustment += priority / 20
        elif severity == "info":
            adjustment += priority / 50
        elif severity == "warning":
            adjustment -= priority / 25
        elif severity == "critical":
            adjustment -= priority / 15
    return round(max(-20, min(15, adjustment)), 1)


def _success_reasons(metrics):
    reasons = []
    ctr = _num(metrics.get("ctr"))
    roas = _num(metrics.get("roas"))
    conversions = _num(metrics.get("conversions"))
    engagement = _num(metrics.get("engagement"))
    engagement_rate = _num(metrics.get("engagement_rate"))
    clicks = _num(metrics.get("clicks"))
    impressions = _num(metrics.get("impressions"))

    if roas >= 2:
        reasons.append(f"ROAS {_fmt(roas)}x ile harcamaya göre güçlü dönüş değeri üretiyor.")
    elif roas > 0:
        reasons.append(f"ROAS {_fmt(roas)}x; dönüşüm değeri var ve izlenebilir seviyede.")
    if ctr >= 1.5:
        reasons.append(f"CTR %{_fmt(ctr)}; kreatif tıklama isteği oluşturuyor.")
    elif clicks > 0 and impressions > 0:
        reasons.append(f"{_fmt_int(clicks)} tıklama aldı; mesaj kullanıcıda tepki oluşturmuş.")
    if conversions > 0:
        reasons.append(f"{_fmt_int(conversions)} dönüşüm ile sonuç üreten kreatifler arasında.")
    if engagement_rate >= 2:
        reasons.append(f"Etkileşim oranı %{_fmt(engagement_rate)}; sosyal sinyal güçlü.")
    elif engagement > 0:
        reasons.append(f"{_fmt_int(engagement)} etkileşim ile görünür kullanıcı ilgisi var.")
    if not reasons:
        reasons.append("Başarı sırası mevcut skor, gösterim ve son metrik sinyallerine göre hesaplandı; daha net karar için yeni metrik verisi beklenmeli.")
    return reasons[:3]


def _metric_pack(metric):
    impressions = _num(metric.get("impressions"))
    clicks = _num(metric.get("clicks"))
    spend = _num(metric.get("spend"))
    conversion_value = _num(metric.get("conversion_value"))
    engagement = _num(metric.get("engagement"))
    ctr = _num(metric.get("ctr")) or ((clicks / impressions) * 100 if impressions else 0)
    cpc = _num(metric.get("cpc")) or (spend / clicks if clicks else 0)
    roas = _num(metric.get("roas")) or (conversion_value / spend if spend else 0)
    engagement_rate = _num(metric.get("engagement_rate")) or ((engagement / impressions) * 100 if impressions else 0)
    return {
        "impressions": impressions,
        "clicks": clicks,
        "spend": spend,
        "ctr": ctr,
        "cpc": cpc,
        "roas": roas,
        "conversions": _num(metric.get("conversions")),
        "conversion_value": conversion_value,
        "engagement": engagement,
        "engagement_rate": engagement_rate,
        "last_metric_date": metric.get("last_metric_date"),
        "source": metric.get("source") or "Kreatif metrikleri",
    }

    try:
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value
    except Exception:
        return None


@login_required
def creative_center(request):
    Creative = _model("Creative")
    CreativeMetricHistory = _model("CreativeMetricHistory")
    AdMetricHistory = _model("AdMetricHistory")
    OctoTaskInstance = _model("OctoTaskInstance")

    creatives = []
    totals = {"image": 0, "video": 0, "carousel": 0, "other": 0}
    agency_scope = get_agency_scope(request)

    if Creative:
        qs = scope_queryset(request, Creative.objects.all()).order_by("-id")

        type_field = _field(Creative, "media_type", "creative_type", "type", "format")
        name_field = _field(Creative, "name", "title", "headline")
        url_field = _field(Creative, "media_url", "image_url", "video_url", "thumbnail_url", "url")
        score_field = _field(Creative, "performance_score", "score", "ai_score")
        created_field = _field(Creative, "created_at", "created_time")
        creative_ids = list(qs.values_list("id", flat=True))
        metric_map = {}
        rule_task_map = {}

        if OctoTaskInstance and creative_ids:
            rule_tasks = (
                OctoTaskInstance.objects
                .filter(creative_id__in=creative_ids)
                .exclude(status__in=["dismissed", "snoozed"])
                .select_related("rule")
                .order_by("-priority_score", "-last_detected_at")
            )
            for task in rule_tasks:
                rule_task_map.setdefault(task.creative_id, []).append(task)

        if CreativeMetricHistory and creative_ids:
            for row in (
                CreativeMetricHistory.objects.filter(creative_id__in=creative_ids)
                .values("creative_id")
                .annotate(
                    impressions=Sum("impressions"),
                    clicks=Sum("clicks"),
                    spend=Sum("spend"),
                    conversions=Sum("conversions"),
                    conversion_value=Sum("conversion_value"),
                    engagement=Sum("engagement"),
                    ctr=Avg("ctr"),
                    cpc=Avg("cpc"),
                    roas=Avg("roas"),
                    engagement_rate=Avg("engagement_rate"),
                    last_metric_date=Max("date"),
                )
            ):
                row["source"] = "Kreatif metrikleri"
                metric_map[row["creative_id"]] = _metric_pack(row)

        missing_metric_ids = [creative_id for creative_id in creative_ids if creative_id not in metric_map]
        if AdMetricHistory and missing_metric_ids:
            ad_metric_qs = scope_queryset(
                request,
                AdMetricHistory.objects.filter(ad__source_type="OWN", ad__creative_id__in=missing_metric_ids),
                account_lookup="ad__platform_account",
                user_lookup="ad__user",
            )
            for row in (
                ad_metric_qs
                .values("ad__creative_id")
                .annotate(
                    impressions=Sum("impressions"),
                    clicks=Sum("clicks"),
                    spend=Sum("spend"),
                    conversions=Sum("conversions"),
                    conversion_value=Sum("conversion_value"),
                    engagement=Sum("engagement"),
                    ctr=Avg("ctr"),
                    cpc=Avg("cpc"),
                    roas=Avg("roas"),
                    engagement_rate=Avg("engagement_rate"),
                    last_metric_date=Max("date"),
                )
            ):
                row["source"] = "Bağlı reklam metrikleri"
                metric_map[row["ad__creative_id"]] = _metric_pack(row)

        for item in qs:
            raw_type = (getattr(item, type_field, "") if type_field else "") or "other"
            raw_type = str(raw_type).lower()

            if "video" in raw_type or "reels" in raw_type:
                group = "video"
            elif "carousel" in raw_type:
                group = "carousel"
            elif "image" in raw_type or "gorsel" in raw_type or "photo" in raw_type:
                group = "image"
            else:
                group = "other"

            totals[group] += 1

            created_at = getattr(item, created_field, None) if created_field else None
            created_at = _aware_datetime(created_at)

            raw_score = getattr(item, score_field, 0) if score_field else 0
            metrics = metric_map.get(item.id, _metric_pack({}))
            metric_score = _success_score(metrics, raw_score)
            creative_rule_tasks = rule_task_map.get(item.id, [])
            rule_adjustment = _rule_adjustment(creative_rule_tasks)
            success_score = round(max(0, min(100, metric_score + rule_adjustment)), 1)

            creatives.append({
                "id": item.id,
                "name": getattr(item, name_field, None) if name_field else f"Kreatif #{item.id}",
                "type": group,
                "raw_type": raw_type,
                "media_url": getattr(item, url_field, "") if url_field else "",
                "score": success_score,
                "metric_score": metric_score,
                "rule_adjustment": rule_adjustment,
                "rule_match_count": len(creative_rule_tasks),
                "raw_score": raw_score,
                "metrics": {
                    "impressions": _fmt_int(metrics["impressions"]),
                    "clicks": _fmt_int(metrics["clicks"]),
                    "ctr": f"%{_fmt(metrics['ctr'])}",
                    "roas": f"{_fmt(metrics['roas'])}x",
                    "conversions": _fmt_int(metrics["conversions"]),
                    "spend": f"{_fmt(metrics['spend'])} TL",
                    "engagement": _fmt_int(metrics["engagement"]),
                    "engagement_rate": f"%{_fmt(metrics['engagement_rate'])}",
                },
                "metric_source": metrics["source"],
                "last_metric_date": metrics["last_metric_date"],
                "success_reasons": _success_reasons(metrics),
                "created_at": created_at,
            })

    top_creatives = sorted(creatives, key=lambda x: x.get("score") or 0, reverse=True)

    context = {
        "agency_scope": agency_scope,
        "creatives": creatives,
        "top_creatives": top_creatives,
        "totals": totals,
    }
    return render(request, "reports/creative_center.html", context)
