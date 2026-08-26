from django.db import migrations


def activate_competitor_ai(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.filter(key="competitor-single-analysis").update(is_active=True, credit_cost=3)


class Migration(migrations.Migration):
    dependencies = [("core", "0029_complete_ai_tariff_catalog")]
    operations = [migrations.RunPython(activate_competitor_ai, migrations.RunPython.noop)]
