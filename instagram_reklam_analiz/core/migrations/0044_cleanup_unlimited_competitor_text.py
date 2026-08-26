from django.db import migrations


LIMITS = {
    "gold": (10, "10 rakip takibi"),
    "platinum": (30, "30 rakip takibi"),
    "platinyum": (30, "30 rakip takibi"),
}


def cleanup_competitor_features(apps, schema_editor):
    MembershipPlan = apps.get_model("core", "MembershipPlan")
    for name, (limit, feature_text) in LIMITS.items():
        for plan in MembershipPlan.objects.filter(name=name):
            features = [
                feature
                for feature in (plan.features or "").splitlines()
                if "rakip" not in feature.casefold()
            ]
            features.append(feature_text)
            plan.max_competitors = limit
            plan.features = "\n".join(features)
            plan.save(update_fields=["max_competitors", "features"])


class Migration(migrations.Migration):
    dependencies = [("core", "0043_set_business_competitor_limits")]

    operations = [
        migrations.RunPython(cleanup_competitor_features, migrations.RunPython.noop),
    ]
