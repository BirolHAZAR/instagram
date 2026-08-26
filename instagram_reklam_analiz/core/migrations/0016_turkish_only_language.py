from django.db import migrations, models


def force_turkish(apps, schema_editor):
    UserProfile = apps.get_model("core", "UserProfile")
    UserProfile.objects.exclude(preferred_language="tr").update(preferred_language="tr")


class Migration(migrations.Migration):
    dependencies = [("core", "0015_scheduledreport_agency_client")]
    operations = [
        migrations.RunPython(force_turkish, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="userprofile",
            name="preferred_language",
            field=models.CharField(choices=[("tr", "Türkçe")], default="tr", max_length=5),
        ),
    ]
