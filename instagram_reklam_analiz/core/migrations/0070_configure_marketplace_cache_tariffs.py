from django.db import migrations


def configure_cache_timeouts(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    timeouts = {
        "shopping-agent-plan": 60 * 60 * 24 * 30,
        "shopping-agent-prefilter": 60 * 60 * 24 * 7,
        "shopping-agent-match": 60 * 60 * 24 * 7,
        "shopping-agent-final-qa": 0,
        "vision-analysis": 60 * 60 * 24 * 30,
    }
    for key, timeout in timeouts.items():
        Tariff.objects.filter(key=key).update(cache_timeout_seconds=timeout)


def clear_cache_timeouts(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.filter(
        key__in=[
            "shopping-agent-plan",
            "shopping-agent-prefilter",
            "shopping-agent-match",
            "shopping-agent-final-qa",
            "vision-analysis",
        ]
    ).update(cache_timeout_seconds=0)


class Migration(migrations.Migration):
    dependencies = [("core", "0069_rebalance_marketplace_entitlements")]

    operations = [migrations.RunPython(configure_cache_timeouts, clear_cache_timeouts)]
