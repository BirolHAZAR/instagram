from django.conf import settings
from django.db import models
from django.utils import timezone

from core.fields import EncryptedTextField
from .platform import Platform


class PlatformConnection(models.Model):
    STATUS_CHOICES = [
        ("active", "Aktif"),
        ("expired", "Süresi Doldu"),
        ("error", "Hatalı"),
        ("disconnected", "Bağlantı Kesildi"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="platform_connections",
    )

    platform = models.ForeignKey(
        Platform,
        on_delete=models.CASCADE,
        related_name="connections",
    )

    name = models.CharField(max_length=200, blank=True, null=True)

    access_token = EncryptedTextField()
    refresh_token = EncryptedTextField(blank=True, null=True)
    token_expiry = models.DateTimeField(blank=True, null=True)

    scopes = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="active")

    last_sync = models.DateTimeField(blank=True, null=True)
    extra_data = models.JSONField(default=dict, blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Platform Bağlantısı"
        verbose_name_plural = "Platform Bağlantıları"
        indexes = [
            models.Index(fields=["user", "platform"]),
            models.Index(fields=["platform", "is_active"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.platform.name} - {self.name or self.user}"

    @property
    def is_token_expired(self):
        if not self.token_expiry:
            return False
        return timezone.now() >= self.token_expiry