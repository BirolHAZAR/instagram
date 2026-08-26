from django.conf import settings
from django.db import models


class SocialPost(models.Model):
    POST_TYPE_CHOICES = [
        ("IMAGE", "Görsel"),
        ("VIDEO", "Video"),
        ("CAROUSEL", "Carousel"),
        ("REELS", "Reels"),
        ("SHORTS", "Shorts"),
        ("TEXT", "Metin"),
        ("LINK", "Link"),
        ("UNKNOWN", "Bilinmiyor"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="competitor_social_posts",
    )

    platform_connection = models.ForeignKey(
        "core.PlatformConnection",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="competitor_social_posts",
    )

    platform_account = models.ForeignKey(
        "core.PlatformAccount",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="competitor_social_posts",
    )

    competitor = models.ForeignKey(
        "core.Ad",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="competitor_social_posts",
    )

    platform_post_id = models.CharField(max_length=255)
    post_type = models.CharField(max_length=30, choices=POST_TYPE_CHOICES, default="UNKNOWN")

    caption = models.TextField(blank=True, null=True)
    permalink = models.URLField(max_length=1000, blank=True, null=True)

    image_url = models.URLField(max_length=1000, blank=True, null=True)
    video_url = models.URLField(max_length=1000, blank=True, null=True)
    thumbnail_url = models.URLField(max_length=1000, blank=True, null=True)

    posted_at = models.DateTimeField(blank=True, null=True)

    raw_data = models.JSONField(default=dict, blank=True)

    last_synced_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Sosyal Medya Paylaşımı"
        verbose_name_plural = "Sosyal Medya Paylaşımları"
        ordering = ["-posted_at", "-created_at"]
        indexes = [
            models.Index(fields=["user", "post_type"]),
            models.Index(fields=["platform_post_id"]),
            models.Index(fields=["competitor"]),
            models.Index(fields=["posted_at"]),
        ]

    def __str__(self):
        return self.caption[:60] if self.caption else f"SocialPost #{self.id}"


class SocialPostMetricHistory(models.Model):
    social_post = models.ForeignKey(
        "core.SocialPost",
        on_delete=models.CASCADE,
        related_name="metric_history",
    )

    date = models.DateField()

    impressions = models.BigIntegerField(default=0)
    reach = models.BigIntegerField(default=0)

    likes = models.BigIntegerField(default=0)
    comments = models.BigIntegerField(default=0)
    shares = models.BigIntegerField(default=0)
    saves = models.BigIntegerField(default=0)

    video_views = models.BigIntegerField(default=0)
    profile_visits = models.BigIntegerField(default=0)
    website_clicks = models.BigIntegerField(default=0)

    engagement = models.BigIntegerField(default=0)
    engagement_rate = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    raw_metrics = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sosyal Paylaşım Metrik Geçmişi"
        verbose_name_plural = "Sosyal Paylaşım Metrik Geçmişleri"
        unique_together = ("social_post", "date")
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["social_post", "date"]),
            models.Index(fields=["date"]),
        ]

    def __str__(self):
        return f"{self.social_post} - {self.date}"