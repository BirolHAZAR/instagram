from django.db import migrations, models


def configure_tariff_budgets(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.filter(key__in=[
        "control-tower-analysis", "health-center-deep-analysis",
        "campaign-panel-analysis", "campaign-panel-recommendation",
        "campaign-center-analysis", "campaign-center-recommendation",
        "ad-report-card-analysis", "ad-report-card-recommendation",
        "competitor-single-analysis", "creative-studio-content",
    ]).update(max_calls=4)
    Tariff.objects.filter(key="control-tower-analysis").update(cache_timeout_seconds=21600)
    Tariff.objects.filter(key="health-center-deep-analysis").update(cache_timeout_seconds=21600)


class Migration(migrations.Migration):
    dependencies = [("core", "0050_make_demo_request_company_optional")]
    operations = [
        migrations.AddField(
            model_name="aioperationtariff", name="max_calls",
            field=models.PositiveIntegerField(default=1, verbose_name="Islem basina azami AI cagrisi"),
        ),
        migrations.AddField(
            model_name="aioperationtariff", name="cache_timeout_seconds",
            field=models.PositiveIntegerField(default=0, verbose_name="Sonuc onbellegi (saniye)"),
        ),
        migrations.AddField(
            model_name="openaitokenusageledger", name="operation_key",
            field=models.CharField(blank=True, db_index=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="openaitokenusageledger", name="request_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="openaitokenusageledger", name="usage_kind",
            field=models.CharField(blank=True, db_index=True, default="customer_usage", max_length=40),
        ),
        migrations.RunPython(configure_tariff_budgets, migrations.RunPython.noop),
    ]
