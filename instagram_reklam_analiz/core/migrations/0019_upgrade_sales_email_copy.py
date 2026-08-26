from django.db import migrations, models


def upgrade_default_campaign(apps, schema_editor):
    Campaign = apps.get_model("core", "LifecycleEmailCampaign")
    Campaign.objects.filter(name="14 gün sonrası abonelik hatırlatması").update(
        subject="Reklam bütçeniz daha verimli çalışmaya hazır",
        body="14 günlük deneyiminiz tamamlandı. Şimdi reklam verilerinizi gerçek büyüme kararlarına dönüştürme zamanı.\n\nDağınık raporlar yerine tüm hesaplarınızı tek panelde izleyin; bütçe, ROAS ve kreatif kararlarında Octo AI desteğiyle daha hızlı hareket edin.",
        cta_text="Planınızı Seçin",
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0018_seed_default_lifecycle_email")]
    operations = [
        migrations.RunPython(upgrade_default_campaign, migrations.RunPython.noop),
        migrations.AlterField(model_name="lifecycleemailcampaign", name="subject", field=models.CharField(default="Reklam bütçeniz daha verimli çalışmaya hazır", max_length=200)),
        migrations.AlterField(model_name="lifecycleemailcampaign", name="body", field=models.TextField(default="14 günlük deneyiminiz tamamlandı. Şimdi reklam verilerinizi gerçek büyüme kararlarına dönüştürme zamanı.\n\nDağınık raporlar yerine tüm hesaplarınızı tek panelde izleyin; bütçe, ROAS ve kreatif kararlarında Octo AI desteğiyle daha hızlı hareket edin.")),
        migrations.AlterField(model_name="lifecycleemailcampaign", name="cta_text", field=models.CharField(default="Planınızı Seçin", max_length=80)),
    ]
