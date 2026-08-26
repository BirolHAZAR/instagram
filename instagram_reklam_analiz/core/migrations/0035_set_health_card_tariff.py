from django.db import migrations


def update_health_card_tariff(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.filter(key="health-center-deep-analysis").update(
        display_name="Sağlık Karnesi AI analizi",
        category="Sağlık Karnesi",
        credit_cost=100,
        is_active=True,
        note="Sağlık Karnesi toplu 16 uzmanlı AI analizi; kredi ve token takibi aktiftir.",
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0034_reprice_all_ai_tariffs_and_5000_package")]
    operations = [migrations.RunPython(update_health_card_tariff, migrations.RunPython.noop)]
