from django.db import migrations


REMOVED_FEATURE = "öncelikli e-posta desteği"


def remove_priority_email_support_feature(apps, schema_editor):
    MembershipPlan = apps.get_model("core", "MembershipPlan")

    for plan in MembershipPlan.objects.exclude(features="").iterator():
        feature_lines = plan.features.splitlines()
        filtered_lines = [
            line for line in feature_lines if line.strip().casefold() != REMOVED_FEATURE
        ]
        updated_features = "\n".join(filtered_lines)

        if updated_features != plan.features:
            plan.features = updated_features
            plan.save(update_fields=["features"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0047_remove_selected_plan_features"),
    ]

    operations = [
        migrations.RunPython(remove_priority_email_support_feature, migrations.RunPython.noop),
    ]
