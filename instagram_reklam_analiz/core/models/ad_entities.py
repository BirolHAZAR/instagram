from django.conf import settings
from django.db import models


class Campaign(models.Model):
    STATUS_CHOICES = [
        ("ACTIVE", "Aktif"),
        ("PAUSED", "Duraklatıldı"),
        ("DELETED", "Silindi"),
        ("ARCHIVED", "Arşivlendi"),
        ("UNKNOWN", "Bilinmiyor"),
    ]

    OBJECTIVE_CHOICES = [
        ("AWARENESS", "Bilinirlik"),
        ("TRAFFIC", "Trafik"),
        ("ENGAGEMENT", "Etkileşim"),
        ("LEADS", "Potansiyel Müşteri"),
        ("SALES", "Satış"),
        ("APP_PROMOTION", "Uygulama Tanıtımı"),
        ("VIDEO_VIEWS", "Video İzlenme"),
        ("MESSAGES", "Mesaj"),
        ("UNKNOWN", "Bilinmiyor"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="campaigns_v2",
    )

    platform_connection = models.ForeignKey(
        "core.PlatformConnection",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="campaigns",
    )

    platform_account = models.ForeignKey(
        "core.PlatformAccount",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="campaigns_v2",
    )

    platform_campaign_id = models.CharField(max_length=255)

    name = models.CharField(max_length=255)
    objective = models.CharField(max_length=50, choices=OBJECTIVE_CHOICES, default="UNKNOWN")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="UNKNOWN")

    daily_budget = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)
    lifetime_budget = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)
    currency = models.CharField(max_length=10, default="TRY")

    start_time = models.DateTimeField(blank=True, null=True)
    end_time = models.DateTimeField(blank=True, null=True)

    raw_data = models.JSONField(default=dict, blank=True)

    last_synced_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Kampanya"
        verbose_name_plural = "Kampanyalar"
        ordering = ["-created_at"]
        unique_together = ("platform_account", "platform_campaign_id")
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["platform_campaign_id"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return self.name


class AdGroup(models.Model):
    STATUS_CHOICES = [
        ("ACTIVE", "Aktif"),
        ("PAUSED", "Duraklatıldı"),
        ("DELETED", "Silindi"),
        ("ARCHIVED", "Arşivlendi"),
        ("UNKNOWN", "Bilinmiyor"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="adgroups_v2",
    )

    campaign = models.ForeignKey(
        "core.Campaign",
        on_delete=models.CASCADE,
        related_name="ad_groups",
    )

    platform_adgroup_id = models.CharField(max_length=255)

    name = models.CharField(max_length=255)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="UNKNOWN")

    optimization_goal = models.CharField(max_length=100, blank=True, null=True)
    billing_event = models.CharField(max_length=100, blank=True, null=True)

    daily_budget = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)
    lifetime_budget = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)

    targeting = models.JSONField(default=dict, blank=True)
    placements = models.JSONField(default=dict, blank=True)

    start_time = models.DateTimeField(blank=True, null=True)
    end_time = models.DateTimeField(blank=True, null=True)

    raw_data = models.JSONField(default=dict, blank=True)

    last_synced_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Reklam Grubu"
        verbose_name_plural = "Reklam Grupları"
        ordering = ["-created_at"]
        unique_together = ("campaign", "platform_adgroup_id")
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["platform_adgroup_id"]),
        ]

    def __str__(self):
        return self.name


