from decimal import Decimal

from django.db import migrations


# credit_cost and maximum provider cost (USD, including the 30% safety margin)
AI_TARIFFS = {
    "auto-response": (3, "0.0260"),
    "lead-scoring": (4, "0.0390"),
    "sentiment-analysis": (7, "0.0650"),
    "hashtag-recommendation": (4, "0.0325"),
    "influencer-analysis": (6, "0.0585"),
    "performance-insights": (6, "0.0520"),
    "creative-studio-content": (22, "0.2600"),
    "creative-studio-image": (30, "0.5000"),
    "creative-studio-regenerate": (30, "0.2500"),
    "creative-studio-video": (160, "1.2000"),
    "content-post-ideas": (8, "0.0780"),
    "content-caption": (6, "0.0520"),
    "vision-analysis": (13, "0.0910"),
    "video-analysis": (15, "0.1300"),
    "market-trend-analysis": (8, "0.0715"),
    "competitor-bulk-analysis": (15, "0.1768"),
    "competitor-single-analysis": (13, "0.1508"),
    "campaign-center-analysis": (13, "0.1508"),
    "campaign-center-recommendation": (13, "0.1508"),
    "campaign-panel-analysis": (15, "0.1755"),
    "campaign-panel-recommendation": (15, "0.1755"),
    "ad-report-card-analysis": (13, "0.1508"),
    "ad-report-card-recommendation": (13, "0.1508"),
    "control-tower-analysis": (15, "0.1768"),
    "health-center-deep-analysis": (15, "0.1768"),
}


def update_catalog(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Package = apps.get_model("core", "AICreditPackage")
    for key, (credits, max_cost) in AI_TARIFFS.items():
        Tariff.objects.filter(key=key).update(
            credit_cost=credits,
            max_cost_usd=Decimal(max_cost),
            safety_margin_percent=30,
        )
    Tariff.objects.filter(uses_openai=False).update(
        credit_cost=0,
        max_input_tokens=0,
        max_output_tokens=0,
        max_cost_usd=Decimal("0.0000"),
    )
    Package.objects.filter(name="ai_credit_5000").update(
        price=Decimal("5000.00"),
        price_with_kdv=Decimal("6000.00"),
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0033_update_plan_credits_and_topup_prices")]
    operations = [migrations.RunPython(update_catalog, migrations.RunPython.noop)]
