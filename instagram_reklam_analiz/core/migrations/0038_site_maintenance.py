import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0037_activate_all_ai_tariffs"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SiteMaintenance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=False, verbose_name="Bakım modu aktif")),
                ("title", models.CharField(default="Kısa Bir Bakım Molası", max_length=160, verbose_name="Sayfa başlığı")),
                ("message", models.TextField(default="Size daha iyi hizmet verebilmek için sistemimizde planlı bir çalışma yapıyoruz. Kısa süre içinde yeniden buradayız.", verbose_name="Açıklama")),
                ("estimated_end_at", models.DateTimeField(blank=True, null=True, verbose_name="Tahmini bitiş zamanı")),
                ("contact_email", models.EmailField(blank=True, max_length=254, verbose_name="İletişim e-postası")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Son güncelleme")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="maintenance_settings_updates", to=settings.AUTH_USER_MODEL, verbose_name="Son güncelleyen")),
            ],
            options={"verbose_name": "Bakım modu", "verbose_name_plural": "Bakım modu"},
        ),
    ]
