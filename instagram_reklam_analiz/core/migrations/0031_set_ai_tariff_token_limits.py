from django.db import migrations


# Limits cover the complete operation, not one specialist call.
LIMITS = {
    "creative-studio-content": (32000, 12000),
    "creative-studio-regenerate": (32000, 12000),
    "health-center-deep-analysis": (32000, 5600),
    "control-tower-analysis": (32000, 5600),
    "ad-report-card-analysis": (24000, 5600),
    "ad-report-card-recommendation": (24000, 5600),
    "campaign-center-analysis": (24000, 5600),
    "campaign-center-recommendation": (24000, 5600),
    "campaign-panel-analysis": (28000, 6500),
    "campaign-panel-recommendation": (28000, 6500),
    "competitor-single-analysis": (24000, 5600),
    "competitor-bulk-analysis": (32000, 5600),
    "market-trend-analysis": (12000, 2500),
    "performance-insights": (8000, 2000),
    "sentiment-analysis": (12000, 2000),
    "hashtag-recommendation": (4000, 1500),
    "lead-scoring": (6000, 1500),
    "auto-response": (4000, 1000),
    "influencer-analysis": (10000, 2000),
    "content-post-ideas": (12000, 3000),
    "content-caption": (8000, 2000),
    "vision-analysis": (16000, 3000),
    "video-analysis": (24000, 4000),
}


def set_limits(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    for key, (max_input, max_output) in LIMITS.items():
        Tariff.objects.filter(key=key).update(
            max_input_tokens=max_input,
            max_output_tokens=max_output,
            safety_margin_percent=30,
        )
    Tariff.objects.filter(uses_openai=False).update(
        max_input_tokens=0, max_output_tokens=0, max_cost_usd=0,
    )
    Tariff.objects.filter(key="competitor-single-analysis").update(
        is_active=True,
        note="Rakip ekranindaki gercek 16 uzmanli AI analizi; kredi ve token kaydi aktiftir.",
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0030_activate_real_competitor_ai")]
    operations = [migrations.RunPython(set_limits, migrations.RunPython.noop)]
