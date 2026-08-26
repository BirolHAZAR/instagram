from django.db import migrations, models


TARIFFS = [
    ("health-center-deep-analysis", "Saglik Merkezi derin hesap analizi", "Saglik Merkezi", 3, 8000, 2000, True),
    ("control-tower-analysis", "Control Tower Octo AI analizi", "Control Tower", 3, 10000, 2500, True),
    ("ad-report-card-analysis", "Reklam Karnesi AI analizi", "Reklam Karnesi", 3, 10000, 2500, True),
    ("ad-report-card-recommendation", "Reklam Karnesi AI onerisi", "Reklam Karnesi", 2, 8000, 2000, True),
    ("campaign-center-analysis", "Campaign Center 16 ajan analizi", "Campaign Center", 3, 10000, 2500, True),
    ("campaign-center-recommendation", "Campaign Center 16 ajan onerisi", "Campaign Center", 2, 8000, 2000, True),
    ("campaign-panel-analysis", "Kampanya paneli AI analizi", "Kampanya Paneli", 2, 8000, 2000, True),
    ("campaign-panel-recommendation", "Kampanya paneli AI onerisi", "Kampanya Paneli", 1, 5000, 1200, True),
    ("creative-studio-content", "Creative Studio icerik uretimi", "Creative Studio", 3, 6000, 2000, True),
    ("creative-studio-regenerate", "Creative Studio medya yeniden uretimi", "Creative Studio", 1, 3000, 1000, True),
    ("campaign-local-analysis", "Yerel kampanya analizi", "Yerel Analiz", 0, 0, 0, False),
    ("account-local-analysis", "Yerel hesap analizi", "Yerel Analiz", 0, 0, 0, False),
    ("suggestions-local", "Yerel kural tabanli oneriler", "Yerel Analiz", 0, 0, 0, False),
]


def seed_tariffs(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    for key, name, category, credits, max_input, max_output, uses_openai in TARIFFS:
        Tariff.objects.update_or_create(
            key=key,
            defaults={
                "display_name": name,
                "category": category,
                "credit_cost": credits,
                "model_name": "gpt-4o" if uses_openai else "",
                "max_input_tokens": max_input,
                "max_output_tokens": max_output,
                "uses_openai": uses_openai,
                "is_active": True,
                "safety_margin_percent": 30,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0026_openai_token_usage_ledger")]
    operations = [
        migrations.CreateModel(
            name="AIOperationTariff",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.SlugField(max_length=120, unique=True, verbose_name="Islem anahtari")),
                ("display_name", models.CharField(max_length=160, verbose_name="Islem adi")),
                ("category", models.CharField(blank=True, default="", max_length=80, verbose_name="Kategori")),
                ("credit_cost", models.PositiveIntegerField(default=1, verbose_name="Kredi bedeli")),
                ("model_name", models.CharField(blank=True, default="", max_length=120, verbose_name="OpenAI modeli")),
                ("max_input_tokens", models.PositiveIntegerField(default=0, verbose_name="Maksimum giris token")),
                ("max_output_tokens", models.PositiveIntegerField(default=0, verbose_name="Maksimum cikis token")),
                ("max_cost_usd", models.DecimalField(decimal_places=4, default=0, max_digits=10, verbose_name="Azami maliyet USD")),
                ("safety_margin_percent", models.PositiveSmallIntegerField(default=30, verbose_name="Guvenlik marji %")),
                ("uses_openai", models.BooleanField(default=True, verbose_name="OpenAI kullanir")),
                ("is_active", models.BooleanField(default=True, verbose_name="Aktif")),
                ("note", models.TextField(blank=True, default="", verbose_name="Not")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "AI Islem Tarifesi", "verbose_name_plural": "AI Islem Tarifeleri", "ordering": ["category", "display_name"]},
        ),
        migrations.RunPython(seed_tariffs, migrations.RunPython.noop),
    ]
