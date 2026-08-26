from django.db import migrations, models


AGENCY_LIMITS = {
    "agency_3": {"clients": 5, "credits": 3000, "content": 1000, "products": 1000},
    "agency_5": {"clients": 12, "credits": 4000, "content": 2500, "products": 2500},
    "agency_10": {"clients": 30, "credits": 8000, "content": 5000, "products": 5000},
}


def apply_finite_agency_limits(apps, schema_editor):
    MembershipPlan = apps.get_model("core", "MembershipPlan")
    for name, values in AGENCY_LIMITS.items():
        MembershipPlan.objects.filter(name=name).update(
            max_instagram_accounts=values["clients"],
            max_competitors=values["clients"],
            ai_analysis_per_month=values["credits"],
            ai_recommendation_per_month=values["credits"],
            ai_analysis_per_week=0,
            ai_recommendation_per_week=0,
            max_campaign_templates=values["clients"],
            max_campaigns=values["clients"],
            max_content_fetch_count=values["content"],
            max_products=values["products"],
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0041_plan_sync_policy_fields")]

    operations = [
        migrations.AlterField(
            model_name="membershipplan",
            name="max_instagram_accounts",
            field=models.IntegerField(default=1, help_text="Platform başına değil, tüm platform hesaplarının toplamına uygulanır.", verbose_name="Maksimum toplam platform hesabı"),
        ),
        migrations.AlterField(
            model_name="membershipplan",
            name="max_competitors",
            field=models.IntegerField(default=0, help_text="0 = rakip takibi yok", verbose_name="Maksimum toplam rakip"),
        ),
        migrations.AlterField(
            model_name="membershipplan",
            name="included_seats",
            field=models.IntegerField(default=1, help_text="Ajans paketinde fiyata dahil kullanıcı/koltuk sayısıdır.", verbose_name="Ajans dahil kullanıcı/koltuk"),
        ),
        migrations.AlterField(
            model_name="membershipplan",
            name="max_team_members",
            field=models.IntegerField(default=0, verbose_name="Ajans azami kullanıcı/koltuk"),
        ),
        migrations.AlterField(
            model_name="membershipplan",
            name="max_client_accounts",
            field=models.IntegerField(default=0, help_text="Ajans paketindeki müşteri/marka çalışma alanı limitidir.", verbose_name="Ajans müşteri/marka alanı"),
        ),
        migrations.RunPython(apply_finite_agency_limits, migrations.RunPython.noop),
    ]
