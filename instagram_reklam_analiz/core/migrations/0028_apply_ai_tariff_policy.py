from django.db import migrations


POLICY = {
    "creative-studio-content": 10,
    "creative-studio-regenerate": 10,
    "health-center-deep-analysis": 5,
    "control-tower-analysis": 5,
    "ad-report-card-analysis": 3,
    "ad-report-card-recommendation": 3,
    "campaign-center-analysis": 3,
    "campaign-center-recommendation": 3,
    "campaign-panel-analysis": 3,
    "campaign-panel-recommendation": 3,
    "campaign-local-analysis": 0,
    "account-local-analysis": 0,
    "suggestions-local": 0,
}


def apply_policy(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    defaults = {
        "ad-report-card-recommendation": {
            "display_name": "Reklam Karnesi AI onerisi",
            "category": "Reklam Karnesi",
            "model_name": "gpt-4o",
            "max_input_tokens": 8000,
            "max_output_tokens": 2000,
            "uses_openai": True,
            "is_active": True,
            "safety_margin_percent": 30,
        },
    }
    for key, credits in POLICY.items():
        if key in defaults:
            values = {**defaults[key], "credit_cost": credits}
            Tariff.objects.update_or_create(key=key, defaults=values)
        else:
            Tariff.objects.filter(key=key).update(credit_cost=credits)


class Migration(migrations.Migration):
    dependencies = [("core", "0027_ai_operation_tariffs")]
    operations = [migrations.RunPython(apply_policy, migrations.RunPython.noop)]