class Creative(models.Model):
    CREATIVE_TYPE_CHOICES = [
        ("IMAGE", "Görsel"),
        ("VIDEO", "Video"),
        ("CAROUSEL", "Carousel"),
        ("TEXT", "Metin"),
        ("STORY", "Story"),
        ("REELS", "Reels"),
        ("UNKNOWN", "Bilinmiyor"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="creatives_v2",
    )

    platform_connection = models.ForeignKey(
        "core.PlatformConnection",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="creatives",
    )

    platform_account = models.ForeignKey(
        "core.PlatformAccount",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="creatives_v2",
    )

    platform_creative_id = models.CharField(max_length=255, blank=True, null=True)

    creative_type = models.CharField(
        max_length=30,
        choices=CREATIVE_TYPE_CHOICES,
        default="UNKNOWN",
    )

    name = models.CharField(max_length=255, blank=True, null=True)

    title = models.CharField(max_length=255, blank=True, null=True)
    body_text = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    call_to_action = models.CharField(max_length=100, blank=True, null=True)

    image_url = models.URLField(max_length=1000, blank=True, null=True)
    video_url = models.URLField(max_length=1000, blank=True, null=True)
    thumbnail_url = models.URLField(max_length=1000, blank=True, null=True)
    landing_url = models.URLField(max_length=1000, blank=True, null=True)

    media_hash = models.CharField(max_length=255, blank=True, null=True)

    raw_data = models.JSONField(default=dict, blank=True)

    first_seen_at = models.DateTimeField(blank=True, null=True)
    last_seen_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Kreatif"
        verbose_name_plural = "Kreatifler"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "creative_type"]),
            models.Index(fields=["platform_creative_id"]),
            models.Index(fields=["media_hash"]),
        ]

    def __str__(self):
        return self.name or self.title or f"Creative #{self.id}"


class Ad(models.Model):
    SOURCE_TYPE_CHOICES = [
        ("OWN", "Kendi Reklamım"),
        ("COMPETITOR", "Rakip Reklam"),
    ]

    STATUS_CHOICES = [
        ("ACTIVE", "Aktif"),
        ("PAUSED", "Duraklatıldı"),
        ("DELETED", "Silindi"),
        ("ARCHIVED", "Arşivlendi"),
        ("ENDED", "Bitti"),
        ("UNKNOWN", "Bilinmiyor"),
    ]

    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ads_v2",
    )

    source_type = models.CharField(
        max_length=20,
        choices=SOURCE_TYPE_CHOICES,
        default="OWN",
    )

    platform_connection = models.ForeignKey(
        "core.PlatformConnection",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="ads",
    )

    platform_account = models.ForeignKey(
        "core.PlatformAccount",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="ads_v2",
    )

    competitor = models.ForeignKey(
       "core.Competitor",
       on_delete=models.SET_NULL,
       null=True,
       blank=True,
       related_name="ads",
       verbose_name="Rakip",
    )

    campaign = models.ForeignKey(
        "core.Campaign",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="ads",
    )

    ad_group = models.ForeignKey(
        "core.AdGroup",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="ads",
    )

    creative = models.ForeignKey(
        "core.Creative",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="ads",
    )


    platform_ad_id = models.CharField(max_length=255, blank=True, null=True)
    ad_library_id = models.CharField(max_length=255, blank=True, null=True)

    name = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="UNKNOWN")

    ad_format = models.CharField(max_length=100, blank=True, null=True)
    objective = models.CharField(max_length=100, blank=True, null=True)

    headline = models.CharField(max_length=255, blank=True, null=True)
    primary_text = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    call_to_action = models.CharField(max_length=100, blank=True, null=True)
    landing_url = models.URLField(max_length=1000, blank=True, null=True)

    preview_image_url = models.URLField(max_length=1000, blank=True, null=True)
    preview_video_url = models.URLField(max_length=1000, blank=True, null=True)

    first_seen_at = models.DateTimeField(blank=True, null=True)
    last_seen_at = models.DateTimeField(blank=True, null=True)

    started_at = models.DateTimeField(blank=True, null=True)
    ended_at = models.DateTimeField(blank=True, null=True)

    raw_data = models.JSONField(default=dict, blank=True)

    last_synced_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Reklam"
        verbose_name_plural = "Reklamlar"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "source_type"]),
            models.Index(fields=["status"]),
            models.Index(fields=["platform_ad_id"]),
            models.Index(fields=["ad_library_id"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return self.name or self.headline or f"Ad #{self.id}"