from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


SOURCES = [
    ("trendyol", "Trendyol", "https://www.trendyol.com", ["trendyol.com"], 10),
    ("hepsiburada", "Hepsiburada", "https://www.hepsiburada.com", ["hepsiburada.com"], 20),
    ("amazon-tr", "Amazon Türkiye", "https://www.amazon.com.tr", ["amazon.com.tr"], 30),
    ("n11", "N11", "https://www.n11.com", ["n11.com"], 40),
    ("pazarama", "Pazarama", "https://www.pazarama.com", ["pazarama.com"], 50),
    ("ciceksepeti", "ÇiçekSepeti", "https://www.ciceksepeti.com", ["ciceksepeti.com"], 60),
    ("etsy", "Etsy", "https://www.etsy.com", ["etsy.com"], 70),
    ("aliexpress", "AliExpress", "https://www.aliexpress.com", ["aliexpress.com"], 80),
    ("sahibinden", "Sahibinden", "https://www.sahibinden.com", ["sahibinden.com"], 90),
    ("akakce", "Akakçe", "https://www.akakce.com", ["akakce.com"], 100),
    ("cimri", "Cimri", "https://www.cimri.com", ["cimri.com"], 110),
]


def seed_shopping_agent(apps, schema_editor):
    Marketplace = apps.get_model("core", "Marketplace")
    Tariff = apps.get_model("core", "AIOperationTariff")
    for code, name, website, domains, priority in SOURCES:
        Marketplace.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "website_url": website,
                "allowed_domains": domains,
                "research_enabled": True,
                "browser_verification_enabled": code in {"trendyol", "hepsiburada", "amazon-tr", "n11"},
                "search_priority": priority,
                "max_results": 10,
                "timeout_seconds": 20,
                "credit_multiplier": Decimal("1.00"),
                "is_active": True,
                "order": priority,
            },
        )
    tariffs = [
        (
            "shopping-agent-plan",
            "Alışveriş ajanı görsel ve arama planı",
            "gpt-5.6-terra",
            5,
            30000,
            2200,
            "Görsel analizi, profesyonel prompt ve yapılandırılmış arama planı.",
        ),
        (
            "shopping-agent-prefilter",
            "Alışveriş ajanı toplu ön eleme",
            "gpt-5.6-luna",
            3,
            24000,
            2400,
            "Çok sayıda ürün adayını düşük maliyetle puanlar ve eler.",
        ),
        (
            "shopping-agent-match",
            "Alışveriş ajanı ayrıntılı eşleştirme",
            "gpt-5.6-terra",
            4,
            24000,
            2400,
            "En güçlü ürün adaylarını görsel ve metin sinyalleriyle eşleştirir.",
        ),
        (
            "shopping-agent-final-qa",
            "Alışveriş ajanı son kalite kontrolü",
            "gpt-5.6-sol",
            2,
            18000,
            1800,
            "Belirsiz sonuçlar ve orijinallik iddiaları için son kontrol.",
        ),
    ]
    for key, display_name, model_name, credit_cost, max_input, max_output, note in tariffs:
        Tariff.objects.update_or_create(
            key=key,
            defaults={
                "display_name": display_name,
                "category": "AI Alışveriş Ajanı",
                "credit_cost": credit_cost,
                "model_name": model_name,
                "max_input_tokens": max_input,
                "max_output_tokens": max_output,
                "max_calls": 1,
                "cache_timeout_seconds": 0,
                "max_cost_usd": Decimal("0.0000"),
                "safety_margin_percent": 30,
                "uses_openai": True,
                "is_active": True,
                "note": note,
            },
        )


