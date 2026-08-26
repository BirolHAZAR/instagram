from decimal import Decimal

from django.db import migrations


def update_tariffs(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.filter(key="health-center-deep-analysis").update(
        display_name="Sağlık Karnesi AI analizi",
        category="Sağlık Karnesi",
        credit_cost=50,
        is_active=True,
    )
    Tariff.objects.filter(key="control-tower-analysis").update(
        display_name="Control Tower AI analizi",
        category="Control Tower",
        credit_cost=75,
        is_active=True,
    )
    Tariff.objects.update_or_create(
        key="executive-dashboard-summary",
        defaults={
            "display_name": "Özet Dashboard AI özeti",
            "category": "Özet Dashboard",
            "credit_cost": 75,
            "model_name": "gpt-4o",
            "max_input_tokens": 32000,
            "max_output_tokens": 5600,
            "max_cost_usd": Decimal("0.1768"),
            "safety_margin_percent": 30,
            "uses_openai": True,
            "is_active": True,
            "note": "AI yönetici özeti Control Tower analizi içinde üretilir; aynı çalışmada ikinci kez kredi kesilmez.",
        },
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0035_set_health_card_tariff")]
    operations = [migrations.RunPython(update_tariffs, migrations.RunPython.noop)]
