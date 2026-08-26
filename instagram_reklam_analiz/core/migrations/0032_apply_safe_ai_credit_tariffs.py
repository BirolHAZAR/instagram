from django.db import migrations


TARIFFS = {
    "creative-studio-content": ("Creative Studio yalnız metin üretimi", 22, 32000, 12000),
    "creative-studio-image": ("Creative Studio metin ve görsel üretimi", 30, 32000, 12000),
    "creative-studio-regenerate": ("Creative Studio görsel yeniden üretimi", 30, 16000, 3000),
    "creative-studio-video": ("Creative Studio video üretimi veya yenileme", 160, 24000, 4000),
    "health-center-deep-analysis": ("Sağlık Merkezi toplu hesap analizi", 15, 32000, 5600),
    "control-tower-analysis": ("Control Tower toplu Octo analizi", 15, 32000, 5600),
    "ad-report-card-analysis": ("Tek reklam AI analizi", 13, 24000, 5600),
    "ad-report-card-recommendation": ("Tek reklam AI önerisi", 13, 24000, 5600),
    "campaign-center-analysis": ("Tek kampanya AI analizi", 13, 24000, 5600),
    "campaign-center-recommendation": ("Tek kampanya AI önerisi", 13, 24000, 5600),
    "campaign-panel-analysis": ("Tek kampanya panel analizi", 15, 28000, 6500),
    "campaign-panel-recommendation": ("Tek kampanya panel önerisi", 15, 28000, 6500),
    "competitor-single-analysis": ("Tek rakip AI analizi", 13, 24000, 5600),
}


def apply_tariffs(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    bulk = {"health-center-deep-analysis", "control-tower-analysis"}
    for key, (name, credits, max_input, max_output) in TARIFFS.items():
        Tariff.objects.update_or_create(
            key=key,
            defaults={
                "display_name": name,
                "category": "Creative Studio" if key.startswith("creative-studio") else ("Toplu AI Analizi" if key in bulk else "Tekil Analiz"),
                "credit_cost": credits,
                "model_name": "gpt-4o",
                "max_input_tokens": max_input,
                "max_output_tokens": max_output,
                "safety_margin_percent": 30,
                "uses_openai": True,
                "is_active": True,
                "note": "Gerçek kullanıcı işlemine bağlı; kredi ve token takibi aktif güvenli tarife.",
            },
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0031_set_ai_tariff_token_limits")]
    operations = [migrations.RunPython(apply_tariffs, migrations.RunPython.noop)]
