# core/models/competitor.py
from django.conf import settings
from django.db import models


class Competitor(models.Model):
    """
    Üyeye ait rakip firma / rakip hesap profili.

    Not:
    - Rakibin kendisi burada tutulur.
    - Rakibe ait reklamlar core.Ad tablosunda tutulur.
    - Rakip reklamları Ad.source_type='COMPETITOR' ve Ad.competitor_id ile bağlanır.
    """

    CATEGORY_CHOICES = [
        ("direct", "Doğrudan Rakip"),
        ("indirect", "Dolaylı Rakip"),
        ("potential", "Potansiyel Rakip"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="competitors",
        verbose_name="Üye",
    )

    platform = models.ForeignKey(
        "core.Platform",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="competitors",
        verbose_name="Platform",
    )

    platform_account = models.ForeignKey(
        "core.PlatformAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="competitors",
        verbose_name="Bağlı Platform Hesabı",
        help_text="Bu rakibin hangi üyenin hangi platform hesabı kapsamında takip edildiğini gösterir.",
    )

    agency_client = models.ForeignKey(
        "core.AgencyClient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="competitors",
        verbose_name="Ajans Müşterisi",
        help_text="Ajans panelinde bu rakibin bağlı olduğu müşteri/marka.",
    )

    platform_identifier = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name="Platform Hesap Adı / ID",
    )

    name = models.CharField(
        max_length=255,
        verbose_name="Rakip Adı",
    )

    website = models.URLField(
        blank=True,
        null=True,
        verbose_name="Web Sitesi",
    )

    category = models.CharField(
        max_length=30,
        choices=CATEGORY_CHOICES,
        default="direct",
        verbose_name="Rakip Kategorisi",
    )

    description = models.TextField(
        blank=True,
        null=True,
        verbose_name="Açıklama / Not",
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="Aktif İzleniyor",
    )

    total_ads_seen = models.PositiveIntegerField(
        default=0,
        verbose_name="Görülen Reklam Sayısı",
    )

    last_seen_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Son Görülme",
    )

    raw_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Ham Veri",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Oluşturulma Tarihi",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Güncellenme Tarihi",
    )

    class Meta:
        verbose_name = "Rakip"
        verbose_name_plural = "Rakipler"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "platform", "platform_account", "platform_identifier"],
                name="uniq_competitor_user_platform_account_identifier",
            )
        ]
        indexes = [
            models.Index(fields=["user", "platform", "is_active"]),
            models.Index(fields=["user", "platform_account", "is_active"]),
            models.Index(fields=["agency_client", "is_active"]),
            models.Index(fields=["platform_identifier"]),
        ]

    def __str__(self):
        platform_name = self.platform.name if self.platform else "Platform"
        return f"{self.name} - {platform_name}"
