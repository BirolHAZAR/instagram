from django.db import migrations


def configure_creative_models(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.filter(key="creative-studio-prompt").update(
        model_name="gpt-5.6-sol",
        max_input_tokens=30000,
        max_output_tokens=2200,
        max_calls=1,
        cache_timeout_seconds=3600,
        note=(
            "Sol ile en fazla 10 referans görselin ürün analizi ve üç yaratıcı yönü. "
            "İlk dört görsel yüksek, kalanlar düşük detayla maliyet kontrollü işlenir."
        ),
    )
    Tariff.objects.filter(key="creative-studio-content").update(
        model_name="gpt-5.6-terra",
        note="Ara kreatif strateji, metin ve varyant üretimi için maliyet dengeli Terra rotası.",
    )
    Tariff.objects.filter(key="creative-studio-image").update(
        model_name="gpt-image-2",
        note="Creative Studio görsel üretimi ve yüksek sadakatli düzenleme için GPT Image 2.",
    )
    Tariff.objects.update_or_create(
        key="creative-studio-final-review",
        defaults={
            "display_name": "Creative Studio final kalite kontrolü",
            "category": "Creative Studio",
            "credit_cost": 0,
            "model_name": "gpt-5.6-sol",
            "max_input_tokens": 12000,
            "max_output_tokens": 2200,
            "max_calls": 1,
            "cache_timeout_seconds": 0,
            "max_cost_usd": 0,
            "safety_margin_percent": 25,
            "uses_openai": True,
            "is_active": True,
            "note": "Bütün Terra varyantlarını tek Sol çağrısında denetler; ayrı üye kredisi tüketmez.",
        },
    )


def reverse_creative_models(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.filter(key="creative-studio-prompt").update(
        model_name="", max_input_tokens=12000, max_output_tokens=1800,
        max_calls=1, cache_timeout_seconds=0,
    )
    Tariff.objects.filter(key__in=["creative-studio-content", "creative-studio-image"]).update(
        model_name="",
    )
    Tariff.objects.filter(key="creative-studio-final-review").delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0063_creative_studio_prompt_tariff")]
    operations = [
        migrations.RunPython(configure_creative_models, reverse_creative_models),
    ]
