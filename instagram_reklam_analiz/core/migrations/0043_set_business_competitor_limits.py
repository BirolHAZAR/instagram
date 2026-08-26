from django.db import migrations


LIMITS = {
    "gold": (10, "10 rakip takibi"),
    "platinum": (30, "30 rakip takibi"),
    "platinyum": (30, "30 rakip takibi"),
}


def set_finite_competitor_limits(apps, schema_editor):
    MembershipPlan = apps.get_model("core", "MembershipPlan")
    for name, (limit, feature_text) in LIMITS.items():
        for plan in MembershipPlan.objects.filter(name=name):
            features = []
            competitor_feature_replaced = False
            for feature in (plan.features or "").splitlines():
                if "rakip" in feature.casefold() and "takip" in feature.casefold():
                    if not competitor_feature_replaced:
                        features.append(feature_text)
                        competitor_feature_replaced = True
                else:
                    features.append(feature)
            if not competitor_feature_replaced:
                features.append(feature_text)
            plan.max_competitors = limit
            plan.features = "\n".join(features)
            plan.save(update_fields=["max_competitors", "features"])


class Migration(migrations.Migration):
    dependencies = [("core", "0042_fix_platform_and_agency_limits")]

    operations = [
        migrations.RunPython(set_finite_competitor_limits, migrations.RunPython.noop),
    ]
