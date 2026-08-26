from django.db import migrations


REMOVED_FEATURES = {
    "fırsat bulucu ai",
    "creative studio",
    "özel hesap yöneticisi",
}


def remove_selected_plan_features(apps, schema_editor):
    MembershipPlan = apps.get_model("core", "MembershipPlan")

    for plan in MembershipPlan.objects.exclude(features="").iterator():
        feature_lines = plan.features.splitlines()
        filtered_lines = [
            line for line in feature_lines if line.strip().casefold() not in REMOVED_FEATURES
        ]
        updated_features = "\n".join(filtered_lines)

        if updated_features != plan.features:
            plan.features = updated_features
            plan.save(update_fields=["features"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0046_set_agency_platform_limits"),
    ]

    operations = [
        migrations.RunPython(remove_selected_plan_features, migrations.RunPython.noop),
    ]
