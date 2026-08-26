from django.conf import settings
from django.db import models


class AudienceHistory(models.Model):
    ENTITY_TYPE_CHOICES = [
        ("CAMPAIGN", "Kampanya"),
        ("ADGROUP", "Reklam Grubu"),
        ("AD", "Reklam"),
        ("SOCIAL_POST", "Sosyal Paylaşım"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="audience_histories",
    )

    entity_type = models.CharField(max_length=30, choices=ENTITY_TYPE_CHOICES)
    entity_id = models.PositiveIntegerField()

    date = models.DateField()

    age_range = models.CharField(max_length=30, blank=True, null=True)
    gender = models.CharField(max_length=30, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    device = models.CharField(max_length=100, blank=True, null=True)

    impressions = models.BigIntegerField(default=0)
    reach = models.BigIntegerField(default=0)
    clicks = models.BigIntegerField(default=0)
    spend = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    conversions = models.DecimalField(max_digits=14, decimal_places=4, default=0)

    raw_data = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Kitle Geçmişi"
        verbose_name_plural = "Kitle Geçmişleri"
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["user", "entity_type", "entity_id"]),
            models.Index(fields=["date"]),
            models.Index(fields=["age_range", "gender"]),
            models.Index(fields=["country", "city"]),
        ]

    def __str__(self):
        return f"{self.entity_type} #{self.entity_id} - {self.date}"


class PlacementHistory(models.Model):
    ENTITY_TYPE_CHOICES = [
        ("CAMPAIGN", "Kampanya"),
        ("ADGROUP", "Reklam Grubu"),
        ("AD", "Reklam"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="placement_histories",
    )

    entity_type = models.CharField(max_length=30, choices=ENTITY_TYPE_CHOICES)
    entity_id = models.PositiveIntegerField()

    date = models.DateField()

    platform_position = models.CharField(max_length=150, blank=True, null=True)
    publisher_platform = models.CharField(max_length=100, blank=True, null=True)
    device_platform = models.CharField(max_length=100, blank=True, null=True)

    impressions = models.BigIntegerField(default=0)
    reach = models.BigIntegerField(default=0)
    clicks = models.BigIntegerField(default=0)
    spend = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    conversions = models.DecimalField(max_digits=14, decimal_places=4, default=0)

    raw_data = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Yerleşim Geçmişi"
        verbose_name_plural = "Yerleşim Geçmişleri"
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["user", "entity_type", "entity_id"]),
            models.Index(fields=["date"]),
            models.Index(fields=["platform_position"]),
            models.Index(fields=["publisher_platform"]),
        ]

    def __str__(self):
        return f"{self.entity_type} #{self.entity_id} - {self.platform_position}"


class RawPlatformData(models.Model):
    DATA_TYPE_CHOICES = [
        ("CONNECTION", "Bağlantı"),
        ("ACCOUNT", "Hesap"),
        ("CAMPAIGN", "Kampanya"),
        ("ADGROUP", "Reklam Grubu"),
        ("AD", "Reklam"),
        ("CREATIVE", "Kreatif"),
        ("SOCIAL_POST", "Sosyal Paylaşım"),
        ("METRIC", "Metrik"),
        ("COMPETITOR_AD", "Rakip Reklam"),
        ("OTHER", "Diğer"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="raw_platform_data",
    )

    platform_connection = models.ForeignKey(
        "core.PlatformConnection",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="raw_data_records",
    )

    platform_account = models.ForeignKey(
        "core.PlatformAccount",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="raw_data_records",
    )

    platform = models.CharField(max_length=50)
    data_type = models.CharField(max_length=50, choices=DATA_TYPE_CHOICES)

    external_id = models.CharField(max_length=255, blank=True, null=True)
    endpoint = models.CharField(max_length=500, blank=True, null=True)

    payload = models.JSONField(default=dict, blank=True)

    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ham Platform Verisi"
        verbose_name_plural = "Ham Platform Verileri"
        ordering = ["-fetched_at"]
        indexes = [
            models.Index(fields=["user", "platform"]),
            models.Index(fields=["data_type"]),
            models.Index(fields=["external_id"]),
            models.Index(fields=["fetched_at"]),
        ]

    def __str__(self):
        return f"{self.platform} - {self.data_type} - {self.external_id}"


class OctoScoreHistory(models.Model):
    ENTITY_TYPE_CHOICES = [
        ("CAMPAIGN", "Kampanya"),
        ("ADGROUP", "Reklam Grubu"),
        ("AD", "Reklam"),
        ("CREATIVE", "Kreatif"),
        ("SOCIAL_POST", "Sosyal Paylaşım"),
        ("ACCOUNT", "Hesap"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="octo_score_histories",
    )

    entity_type = models.CharField(max_length=30, choices=ENTITY_TYPE_CHOICES)
    entity_id = models.PositiveIntegerField()

    score = models.DecimalField(max_digits=6, decimal_places=2)
    previous_score = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)

    score_label = models.CharField(max_length=100, blank=True, null=True)

    performance_score = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    creative_score = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    budget_score = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    audience_score = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    risk_score = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    reasons = models.JSONField(default=list, blank=True)
    raw_input = models.JSONField(default=dict, blank=True)

    calculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Octo Skor Geçmişi"
        verbose_name_plural = "Octo Skor Geçmişleri"
        ordering = ["-calculated_at"]
        indexes = [
            models.Index(fields=["user", "entity_type", "entity_id"]),
            models.Index(fields=["score"]),
            models.Index(fields=["calculated_at"]),
        ]

    def __str__(self):
        return f"{self.entity_type} #{self.entity_id} - {self.score}"


class AIRecommendationHistory(models.Model):
    STATUS_CHOICES = [
        ("NEW", "Yeni"),
        ("VIEWED", "Görüldü"),
        ("APPLIED", "Uygulandı"),
        ("REJECTED", "Reddedildi"),
        ("EXPIRED", "Süresi Doldu"),
    ]

    PRIORITY_CHOICES = [
        ("LOW", "Düşük"),
        ("MEDIUM", "Orta"),
        ("HIGH", "Yüksek"),
        ("CRITICAL", "Kritik"),
    ]

    RECOMMENDATION_TYPE_CHOICES = [
        ("BUDGET", "Bütçe"),
        ("CREATIVE", "Kreatif"),
        ("AUDIENCE", "Kitle"),
        ("PLACEMENT", "Yerleşim"),
        ("COPY", "Reklam Metni"),
        ("PAUSE", "Duraklatma"),
        ("SCALE", "Ölçekleme"),
        ("WARNING", "Uyarı"),
        ("OTHER", "Diğer"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_recommendation_histories",
    )

    entity_type = models.CharField(max_length=30)
    entity_id = models.PositiveIntegerField(blank=True, null=True)

    recommendation_type = models.CharField(
        max_length=30,
        choices=RECOMMENDATION_TYPE_CHOICES,
        default="OTHER",
    )

    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="MEDIUM")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="NEW")

    title = models.CharField(max_length=255)
    message = models.TextField()
    action_text = models.CharField(max_length=255, blank=True, null=True)

    expected_impact = models.TextField(blank=True, null=True)
    confidence_score = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    before_data = models.JSONField(default=dict, blank=True)
    after_data = models.JSONField(default=dict, blank=True)

    applied_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField(blank=True, null=True)

    raw_ai_response = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "AI Öneri Geçmişi"
        verbose_name_plural = "AI Öneri Geçmişleri"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["recommendation_type"]),
            models.Index(fields=["priority"]),
            models.Index(fields=["entity_type", "entity_id"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return self.title