from django.db import migrations


def apply_premium_pricing(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.filter(key="creative-studio-prompt").update(
        credit_cost=10,
        note=(
            "Sol ürün analizi, en fazla 10 referans görsel ve üç yaratıcı yön. "
            "Tam görselli akışın 200 kontörlük fiyatına dahildir."
        ),
    )
    Tariff.objects.filter(key="creative-studio-image").update(
        credit_cost=190,
        note=(
            "Terra strateji/metin, GPT Image 2 görsel üretimi ve tek Sol final kalite "
            "kontrolünü kapsayan premium Creative Studio üretim bedeli."
        ),
    )
    Tariff.objects.filter(key="creative-studio-final-review").update(
        credit_cost=0,
        note="Tek Sol final kalite kontrolü 190 kontörlük görselli üretim tarifesine dahildir.",
    )


def restore_previous_pricing(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.filter(key="creative-studio-prompt").update(credit_cost=6)
    Tariff.objects.filter(key="creative-studio-image").update(credit_cost=160)
    Tariff.objects.filter(key="creative-studio-final-review").update(credit_cost=0)


class Migration(migrations.Migration):
    dependencies = [("core", "0065_expand_creative_prompt_output_budget")]
    operations = [
        migrations.RunPython(apply_premium_pricing, restore_previous_pricing),
    ]
