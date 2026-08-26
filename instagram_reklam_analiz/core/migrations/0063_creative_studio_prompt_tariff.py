from django.db import migrations


def create_prompt_tariff(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.update_or_create(
        key="creative-studio-prompt",
        defaults={
            "display_name": "Creative Studio görsel analizi ve profesyonel prompt",
            "category": "Creative Studio",
            "credit_cost": 6,
            "model_name": "",
            "max_input_tokens": 12000,
            "max_output_tokens": 1800,
            "max_calls": 1,
            "cache_timeout_seconds": 0,
            "max_cost_usd": 0,
            "safety_margin_percent": 25,
            "uses_openai": True,
            "is_active": True,
            "note": (
                "Referans ürün görsellerini bir kez analiz eder. Ayrı, düşük maliyetli "
                "tarife sayesinde tam içerik üretim tarifesi iki kez tüketilmez."
            ),
        },
    )


def remove_prompt_tariff(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.filter(key="creative-studio-prompt").delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0062_organization_additional_seats")]
    operations = [
        migrations.RunPython(create_prompt_tariff, remove_prompt_tariff),
    ]
