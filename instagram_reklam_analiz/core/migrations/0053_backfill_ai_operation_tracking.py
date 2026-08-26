from django.db import migrations


REFERENCE_PREFIX_MAP = {
    "control_tower.deep_analysis": "control-tower-analysis",
    "health_center.deep_account_analysis": "health-center-deep-analysis",
    "campaign_panel.analysis": "campaign-panel-analysis",
    "campaign_panel.recommendation": "campaign-panel-recommendation",
    "campaign_center.analysis": "campaign-center-analysis",
    "campaign_center.recommendation": "campaign-center-recommendation",
    "ads_panel.analysis": "ad-report-card-analysis",
    "ads_panel.recommendation": "ad-report-card-recommendation",
    "competitor_intelligence.single_ad": "competitor-single-analysis",
    "creative_studio.": "creative-studio-content",
    "content_generator.post_ideas": "content-post-ideas",
    "content_generator.caption": "content-caption",
    "market_analyzer.trend_analysis": "market-trend-analysis",
    "performance_analyzer.insights": "performance-insights",
    "recommendation_engine.recommendations": "performance-insights",
    "ai_content_analyzer.vision": "vision-analysis",
    "marketplace.product_research.vision": "vision-analysis",
    "ai_content_analyzer.video": "video-analysis",
}


def backfill_operation_tracking(apps, schema_editor):
    TokenLedger = apps.get_model("core", "OpenAITokenUsageLedger")
    CreditLedger = apps.get_model("core", "AICreditLedger")
    FeatureLedger = apps.get_model("core", "FeatureUsageLedger")

    for prefix, operation_key in REFERENCE_PREFIX_MAP.items():
        TokenLedger.objects.filter(
            operation_key="", reference__startswith=prefix
        ).update(operation_key=operation_key)

    refunds = CreditLedger.objects.filter(action="refund", reference__startswith="refund-ledger:")
    for refund in refunds.iterator():
        try:
            consume_id = int(refund.reference.split(":", 1)[1])
        except (TypeError, ValueError, IndexError):
            continue
        consume = CreditLedger.objects.filter(pk=consume_id, action="consume").first()
        if consume is None:
            continue
        usage = FeatureLedger.objects.filter(
            user_id=consume.user_id,
            organization_id=consume.organization_id,
            reference=consume.reference,
            status="allowed",
            created_at__lte=refund.created_at,
        ).order_by("-created_at", "-id").first()
        if usage is not None:
            usage.status = "failed"
            usage.metadata = {**(usage.metadata or {}), "credit_state": "refunded"}
            usage.save(update_fields=["status", "metadata"])


class Migration(migrations.Migration):
    dependencies = [("core", "0052_finalize_ai_gateway_tariff_budgets")]
    operations = [migrations.RunPython(backfill_operation_tracking, migrations.RunPython.noop)]
