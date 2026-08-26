from django.conf import settings
from django.db import models


class PlatformSyncJob(models.Model):
    STATUS_CHOICES = [
        ("pending", "Bekliyor"),
        ("running", "Çalışıyor"),
        ("completed", "Tamamlandı"),
        ("failed", "Hatalı"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="platform_sync_jobs",
    )

    platform_account = models.ForeignKey(
        "core.PlatformAccount",
        on_delete=models.CASCADE,
        related_name="sync_jobs",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
    )

    progress = models.PositiveSmallIntegerField(default=0)

    message = models.CharField(max_length=255, blank=True, null=True)

    campaigns_count = models.PositiveIntegerField(default=0)
    adgroups_count = models.PositiveIntegerField(default=0)
    ads_count = models.PositiveIntegerField(default=0)
    creatives_count = models.PositiveIntegerField(default=0)
    metrics_count = models.PositiveIntegerField(default=0)

    days_back = models.PositiveIntegerField(default=30)

    error_message = models.TextField(blank=True, null=True)
    result = models.JSONField(default=dict, blank=True)

    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Platform Senkronizasyon İşi"
        verbose_name_plural = "Platform Senkronizasyon İşleri"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.platform_account} - {self.status}"