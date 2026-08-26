from django.db import migrations


def seed_campaign(apps, schema_editor):
    Campaign = apps.get_model("core", "LifecycleEmailCampaign")
    Campaign.objects.get_or_create(
        name="14 gün sonrası abonelik hatırlatması",
        defaults={
            "subject": "Reklam performansınızı birlikte büyütelim",
            "body": "14 günlük deneyiminiz sona erdi. Reklam verilerinizi tek panelde izlemeye ve Octo önerilerinden yararlanmaya devam etmek için size uygun paketi seçebilirsiniz.\n\nSorunuz olursa yanıtlamaktan memnuniyet duyarız.",
            "cta_text": "Paketleri İncele",
            "cta_url": "https://reklamanaliz.net/pricing/",
            "delay_days": 14,
            "repeat_days": 7,
            "max_sends": 3,
            "is_active": True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0017_announcement_lifecycleemailcampaign_and_more")]
    operations = [migrations.RunPython(seed_campaign, migrations.RunPython.noop)]
