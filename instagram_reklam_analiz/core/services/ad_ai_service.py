from datetime import date, datetime
from decimal import Decimal

from django.conf import settings
from django.db.models import Q

from core.models import (
    AdMetricHistory,
    OctoRuleEngineRun,
    OctoTaskInstance,
    OctoTaskRule,
    ReklamAIAnaliz,
)
from core.services.ai_agent_ecosystem import build_campaign_agent_ecosystem, run_sixteen_agent_orchestration
from core.services.performance_metrics import aggregate_metric_queryset
from core.utils.metric_text import format_metric_text_tr


def _json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _metric_payload(ad):
    history = AdMetricHistory.objects.filter(ad=ad).order_by("date")
    summary = {key: _json_value(value) for key, value in aggregate_metric_queryset(history).items()}
    summary["first_date"] = history.values_list("date", flat=True).first().isoformat() if history.exists() else None
    summary["last_date"] = history.values_list("date", flat=True).last().isoformat() if history.exists() else None
    summary["row_count"] = history.count()
    summary["daily"] = [
        {
            "date": row.date.isoformat(),
            "impressions": row.impressions,
            "clicks": row.clicks,
            "spend": float(row.spend or 0),
            "conversions": float(row.conversions or 0),
            "conversion_value": float(row.conversion_value or 0),
            "ctr": float(row.ctr or 0),
            "cpc": float(row.cpc or 0),
            "cpm": float(row.cpm or 0),
            "roas": float(row.roas or 0),
            "reach": row.reach,
            "frequency": float(row.frequency or 0),
            "engagement": row.engagement,
            "engagement_rate": float(row.engagement_rate or 0),
            "cpa": float(row.cost_per_conversion or 0),
        }
        for row in history.order_by("-date")[:90]
    ]
    return summary


def _creative_payload(ad):
    creative = ad.creative
    return {
        "id": creative.id if creative else None,
        "name": (creative.name or creative.title) if creative else "",
        "type": ad.ad_format or (creative.creative_type if creative else "") or "UNKNOWN",
        "image_url": ad.preview_image_url or (creative.image_url if creative else "") or "",
        "video_url": ad.preview_video_url or (creative.video_url if creative else "") or "",
        "thumbnail_url": (creative.thumbnail_url if creative else "") or ad.preview_image_url or "",
        "headline": ad.headline or (creative.title if creative else "") or "",
        "primary_text": ad.primary_text or (creative.body_text if creative else "") or "",
        "description": ad.description or (creative.description if creative else "") or "",
        "call_to_action": ad.call_to_action or (creative.call_to_action if creative else "") or "",
        "landing_url": ad.landing_url or (creative.landing_url if creative else "") or "",
        "raw_data": creative.raw_data if creative else {},
    }


def build_ad_rule_payload(ad):
    query = Q(ad=ad)
    if ad.ad_group_id:
        query |= Q(ad_group_id=ad.ad_group_id)
    if ad.campaign_id:
        query |= Q(campaign_id=ad.campaign_id)
    tasks = list(
        OctoTaskInstance.objects.filter(query)
        .exclude(status__in=["done", "dismissed"])
        .select_related("rule")
        .order_by("-priority_score", "-last_detected_at", "-created_at")[:250]
    )

    # Ayni kural her gun yeni bir donem anahtariyla kaydedilebildigi icin eski
    # taramalar popup'ta tekrar ediyordu. Reklama en yakin kapsam kazanir;
    # ayni kapsamdaki kayitlarda yalnizca en yeni tespit gosterilir.
    scope_rank = {"ad": 0, "ad_group": 1, "campaign": 2}
    winners = {}
    for task in tasks:
        if task.ad_id == ad.id:
            scope = "ad"
        elif ad.ad_group_id and task.ad_group_id == ad.ad_group_id:
            scope = "ad_group"
        else:
            scope = "campaign"
        semantic_key = task.rule.code if task.rule else f"{task.module}:{task.title_tr.strip().casefold()}"
        detected_at = task.last_detected_at or task.created_at
        candidate_key = (scope_rank[scope], -detected_at.timestamp(), -task.priority_score)
        current = winners.get(semantic_key)
        if current is None or candidate_key < current[0]:
            winners[semantic_key] = (candidate_key, scope, task)

    selected = [row for row in winners.values()]
    selected.sort(
        key=lambda row: (
            -row[2].priority_score,
            -(row[2].last_detected_at or row[2].created_at).timestamp(),
        )
    )
    rows = []
    for _, scope, task in selected:
        rows.append({
            "id": task.id,
            "rule_code": task.rule.code if task.rule else "",
            "title": format_metric_text_tr(task.title_tr),
            "message": format_metric_text_tr(task.message_tr),
            "action": format_metric_text_tr(task.action_text_tr),
            "module": task.module,
            "severity": task.severity,
            "priority_score": task.priority_score,
            "scope": scope,
            "scope_label": {
                "ad": "Reklam",
                "ad_group": "Reklam grubu",
                "campaign": "Kampanya",
            }[scope],
            "source_period_start": task.source_period_start.isoformat() if task.source_period_start else None,
            "source_period_end": task.source_period_end.isoformat() if task.source_period_end else None,
            "detected_at": task.last_detected_at.isoformat() if task.last_detected_at else task.created_at.isoformat(),
        })
    return rows, OctoTaskRule.objects.filter(is_active=True).count()


