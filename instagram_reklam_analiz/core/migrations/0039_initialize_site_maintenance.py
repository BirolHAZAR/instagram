from django.db import migrations


def create_default_setting(apps, schema_editor):
    SiteMaintenance = apps.get_model("core", "SiteMaintenance")
    SiteMaintenance.objects.get_or_create(pk=1, defaults={"is_active": False})


class Migration(migrations.Migration):
    dependencies = [("core", "0038_site_maintenance")]

    operations = [migrations.RunPython(create_default_setting, migrations.RunPython.noop)]
