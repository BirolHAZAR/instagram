from django.db import migrations


CATALOG = [
    # Ana kullanici islemleri: bunlar gercek kredi kesim noktalarina baglidir.
    ("creative-studio-content", "Creative Studio icerik, gorsel veya video uretimi", "Creative Studio", 10, True, True, "Ana Creative Studio uretim tarifesi."),
    ("creative-studio-regenerate", "Creative Studio medya yeniden uretimi", "Creative Studio", 10, True, True, "Varyant gorsel/video yeniden uretimi."),
    ("health-center-deep-analysis", "Saglik Merkezi toplu hesap analizi", "Toplu AI Analizi", 5, True, True, "Hesap genelindeki reklam ve metrikleri toplu analiz eder."),
    ("control-tower-analysis", "Control Tower toplu Octo analizi", "Toplu AI Analizi", 5, True, True, "Control Tower kartlari, butce ve rakip sinyallerini birlikte analiz eder."),
    ("ad-report-card-analysis", "Tek reklam AI analizi", "Tekil Analiz", 3, True, True, "Reklam Karnesi ve reklam paneli tek reklam analizi."),
    ("ad-report-card-recommendation", "Tek reklam AI onerisi", "Tekil Analiz", 3, True, True, "Tek reklam icin AI aksiyon onerisi."),
    ("campaign-center-analysis", "Tek kampanya 16 ajan analizi", "Tekil Analiz", 3, True, True, "Tek kampanyanin performans, butce, kreatif ve rakip sinyalleri."),
    ("campaign-center-recommendation", "Tek kampanya 16 ajan onerisi", "Tekil Analiz", 3, True, True, "Tek kampanya icin AI aksiyon plani."),
    ("campaign-panel-analysis", "Tek kampanya panel analizi", "Tekil Analiz", 3, True, True, "Kampanya paneli tek kampanya analizi."),
    ("campaign-panel-recommendation", "Tek kampanya panel onerisi", "Tekil Analiz", 3, True, True, "Kampanya paneli tek kampanya onerisi."),
    # Projede bulunan alt AI yetenekleri. Ustteki ana islem icinde calisirsa ikinci kez kredi kesilmez.
    ("competitor-single-analysis", "Tek rakip AI analizi", "Rakip AI", 3, True, False, "Rakip ekranindaki gercek AI endpointi henuz aktif degil; hazir tarife."),
    ("competitor-bulk-analysis", "Toplu rakip AI analizi", "Rakip AI", 5, True, False, "Coklu rakip analizi icin hazir tarife."),
    ("market-trend-analysis", "Pazar ve trend AI analizi", "Pazar AI", 5, True, False, "Su anda ana analizlerin alt ajani; ayrica kesilmez."),
    ("performance-insights", "Performans AI icgorusu", "Alt AI Ajanlari", 3, True, False, "Ana reklam/kampanya analizinin alt ajani; ayrica kesilmez."),
    ("sentiment-analysis", "Duygu AI analizi", "Alt AI Ajanlari", 3, True, False, "Ana analizin alt ajani; ayrica kesilmez."),
    ("hashtag-recommendation", "Hashtag AI onerisi", "Alt AI Ajanlari", 3, True, False, "Bagimsiz endpoint aktif edilirse kullanilacak hazir tarife."),
    ("lead-scoring", "AI potansiyel musteri puanlama", "Alt AI Ajanlari", 3, True, False, "Bagimsiz endpoint aktif edilirse kullanilacak hazir tarife."),
    ("auto-response", "AI otomatik yanit", "Alt AI Ajanlari", 3, True, False, "Bagimsiz endpoint aktif edilirse kullanilacak hazir tarife."),
    ("influencer-analysis", "Influencer AI analizi", "Alt AI Ajanlari", 3, True, False, "Bagimsiz endpoint aktif edilirse kullanilacak hazir tarife."),
    ("content-post-ideas", "AI icerik fikirleri", "Icerik AI", 10, True, False, "Creative Studio ana tarifesi icinde calisirsa ayrica kesilmez."),
    ("content-caption", "AI reklam metni ve caption", "Icerik AI", 3, True, False, "Bagimsiz metin uretimi icin hazir tarife."),
    ("vision-analysis", "Tek gorsel AI analizi", "Medya AI", 3, True, False, "Ana reklam analizinin icinde calisirsa ayrica kesilmez."),
    ("video-analysis", "Tek video AI analizi", "Medya AI", 10, True, False, "Video analizi icin hazir tarife."),
    # AI etiketi tasiyan fakat OpenAI kullanmayan aktif yerel motorlar.
    ("budget-local-optimization", "Butce optimizasyonu (yerel kurallar)", "Butce Optimizasyonu", 0, False, True, "ROAS ve harcama kurallariyla calisir; OpenAI maliyeti ve kredi kesimi yoktur."),
    ("budget-bulk-local-analysis", "Toplu butce analizi (yerel kurallar)", "Butce Optimizasyonu", 0, False, True, "Yerel metrik motoru; kredi kesmez."),
    ("campaign-local-analysis", "Yerel kampanya analizi", "Yerel Analiz", 0, False, True, "OpenAI kullanmaz; kredi kesmez."),
    ("account-local-analysis", "Yerel hesap analizi", "Yerel Analiz", 0, False, True, "OpenAI kullanmaz; kredi kesmez."),
    ("suggestions-local", "Yerel kural tabanli oneriler", "Yerel Analiz", 0, False, True, "OpenAI kullanmaz; kredi kesmez."),
]


def complete_catalog(apps, schema_editor):
    Tariff = apps.get_model("core", "AIOperationTariff")
    for key, name, category, credits, uses_openai, active, note in CATALOG:
        Tariff.objects.update_or_create(
            key=key,
            defaults={
                "display_name": name,
                "category": category,
                "credit_cost": credits,
                "model_name": "gpt-4o" if uses_openai else "",
                "uses_openai": uses_openai,
                "is_active": active,
                "note": note,
                "safety_margin_percent": 30,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0028_apply_ai_tariff_policy")]
    operations = [migrations.RunPython(complete_catalog, migrations.RunPython.noop)]
