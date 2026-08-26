from django.db import migrations


def enable_platinum_content_calendar(apps, schema_editor):
    MembershipPlan = apps.get_model("core", "MembershipPlan")
    MembershipPlan.objects.filter(name__in=["platinum", "platinyum"]).update(
        has_content_calendar=True,
        content_calendar_days=365,
    )


def disable_platinum_content_calendar(apps, schema_editor):
    MembershipPlan = apps.get_model("core", "MembershipPlan")
    MembershipPlan.objects.filter(name__in=["platinum", "platinyum"]).update(
        has_content_calendar=False,
        content_calendar_days=0,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0070_configure_marketplace_cache_tariffs"),
    ]

    operations = [
        migrations.RunPython(
            enable_platinum_content_calendar,
            disable_platinum_content_calendar,
        ),
    ]
