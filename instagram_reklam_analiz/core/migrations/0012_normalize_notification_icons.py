from django.db import migrations


def normalize_notification_icons(apps, schema_editor):
    Notification = apps.get_model("core", "Notification")
    aliases = {
        "chart-line": "fa-chart-line",
        "chart_line": "fa-chart-line",
        "line-chart": "fa-chart-line",
        "fas fa-chart-line": "fa-chart-line",
    }
    for old_value, new_value in aliases.items():
        Notification.objects.filter(icon__iexact=old_value).update(icon=new_value)


class Migration(migrations.Migration):
    dependencies = [("core", "0011_billinginfo_identity_hash")]
    operations = [migrations.RunPython(normalize_notification_icons, migrations.RunPython.noop)]
