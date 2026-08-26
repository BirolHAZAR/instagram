from django.db import migrations


PLAN_LIMITS = {
    "silver": (0, 0),
    "gold": (40, 750),
    "platinum": (150, 3000),
    "agency_3": (150, 5000),
    "agency_5": (250, 12000),
    "agency_10": (500, 30000),
    "trial_14": (3, 30),
}


def apply_limits(apps, schema_editor):
    MembershipPlan = apps.get_model("core", "MembershipPlan")
    for name, (research_limit, price_check_limit) in PLAN_LIMITS.items():
        MembershipPlan.objects.filter(name=name).update(
            marketplace_product_research_per_month=research_limit,
            marketplace_price_check_per_month=price_check_limit,
        )


def reverse_limits(apps, schema_editor):
    MembershipPlan = apps.get_model("core", "MembershipPlan")
    previous = {
        "silver": (0, 0),
        "gold": (150, 2000),
        "platinum": (500, 7500),
        "agency_3": (250, 3000),
        "agency_5": (750, 10000),
        "agency_10": (2000, 30000),
        "trial_14": (50, 50),
    }
    for name, (research_limit, price_check_limit) in previous.items():
        MembershipPlan.objects.filter(name=name).update(
            marketplace_product_research_per_month=research_limit,
            marketplace_price_check_per_month=price_check_limit,
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0068_single_visual_research_flow")]

    operations = [migrations.RunPython(apply_limits, reverse_limits)]
