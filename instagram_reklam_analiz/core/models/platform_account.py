from django.db import models
from core.fields import EncryptedTextField
from django.contrib.auth import get_user_model
from .platform import Platform


User = get_user_model()

class PlatformAccount(models.Model):    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='platform_accounts')
    platform = models.ForeignKey(Platform, on_delete=models.CASCADE, related_name='accounts')
    connection = models.ForeignKey(
        "core.PlatformConnection",
        on_delete=models.CASCADE,
        related_name="accounts",
        blank=True,
        null=True,
    )
    agency_client = models.ForeignKey(
        "core.AgencyClient",
        on_delete=models.SET_NULL,
        related_name="platform_accounts",
        blank=True,
        null=True,
        help_text="Ajans panelinde bu hesabın bağlı olduğu müşteri/marka.",
    )
    account_id = models.CharField(max_length=100, db_index=True)   # artık zorunlu, null=False
    account_name = models.CharField(max_length=200, blank=True, null=True)
    
    access_token = EncryptedTextField()       # veritabanında şifreli tutulur
    refresh_token = EncryptedTextField(blank=True, null=True)
    token_expiry = models.DateTimeField(blank=True, null=True)
    
    is_active = models.BooleanField(default=True)
    last_sync = models.DateTimeField(blank=True, null=True)
    extra_data = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['user', 'platform', 'account_id']]   # aynı hesap tekrar edemez
        indexes = [
            models.Index(fields=['platform', 'is_active']),
            models.Index(fields=['user', 'platform']),
            models.Index(fields=['agency_client', 'platform']),
        ]
        verbose_name = "Platform Hesabı"
        verbose_name_plural = "Platform Hesapları"

    def __str__(self):
        return f"{self.platform.name} - {self.account_name or self.account_id}"

