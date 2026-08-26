from django.db import migrations


AGENCY_COMPETITOR_LIMITS = {
    "agency_3": 5,
    "agency_5": 12,
    "agency_10": 30,
}


def add_agency_competitor_features(apps, schema_editor):
    MembershipPlan = apps.get_model("core", "MembershipPlan")
    for name, limit in AGENCY_COMPETITOR_LIMITS.items():
        for plan in MembershipPlan.objects.filter(name=name):
            features = [
                feature
                for feature in (plan.features or "").splitlines()
                if "rakip" not in feature.casefold()
            ]
            features.insert(min(2, len(features)), f"{limit} rakip takibi")
            plan.max_competitors = limit
            plan.features = "\n".join(features)
            plan.save(update_fields=["max_competitors", "features"])


class Migration(migrations.Migration):
    dependencies = [("core", "0044_cleanup_unlimited_competitor_text")]

    operations = [
        migrations.RunPython(add_agency_competitor_features, migrations.RunPython.noop),
    ]
