from django.db import migrations


def expand_prompt_budget(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.filter(key="creative-studio-prompt").update(
        max_output_tokens=4000,
        note=(
            "Sol ile en fazla 10 referans görselin ürün analizi ve üç yaratıcı yönü. "
            "Katı JSON şeması ve 4000 token güvenli çıktı bütçesi kullanılır."
        ),
    )


def restore_prompt_budget(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.filter(key="creative-studio-prompt").update(max_output_tokens=2200)


class Migration(migrations.Migration):
    dependencies = [("core", "0064_creative_studio_model_routing")]
    operations = [
        migrations.RunPython(expand_prompt_budget, restore_prompt_budget),
    ]
