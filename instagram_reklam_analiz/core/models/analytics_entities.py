from django.conf import settings
from django.db import models


class AnalyticsProperty(models.Model):
    PROPERTY_TYPE_CHOICES = [
        ("GA4", "Google Analytics 4"),
        ("UNKNOWN", "Bilinmiyor"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="analytics_properties",
    )

    platform_connection = models.ForeignKey(
        "core.PlatformConnection",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="analytics_properties",
    )

    platform_account = models.ForeignKey(
        "core.PlatformAccount",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="analytics_properties",
    )

    property_type = models.CharField(
        max_length=30,
        choices=PROPERTY_TYPE_CHOICES,
        default="GA4",
    )

    property_id = models.CharField(max_length=255, db_index=True)
    property_name = models.CharField(max_length=255, blank=True, null=True)

    currency = models.CharField(max_length=10, default="TRY")
    timezone = models.CharField(max_length=100, blank=True, null=True)

    raw_data = models.JSONField(default=dict, blank=True)

    last_synced_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Analytics Property"
        verbose_name_plural = "Analytics Properties"
        ordering = ["-created_at"]
        unique_together = ("platform_account", "property_id")
        indexes = [
            models.Index(fields=["user", "property_type"]),
            models.Index(fields=["property_id"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return self.property_name or self.property_id


class AnalyticsDailyMetric(models.Model):
    property = models.ForeignKey(
        "core.AnalyticsProperty",
        on_delete=models.CASCADE,
        related_name="daily_metrics",
    )

    date = models.DateField()

    sessions = models.BigIntegerField(default=0)
    users = models.BigIntegerField(default=0)
    new_users = models.BigIntegerField(default=0)

    engaged_sessions = models.BigIntegerField(default=0)
    engagement_rate = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    bounce_rate = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    average_session_duration = models.DecimalField(max_digits=14, decimal_places=4, default=0)

    screen_page_views = models.BigIntegerField(default=0)
    event_count = models.BigIntegerField(default=0)
    key_events = models.DecimalField(max_digits=14, decimal_places=4, default=0)

    conversions = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    total_revenue = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    purchase_revenue = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    transactions = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    average_purchase_revenue = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    raw_metrics = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Analytics Günlük Metrik"
        verbose_name_plural = "Analytics Günlük Metrikleri"
        unique_together = ("property", "date")
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["property", "date"]),
            models.Index(fields=["date"]),
        ]

    def __str__(self):
        return f"{self.property} - {self.date}"


class AnalyticsLandingPageMetric(models.Model):
    property = models.ForeignKey(
        "core.AnalyticsProperty",
        on_delete=models.CASCADE,
        related_name="landing_page_metrics",
    )

    date = models.DateField()

    landing_page = models.CharField(max_length=1000)
    landing_page_title = models.CharField(max_length=500, blank=True, null=True)

    sessions = models.BigIntegerField(default=0)
    users = models.BigIntegerField(default=0)
    new_users = models.BigIntegerField(default=0)

    engaged_sessions = models.BigIntegerField(default=0)
    engagement_rate = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    bounce_rate = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    conversions = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    total_revenue = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    raw_metrics = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Analytics Landing Page Metriği"
        verbose_name_plural = "Analytics Landing Page Metrikleri"
        unique_together = ("property", "date", "landing_page")
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["property", "date"]),
            models.Index(fields=["landing_page"]),
        ]

    def __str__(self):
        return f"{self.landing_page} - {self.date}"