from django.db import migrations, models


def configure_visual_prompt_tariff(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.filter(key="shopping-agent-plan").update(
        display_name="Alışveriş ajanı ultra profesyonel görsel prompt",
        model_name="gpt-5.6-sol",
        credit_cost=7,
        max_input_tokens=40000,
        max_output_tokens=3000,
        note=(
            "Ürün görselini, kullanıcı ürün adını ve virgülle ayrılmış özellikleri birlikte "
            "analiz eder; uygulanabilir profesyonel prompt ve yapılandırılmış arama planı üretir."
        ),
    )


def restore_visual_prompt_tariff(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.filter(key="shopping-agent-plan").update(
        display_name="Alışveriş ajanı görsel ve arama planı",
        model_name="gpt-5.6-terra",
        credit_cost=5,
        max_input_tokens=30000,
        max_output_tokens=2200,
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0067_shopping_browser_agent")]

    operations = [
        migrations.AlterField(
            model_name="marketplaceproductresearch",
            name="search_mode",
            field=models.CharField(
                choices=[("image_auto", "Görselden AI araştırma promptu")],
                db_index=True,
                default="image_auto",
                max_length=20,
            ),
        ),
        migrations.RunPython(configure_visual_prompt_tariff, restore_visual_prompt_tariff),
    ]
