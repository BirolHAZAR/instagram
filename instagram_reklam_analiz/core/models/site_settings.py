from django.conf import settings
from django.core.cache import cache
from django.db import models


MAINTENANCE_CACHE_KEY = "site-maintenance-settings-v1"


class SiteMaintenance(models.Model):
    """Admin-controlled singleton for putting all public pages into maintenance mode."""

    is_active = models.BooleanField(default=False, verbose_name="Bakım modu aktif")
    title = models.CharField(
        max_length=160,
        default="Kısa Bir Bakım Molası",
        verbose_name="Sayfa başlığı",
    )
    message = models.TextField(
        default=(
            "Size daha iyi hizmet verebilmek için sistemimizde planlı bir çalışma "
            "yapıyoruz. Kısa süre içinde yeniden buradayız."
        ),
        verbose_name="Açıklama",
    )
    estimated_end_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Tahmini bitiş zamanı",
    )
    contact_email = models.EmailField(blank=True, verbose_name="İletişim e-postası")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="maintenance_settings_updates",
        verbose_name="Son güncelleyen",
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Son güncelleme")

    class Meta:
        verbose_name = "Bakım modu"
        verbose_name_plural = "Bakım modu"

    def __str__(self):
        return "Bakım modu: Açık" if self.is_active else "Bakım modu: Kapalı"

    def save(self, *args, **kwargs):
        # There can be only one setting row, including when fixtures are loaded.
        self.pk = 1
        # Manager.create() passes force_insert; after the bootstrap migration the
        # singleton already exists, so every subsequent save must be an update.
        kwargs.pop("force_insert", None)
        result = super().save(*args, **kwargs)
        cache.delete(MAINTENANCE_CACHE_KEY)
        return result

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        cache.delete(MAINTENANCE_CACHE_KEY)
        return result
