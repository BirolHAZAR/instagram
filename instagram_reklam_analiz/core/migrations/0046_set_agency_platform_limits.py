from django.db import migrations


AGENCY_PLATFORM_LIMITS = {
    "agency_3": 15,
    "agency_5": 40,
    "agency_10": 100,
}


def set_agency_platform_limits(apps, schema_editor):
    MembershipPlan = apps.get_model("core", "MembershipPlan")
    for name, limit in AGENCY_PLATFORM_LIMITS.items():
        for plan in MembershipPlan.objects.filter(name=name):
            features = [
                feature
                for feature in (plan.features or "").splitlines()
                if "platform hesab" not in feature.casefold()
            ]
            features.insert(min(2, len(features)), f"{limit} toplam platform hesabı")
            plan.max_instagram_accounts = limit
            plan.features = "\n".join(features)
            plan.save(update_fields=["max_instagram_accounts", "features"])


class Migration(migrations.Migration):
    dependencies = [("core", "0045_add_agency_competitor_features")]

    operations = [
        migrations.RunPython(set_agency_platform_limits, migrations.RunPython.noop),
    ]
