from django.db import migrations


def activate_all_tariffs(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.all().update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [("core", "0036_update_health_control_and_executive_tariffs")]
    operations = [migrations.RunPython(activate_all_tariffs, migrations.RunPython.noop)]
