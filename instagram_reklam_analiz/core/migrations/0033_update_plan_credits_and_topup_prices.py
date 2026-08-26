from decimal import Decimal

from django.db import migrations


PLAN_CREDITS = {
    "gold": 800,
    "platinum": 3000,
    "agency_5": 4000,
    "agency_10": 8000,
}

PACKAGE_PRICES = {
    "ai_credit_250": (Decimal("500.00"), Decimal("600.00")),
    "ai_credit_1000": (Decimal("1500.00"), Decimal("1800.00")),
}


def update_prices_and_limits(apps, schema_editor):
    Plan = apps.get_model("core", "MembershipPlan")
    Package = apps.get_model("core", "AICreditPackage")
    for name, credits in PLAN_CREDITS.items():
        Plan.objects.filter(name=name).update(ai_credits_per_month=credits)
    for name, (price, price_with_kdv) in PACKAGE_PRICES.items():
        Package.objects.filter(name=name).update(price=price, price_with_kdv=price_with_kdv)


class Migration(migrations.Migration):
    dependencies = [("core", "0032_apply_safe_ai_credit_tariffs")]
    operations = [migrations.RunPython(update_prices_and_limits, migrations.RunPython.noop)]