def _performance_score(metrics):
    roas = float(metrics.get("roas") or 0)
    ctr = float(metrics.get("ctr") or 0)
    conversions = float(metrics.get("conversions") or 0)
    score = 35 + min(30, roas * 8) + min(20, ctr * 4) + min(15, conversions)
    return max(0, min(100, round(score)))


def build_ad_detail(ad):
    metrics = _metric_payload(ad)
    creative = _creative_payload(ad)
    rules, active_rule_count = build_ad_rule_payload(ad)
    engine_run = (
        OctoRuleEngineRun.objects.filter(user=ad.user)
        .filter(Q(platform_account=ad.platform_account) | Q(platform_account__isnull=True))
        .order_by("-started_at", "-id")
        .first()
    )
    detail = {
        "id": ad.id,
        "name": ad.name or ad.headline or f"Reklam #{ad.id}",
        "platform_ad_id": ad.platform_ad_id or "",
        "status": ad.status,
        "status_label": ad.get_status_display() if hasattr(ad, "get_status_display") else ad.status,
        "platform": ad.platform_account.platform.name if ad.platform_account and ad.platform_account.platform else "-",
        "account": ad.platform_account.account_name or ad.platform_account.account_id if ad.platform_account else "-",
        "campaign": ad.campaign.name if ad.campaign else "-",
        "ad_group": ad.ad_group.name if ad.ad_group else "-",
        "objective": ad.objective or (ad.campaign.objective if ad.campaign else "") or "-",
        "created_at": ad.created_at.isoformat(),
        "updated_at": ad.updated_at.isoformat(),
        "metrics": metrics,
        "creative": creative,
        "rules": rules,
        "active_rule_count": active_rule_count,
        "matched_rule_count": len(rules),
        "rule_engine": {
            "status": engine_run.status if engine_run else "pending",
            "last_run_at": engine_run.finished_at.isoformat() if engine_run and engine_run.finished_at else None,
            "campaigns_evaluated": engine_run.campaigns_evaluated if engine_run else 0,
            "signals_matched": engine_run.signals_matched if engine_run else 0,
            "error": engine_run.error_message if engine_run and engine_run.status == "failed" else "",
        },
        "performance_score": _performance_score(metrics),
    }
    detail["latest_reports"] = {
        report_type: serialize_ad_report(
            ReklamAIAnaliz.objects.filter(reklam=ad, report_type=report_type).order_by("-created_at", "-id").first()
        )
        for report_type in ["analysis", "recommendation"]
    }
    return detail


def _fallback_agents(metrics, detail, rules, report_type):
    recommendations = [row.get("action") for row in rules if row.get("action")]
    return build_campaign_agent_ecosystem(
        metrics,
        detail={
            "top_ads": [{"name": detail["name"]}],
            "creative_count": 1 if detail["creative"].get("id") else 0,
            "ad_count": 1,
            "platform": detail["platform"],
            "account_name": detail["account"],
        },
        rule_events=rules,
        recommendations=recommendations if report_type == "recommendation" else [],
    )


def _summary_from_agents(agents, report_type):
    key = "recommendation" if report_type == "recommendation" else "reason"
    items = []
    for agent in agents:
        text = agent.get(key) or agent.get("finding") or agent.get("reason") or agent.get("status")
        if text:
            items.append(str(text).strip())
    return "\n".join(items)


def _compact_ai_context(detail, report_type):
    """Keep four parallel agent calls inside the shared tariff input budget."""
    metrics = detail.get("metrics") or {}
    current_metric = (metrics.get("daily") or [{}])[0]
    metric_keys = (
        "impressions", "reach", "clicks", "spend", "conversions",
        "conversion_value", "ctr", "cpc", "cpm", "cpa", "roas",
        "frequency", "engagement", "engagement_rate",
    )
    compact_metrics = {key: current_metric.get(key) for key in metric_keys}
    compact_metrics["date"] = current_metric.get("date")
    compact_metrics["data_scope"] = "latest_database_row"

    creative = detail.get("creative") or {}
    compact_creative = {
        key: creative.get(key)
        for key in (
            "id", "name", "type", "image_url", "video_url", "headline",
            "primary_text", "description", "call_to_action", "landing_url",
        )
    }
    compact_rules = [
        {
            key: rule.get(key)
            for key in (
                "rule_code", "title", "message", "action", "module", "severity",
                "scope", "source_period_start", "source_period_end",
            )
        }
        for rule in (detail.get("rules") or [])
        if rule.get("scope") == "ad"
    ][:8]
    return {
        "report_type": report_type,
        "ad": {
            key: detail.get(key)
            for key in ("id", "name", "platform", "account", "campaign", "ad_group", "objective")
        },
        "metrics": compact_metrics,
        "creative": compact_creative,
        "matched_rules": compact_rules,
        "data_scope": "selected_ad_only",
    }


