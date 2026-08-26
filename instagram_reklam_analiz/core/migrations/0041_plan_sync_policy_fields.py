from django.db import migrations, models


SYNC_VALUES = {
    "silver": (10080, 10080, 10080, 10080, 1000),
    "gold": (1440, 1440, 1440, 1440, 2000),
    "platinum": (120, 120, 120, 120, 5000),
    "agency_3": (1440, 1440, 1440, 1440, 3000),
    "agency_5": (360, 360, 360, 360, 5000),
    "agency_10": (120, 120, 120, 120, 10000),
    "trial_14": (1440, 1440, 1440, 1440, 500),
}


def seed_plan_sync_values(apps, schema_editor):
    MembershipPlan = apps.get_model("core", "MembershipPlan")
    for name, values in SYNC_VALUES.items():
        MembershipPlan.objects.filter(name=name).update(
            ad_sync_interval_minutes=values[0],
            competitor_sync_interval_minutes=values[1],
            organic_sync_interval_minutes=values[2],
            marketplace_sync_interval_minutes=values[3],
            max_sync_records=values[4],
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0040_disable_silver_marketplace")]

    operations = [
        migrations.AddField(model_name="membershipplan", name="ad_sync_interval_minutes", field=models.PositiveIntegerField(default=1440, verbose_name="Reklam güncelleme aralığı (dk)")),
        migrations.AddField(model_name="membershipplan", name="competitor_sync_interval_minutes", field=models.PositiveIntegerField(default=1440, verbose_name="Rakip güncelleme aralığı (dk)")),
        migrations.AddField(model_name="membershipplan", name="organic_sync_interval_minutes", field=models.PositiveIntegerField(default=1440, verbose_name="Post güncelleme aralığı (dk)")),
        migrations.AddField(model_name="membershipplan", name="marketplace_sync_interval_minutes", field=models.PositiveIntegerField(default=1440, verbose_name="Ürün/fiyat güncelleme aralığı (dk)")),
        migrations.AddField(model_name="membershipplan", name="allow_manual_ad_sync", field=models.BooleanField(default=True, verbose_name="Manuel reklam yenileme")),
        migrations.AddField(model_name="membershipplan", name="allow_manual_competitor_sync", field=models.BooleanField(default=True, verbose_name="Manuel rakip yenileme")),
        migrations.AddField(model_name="membershipplan", name="allow_manual_organic_sync", field=models.BooleanField(default=True, verbose_name="Manuel post yenileme")),
        migrations.AddField(model_name="membershipplan", name="allow_manual_marketplace_sync", field=models.BooleanField(default=True, verbose_name="Manuel ürün/fiyat yenileme")),
        migrations.AddField(model_name="membershipplan", name="max_sync_records", field=models.PositiveIntegerField(default=1000, verbose_name="Çalışma başına azami kayıt")),
        migrations.CreateModel(name="PlanAuthorizationPolicy", fields=[], options={"verbose_name": "Plan yetki ve limit tablosu", "verbose_name_plural": "Plan yetki ve limit tablosu", "proxy": True, "indexes": [], "constraints": []}, bases=("core.membershipplan",)),
        migrations.RunPython(seed_plan_sync_values, migrations.RunPython.noop),
    ]
