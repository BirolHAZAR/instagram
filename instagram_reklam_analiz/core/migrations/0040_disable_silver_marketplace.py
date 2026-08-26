from django.db import migrations


def disable_silver_marketplace(apps, schema_editor):
    MembershipPlan = apps.get_model("core", "MembershipPlan")
    MembershipPlan.objects.filter(name="silver").update(
        marketplace_product_research_per_month=0,
        marketplace_price_check_per_month=0,
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0039_initialize_site_maintenance")]

    operations = [migrations.RunPython(disable_silver_marketplace, migrations.RunPython.noop)]
