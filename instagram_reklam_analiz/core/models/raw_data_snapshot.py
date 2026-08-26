# core/models/raw_data_snapshot.py
from django.conf import settings
from django.db import models


class RawDataSnapshot(models.Model):
    """
    Platformlardan gelen ham API verisini saklar.
    """

    SOURCE_TYPE_CHOICES = [
        ("ACCOUNT", "Hesap"),
        ("CAMPAIGN", "Kampanya"),
        ("ADGROUP", "Reklam Grubu"),
        ("AD", "Reklam"),
        ("CREATIVE", "Kreatif"),
        ("METRIC", "Metrik"),
        ("COMPETITOR", "Rakip"),
        ("COMPETITOR_AD", "Rakip Reklamı"),
        ("AUDIENCE", "Kitle"),
        ("PLACEMENT", "Yerleşim"),
        ("POST", "Organik Paylaşım"),
        ("INSIGHT", "İçgörü"),
        ("ERROR", "Hata"),
        ("OTHER", "Diğer"),
    ]

    STATUS_CHOICES = [
        ("SUCCESS", "Başarılı"),
        ("FAILED", "Başarısız"),
        ("PARTIAL", "Kısmi"),
        ("SKIPPED", "Atlandı"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="raw_data_snapshots",
        null=True,
        blank=True,
        verbose_name="Üye",
    )

    platform = models.ForeignKey(
        "core.Platform",
        on_delete=models.SET_NULL,
        related_name="raw_data_snapshots",
        null=True,
        blank=True,
        verbose_name="Platform",
    )

    platform_account = models.ForeignKey(
        "core.PlatformAccount",
        on_delete=models.SET_NULL,
        related_name="raw_data_snapshots",
        null=True,
        blank=True,
        verbose_name="Platform Hesabı",
    )

    platform_connection = models.ForeignKey(
        "core.PlatformConnection",
        on_delete=models.SET_NULL,
        related_name="raw_data_snapshots",
        null=True,
        blank=True,
        verbose_name="Platform Bağlantısı",
    )

    sync_job = models.ForeignKey(
        "core.PlatformSyncJob",
        on_delete=models.SET_NULL,
        related_name="raw_data_snapshots",
        null=True,
        blank=True,
        verbose_name="Senkronizasyon İşi",
    )

    campaign = models.ForeignKey(
        "core.Campaign",
        on_delete=models.SET_NULL,
        related_name="raw_data_snapshots",
        null=True,
        blank=True,
        verbose_name="Kampanya",
    )

    ad_group = models.ForeignKey(
        "core.AdGroup",
        on_delete=models.SET_NULL,
        related_name="raw_data_snapshots",
        null=True,
        blank=True,
        verbose_name="Reklam Grubu",
    )

    ad = models.ForeignKey(
        "core.Ad",
        on_delete=models.SET_NULL,
        related_name="raw_data_snapshots",
        null=True,
        blank=True,
        verbose_name="Reklam",
    )

    creative = models.ForeignKey(
        "core.Creative",
        on_delete=models.SET_NULL,
        related_name="raw_data_snapshots",
        null=True,
        blank=True,
        verbose_name="Kreatif",
    )

    competitor = models.ForeignKey(
        "core.Competitor",
        on_delete=models.SET_NULL,
        related_name="raw_data_snapshots",
        null=True,
        blank=True,
        verbose_name="Rakip",
    )

    source_type = models.CharField(
        max_length=50,
        choices=SOURCE_TYPE_CHOICES,
        default="OTHER",
        db_index=True,
        verbose_name="Kaynak Tipi",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="SUCCESS",
        db_index=True,
        verbose_name="Durum",
    )

    external_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Harici ID",
    )

    external_parent_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Harici Üst ID",
    )

    request_url = models.TextField(blank=True, null=True, verbose_name="İstek URL")
    request_params = models.JSONField(default=dict, blank=True, verbose_name="İstek Parametreleri")
    response_status_code = models.PositiveIntegerField(null=True, blank=True, verbose_name="HTTP Durum Kodu")
    payload = models.JSONField(default=dict, blank=True, verbose_name="Ham Veri")
    error_message = models.TextField(blank=True, null=True, verbose_name="Hata Mesajı")
    checksum = models.CharField(max_length=64, blank=True, null=True, db_index=True, verbose_name="Veri İmzası")
    fetched_at = models.DateTimeField(db_index=True, verbose_name="Çekilme Tarihi")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Kayıt Tarihi")

    class Meta:
        verbose_name = "Ham Veri Anlık Görüntüsü"
        verbose_name_plural = "Ham Veri Anlık Görüntüleri"
        ordering = ["-fetched_at", "-created_at"]
        indexes = [
            models.Index(fields=["user", "source_type", "fetched_at"]),
            models.Index(fields=["platform", "source_type", "fetched_at"]),
            models.Index(fields=["platform_account", "source_type", "fetched_at"]),
            models.Index(fields=["ad", "source_type", "fetched_at"]),
            models.Index(fields=["competitor", "source_type", "fetched_at"]),
            models.Index(fields=["external_id", "source_type"]),
            models.Index(fields=["status", "fetched_at"]),
        ]

    def __str__(self):
        platform_name = self.platform.name if self.platform else "Platform"
        external = self.external_id or "-"
        return f"{platform_name} / {self.source_type} / {external}"
