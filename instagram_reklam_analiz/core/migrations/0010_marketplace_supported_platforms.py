from django.db import migrations


SUPPORTED_MARKETPLACES = [
    ("trendyol", "Trendyol", 1),
    ("hepsiburada", "Hepsiburada", 2),
    ("n11", "n11", 3),
]


def seed_supported_marketplaces(apps, schema_editor):
    Marketplace = apps.get_model("core", "Marketplace")
    supported_codes = [code for code, _, _ in SUPPORTED_MARKETPLACES]

    Marketplace.objects.exclude(code__in=supported_codes).update(is_active=False)
    for code, name, order in SUPPORTED_MARKETPLACES:
        Marketplace.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "order": order,
                "is_active": True,
            },
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_demo_requests"),
    ]

    operations = [
        migrations.RunPython(seed_supported_marketplaces, noop_reverse),
    ]
