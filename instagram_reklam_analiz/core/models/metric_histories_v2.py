from django.db import models


class BaseMetricHistory(models.Model):
    date = models.DateField()

    impressions = models.BigIntegerField(default=0)
    reach = models.BigIntegerField(default=0)
    frequency = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    clicks = models.BigIntegerField(default=0)
    link_clicks = models.BigIntegerField(default=0)
    unique_clicks = models.BigIntegerField(default=0)

    spend = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="TRY")

    ctr = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    cpc = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    cpm = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    conversions = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    conversion_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cost_per_conversion = models.DecimalField(max_digits=14, decimal_places=4, default=0)

    purchases = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    add_to_cart = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    initiate_checkout = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    leads = models.DecimalField(max_digits=14, decimal_places=4, default=0)

    landing_page_views = models.BigIntegerField(default=0)
    outbound_clicks = models.BigIntegerField(default=0)

    roas = models.DecimalField(max_digits=14, decimal_places=4, default=0)

    likes = models.BigIntegerField(default=0)
    comments = models.BigIntegerField(default=0)
    shares = models.BigIntegerField(default=0)
    saves = models.BigIntegerField(default=0)
    video_views = models.BigIntegerField(default=0)

    engagement = models.BigIntegerField(default=0)
    engagement_rate = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    raw_metrics = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class CampaignMetricHistory(BaseMetricHistory):
    campaign = models.ForeignKey(
        "core.Campaign",
        on_delete=models.CASCADE,
        related_name="metric_history",
    )

    class Meta:
        verbose_name = "Kampanya Metrik Geçmişi"
        verbose_name_plural = "Kampanya Metrik Geçmişleri"
        unique_together = ("campaign", "date")
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["campaign", "date"]),
            models.Index(fields=["date"]),
        ]

    def __str__(self):
        return f"{self.campaign} - {self.date}"


class AdGroupMetricHistory(BaseMetricHistory):
    ad_group = models.ForeignKey(
        "core.AdGroup",
        on_delete=models.CASCADE,
        related_name="metric_history",
    )

    class Meta:
        verbose_name = "Reklam Grubu Metrik Geçmişi"
        verbose_name_plural = "Reklam Grubu Metrik Geçmişleri"
        unique_together = ("ad_group", "date")
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["ad_group", "date"]),
            models.Index(fields=["date"]),
        ]

    def __str__(self):
        return f"{self.ad_group} - {self.date}"


class AdMetricHistory(BaseMetricHistory):
    ad = models.ForeignKey(
        "core.Ad",
        on_delete=models.CASCADE,
        related_name="metric_history",
    )

    estimated_engagement = models.BigIntegerField(default=0)
    estimated_reach_min = models.BigIntegerField(blank=True, null=True)
    estimated_reach_max = models.BigIntegerField(blank=True, null=True)

    is_competitor_snapshot = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Reklam Metrik Geçmişi"
        verbose_name_plural = "Reklam Metrik Geçmişleri"
        unique_together = ("ad", "date")
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["ad", "date"]),
            models.Index(fields=["date"]),
            models.Index(fields=["is_competitor_snapshot"]),
        ]

    def __str__(self):
        return f"{self.ad} - {self.date}"


class CreativeMetricHistory(BaseMetricHistory):
    creative = models.ForeignKey(
        "core.Creative",
        on_delete=models.CASCADE,
        related_name="metric_history",
    )

    thumbstop_rate = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    hook_rate = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    hold_rate = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    class Meta:
        verbose_name = "Kreatif Metrik Geçmişi"
        verbose_name_plural = "Kreatif Metrik Geçmişleri"
        unique_together = ("creative", "date")
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["creative", "date"]),
            models.Index(fields=["date"]),
        ]

    def __str__(self):
        return f"{self.creative} - {self.date}"