def reverse_seed(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    Tariff.objects.filter(key__startswith="shopping-agent-").delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0066_reprice_creative_studio_premium_flow")]

    operations = [
        migrations.AddField(
            model_name="marketplace",
            name="allowed_domains",
            field=models.JSONField(blank=True, default=list, verbose_name="İzinli alan adları"),
        ),
        migrations.AddField(
            model_name="marketplace",
            name="browser_verification_enabled",
            field=models.BooleanField(db_index=True, default=False, verbose_name="Tarayıcı doğrulaması"),
        ),
        migrations.AddField(
            model_name="marketplace",
            name="categories",
            field=models.JSONField(blank=True, default=list, verbose_name="Öncelikli kategoriler"),
        ),
        migrations.AddField(
            model_name="marketplace",
            name="credit_multiplier",
            field=models.DecimalField(decimal_places=2, default=1, max_digits=5, verbose_name="Maliyet çarpanı"),
        ),
        migrations.AddField(
            model_name="marketplace",
            name="max_results",
            field=models.PositiveIntegerField(default=10, verbose_name="Azami sonuç"),
        ),
        migrations.AddField(
            model_name="marketplace",
            name="research_enabled",
            field=models.BooleanField(db_index=True, default=True, verbose_name="Araştırmada kullan"),
        ),
        migrations.AddField(
            model_name="marketplace",
            name="search_priority",
            field=models.PositiveIntegerField(default=100, verbose_name="Arama önceliği"),
        ),
        migrations.AddField(
            model_name="marketplace",
            name="search_url_template",
            field=models.CharField(blank=True, default="", help_text="Arama terimi için {query} yer tutucusunu kullanın.", max_length=500, verbose_name="Arama URL şablonu"),
        ),
        migrations.AddField(
            model_name="marketplace",
            name="timeout_seconds",
            field=models.PositiveIntegerField(default=20, verbose_name="Zaman aşımı (sn)"),
        ),
        migrations.AddField(
            model_name="marketplace",
            name="website_url",
            field=models.URLField(blank=True, default="", verbose_name="Mağaza ana adresi"),
        ),
        migrations.AddField(
            model_name="marketplaceproductresearch",
            name="celery_task_id",
            field=models.CharField(blank=True, db_index=True, default="", max_length=80),
        ),
        migrations.AddField(
            model_name="marketplaceproductresearch",
            name="current_step",
            field=models.CharField(blank=True, default="", max_length=180),
        ),
        migrations.AddField(
            model_name="marketplaceproductresearch",
            name="finished_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="marketplaceproductresearch",
            name="generated_prompt",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="marketplaceproductresearch",
            name="parsed_intent",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="marketplaceproductresearch",
            name="progress_percent",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="marketplaceproductresearch",
            name="search_mode",
            field=models.CharField(
                choices=[
                    ("image_auto", "Yalnızca görsel - promptu AI oluştursun"),
                    ("image_prompt", "Görsel ve kullanıcı talimatı"),
                ],
                db_index=True,
                default="image_prompt",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="marketplaceproductresearch",
            name="search_plan",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="marketplaceproductresearch",
            name="selected_marketplaces",
            field=models.ManyToManyField(blank=True, related_name="product_researches", to="core.marketplace"),
        ),
        migrations.AddField(
            model_name="marketplaceproductresearch",
            name="started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="marketplaceproductresearch",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Taslak"), ("queued", "Kuyrukta"), ("analyzing", "Görsel ve talimat analiz ediliyor"),
                    ("searching", "Pazaryerleri aranıyor"), ("verifying", "Ürün sayfaları doğrulanıyor"),
                    ("matching", "Sonuçlar eşleştiriliyor"), ("completed", "Tamamlandı"),
                    ("partial", "Kısmi tamamlandı"), ("failed", "Hatalı"),
                ],
                db_index=True,
                default="draft",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="MarketplaceProductResearchResult",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(blank=True, default="", max_length=50)),
                ("title", models.CharField(max_length=500)),
                ("product_url", models.URLField(max_length=2000)),
                ("image_url", models.URLField(blank=True, default="", max_length=2000)),
                ("seller_name", models.CharField(blank=True, default="", max_length=255)),
                ("price", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("shipping_price", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("total_price", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("currency", models.CharField(default="TRY", max_length=10)),
                ("in_stock", models.BooleanField(blank=True, null=True)),
                ("variant", models.CharField(blank=True, default="", max_length=180)),
                ("match_score", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("visual_score", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("authenticity_score", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("is_eligible", models.BooleanField(db_index=True, default=True)),
                ("verification_status", models.CharField(blank=True, db_index=True, default="discovered", max_length=30)),
                ("match_explanation", models.JSONField(blank=True, default=list)),
                ("authenticity_evidence", models.JSONField(blank=True, default=list)),
                ("raw_data", models.JSONField(blank=True, default=dict)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("marketplace", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="research_results", to="core.marketplace")),
                ("research", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="normalized_results", to="core.marketplaceproductresearch")),
            ],
            options={
                "verbose_name": "Ürün Araştırma Sonucu",
                "verbose_name_plural": "Ürün Araştırma Sonuçları",
                "ordering": ["total_price", "-match_score", "id"],
                "indexes": [
                    models.Index(fields=["research", "is_eligible"], name="core_market_researc_d6326a_idx"),
                    models.Index(fields=["marketplace", "verification_status"], name="core_market_marketp_52eb5a_idx"),
                ],
            },
        ),
        migrations.RunPython(seed_shopping_agent, reverse_seed),
    ]
