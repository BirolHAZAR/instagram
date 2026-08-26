from django.conf import settings
from django.db import models


class Influencer(models.Model):
    PLATFORM_STATUS_CHOICES = [
        ("manual", "Manuel"),
        ("api", "API"),
        ("import", "Import"),
    ]

    CATEGORY_CHOICES = [
        ("fashion", "Moda"),
        ("beauty", "Güzellik"),
        ("food", "Yeme İçme"),
        ("travel", "Seyahat"),
        ("technology", "Teknoloji"),
        ("gaming", "Gaming"),
        ("fitness", "Fitness"),
        ("parenting", "Anne Çocuk"),
        ("business", "İş Dünyası"),
        ("education", "Eğitim"),
        ("lifestyle", "Lifestyle"),
        ("other", "Diğer"),
    ]

    platform = models.ForeignKey(
        "core.Platform",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="influencers",
    )
    handle = models.CharField(max_length=255, db_index=True)
    normalized_handle = models.CharField(max_length=255, db_index=True)
    display_name = models.CharField(max_length=255)
    profile_url = models.URLField(max_length=1000, blank=True, null=True)
    avatar_url = models.URLField(max_length=1000, blank=True, null=True)

    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, default="other", db_index=True)
    country = models.CharField(max_length=80, blank=True, null=True, db_index=True)
    city = models.CharField(max_length=80, blank=True, null=True)
    language = models.CharField(max_length=20, blank=True, null=True)

    follower_count = models.BigIntegerField(default=0, db_index=True)
    following_count = models.BigIntegerField(default=0)
    post_count = models.BigIntegerField(default=0)
    avg_likes = models.BigIntegerField(default=0)
    avg_comments = models.BigIntegerField(default=0)
    avg_views = models.BigIntegerField(default=0)
    engagement_rate = models.DecimalField(max_digits=10, decimal_places=4, default=0, db_index=True)
    estimated_reach = models.BigIntegerField(default=0)
    estimated_price_min = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    estimated_price_max = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    source = models.CharField(max_length=30, choices=PLATFORM_STATUS_CHOICES, default="manual", db_index=True)
    notes = models.TextField(blank=True, null=True)
    contact_email = models.EmailField(blank=True, null=True)
    raw_data = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_influencers",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Influencer"
        verbose_name_plural = "Influencerlar"
        ordering = ["-follower_count", "display_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["platform", "normalized_handle"],
                name="uniq_influencer_platform_handle",
            )
        ]
        indexes = [
            models.Index(fields=["platform", "category", "is_active"]),
            models.Index(fields=["follower_count", "engagement_rate"]),
            models.Index(fields=["country", "city"]),
            models.Index(fields=["source", "is_active"]),
        ]

    def save(self, *args, **kwargs):
        self.normalized_handle = normalize_influencer_handle(self.handle)
        if not self.display_name:
            self.display_name = self.handle
        super().save(*args, **kwargs)

    def __str__(self):
        platform_name = self.platform.name if self.platform else "Platform"
        return f"{self.display_name} - {platform_name}"


class InfluencerMetricHistory(models.Model):
    influencer = models.ForeignKey(
        "core.Influencer",
        on_delete=models.CASCADE,
        related_name="metric_history",
    )
    date = models.DateField()

    follower_count = models.BigIntegerField(default=0)
    following_count = models.BigIntegerField(default=0)
    post_count = models.BigIntegerField(default=0)
    avg_likes = models.BigIntegerField(default=0)
    avg_comments = models.BigIntegerField(default=0)
    avg_views = models.BigIntegerField(default=0)
    engagement_rate = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    estimated_reach = models.BigIntegerField(default=0)

    raw_metrics = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Influencer Metrik Geçmişi"
        verbose_name_plural = "Influencer Metrik Geçmişleri"
        unique_together = ("influencer", "date")
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["influencer", "date"]),
            models.Index(fields=["date"]),
        ]

    def __str__(self):
        return f"{self.influencer} - {self.date}"


def normalize_influencer_handle(handle: str) -> str:
    return (handle or "").strip().lower().lstrip("@")
