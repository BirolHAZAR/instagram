from django.db import migrations


GROUPED_OPERATION_KEYS = [
    "control-tower-analysis",
    "health-center-deep-analysis",
    "campaign-panel-analysis",
    "campaign-panel-recommendation",
    "campaign-center-analysis",
    "campaign-center-recommendation",
    "ad-report-card-analysis",
    "ad-report-card-recommendation",
    "competitor-single-analysis",
    "creative-studio-content",
]


def finalize_gateway_tariff_budgets(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.filter(key__in=GROUPED_OPERATION_KEYS).update(max_calls=4)
    Tariff.objects.filter(key__in=[
        "control-tower-analysis", "health-center-deep-analysis"
    ]).update(cache_timeout_seconds=21600)


class Migration(migrations.Migration):
    dependencies = [("core", "0051_ai_gateway_budget_fields")]
    operations = [
        migrations.RunPython(finalize_gateway_tariff_budgets, migrations.RunPython.noop),
    ]