def generate_ad_report(ad, user, report_type, organization=None):
    if report_type not in {"analysis", "recommendation"}:
        raise ValueError("Geçersiz rapor türü.")
    detail = build_ad_detail(ad)
    metrics = detail["metrics"]
    creative = detail["creative"]
    rules = detail["rules"]
    direct_ad_rules = [rule for rule in rules if rule.get("scope") == "ad"]
    agents = _fallback_agents(metrics, detail, direct_ad_rules, report_type)
    strategy = {}
    model_used = "deterministic-16-agent"
    visual_analyzed = False

    api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
    if api_key:
        try:
            from openai import OpenAI

            context = _compact_ai_context(detail, report_type)
            result = run_sixteen_agent_orchestration(
                client=OpenAI(api_key=api_key, timeout=45, max_retries=1),
                model=getattr(settings, "OPENAI_MODEL", "gpt-4o"),
                task=(
                    "Yalnızca seçilen reklamın veritabanındaki en güncel tek günlük metrik satırını, kendi kreatifini ve doğrudan reklama bağlı kuralları analiz et. Geçmiş dönem toplamı, kampanya veya reklam grubu geneli hakkında çıkarım yapma. Metrik tarihini sonuçta açıkça belirt."
                    if report_type == "analysis"
                    else "Yalnızca seçilen reklamın veritabanındaki en güncel tek günlük metrik satırı, kendi kreatifi ve doğrudan reklama bağlı kurallarıyla uygulanabilir öneri üret. Geçmiş dönem toplamı, kampanya veya reklam grubu geneli hakkında çıkarım yapma. Metrik tarihini sonuçta açıkça belirt."
                ),
                context=context,
                modalities=["text", "image"] if creative.get("image_url") else ["text"],
                reference=f"ads_panel.{report_type}.sixteen_agents",
                user=user,
                organization=organization,
                tariff_key=("ad-report-card-analysis" if report_type == "analysis" else "ad-report-card-recommendation"),
            )
            agents = result.get("agents") or agents
            strategy = result.get("strategy") or {}
            model_used = getattr(settings, "OPENAI_MODEL", "gpt-4o")
            visual_analyzed = bool(creative.get("image_url"))
        except Exception as exc:
            raise RuntimeError(f"Gerçek reklam AI analizi tamamlanamadı: {exc}") from exc
    else:
        raise RuntimeError("OPENAI_API_KEY tanımlı olmadığı için gerçek reklam AI analizi çalıştırılamadı.")

    summary = _summary_from_agents(agents, report_type)
    obj = ReklamAIAnaliz.objects.create(
        reklam=ad,
        created_by=user,
        report_type=report_type,
        reklam_adi=detail["name"],
        Ins_reklam_id=ad.platform_ad_id or str(ad.id),
        overall_score=detail["performance_score"],
        analysis_summary=summary if report_type == "analysis" else "",
        recommendation_summary=summary if report_type == "recommendation" else "",
        agents_results=agents,
        metrics_payload=metrics,
        creative_payload=creative,
        rules_payload=direct_ad_rules,
        strategy_payload=strategy,
        active_rule_count=detail["active_rule_count"],
        matched_rule_count=len(direct_ad_rules),
        visual_analyzed=visual_analyzed,
        ai_model_used=model_used,
        performance_score=detail["performance_score"],
    )
    return obj


def serialize_ad_report(obj):
    if not obj:
        return None
    return {
        "id": obj.id,
        "report_type": obj.report_type,
        "score": obj.overall_score,
        "summary": obj.analysis_summary if obj.report_type == "analysis" else obj.recommendation_summary,
        "agents": obj.agents_results or [],
        "metrics": obj.metrics_payload or {},
        "creative": obj.creative_payload or {},
        "rules": obj.rules_payload or [],
        "strategy": obj.strategy_payload or {},
        "active_rule_count": obj.active_rule_count,
        "matched_rule_count": obj.matched_rule_count,
        "visual_analyzed": obj.visual_analyzed,
        "model": obj.ai_model_used,
        "created_at": obj.created_at.isoformat(),
        "created_label": obj.created_at.strftime("%d.%m.%Y %H:%M"),
    }
