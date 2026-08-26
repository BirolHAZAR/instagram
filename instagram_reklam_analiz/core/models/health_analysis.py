from django.conf import settings
from django.db import models


class HealthCenterAIAnalysis(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="health_center_ai_analyses",
    )
    platform_code = models.CharField(max_length=80, blank=True, default="")
    platform_label = models.CharField(max_length=160, blank=True, default="")
    account_id = models.CharField(max_length=80, blank=True, default="")
    account_label = models.CharField(max_length=255, blank=True, default="")
    days = models.PositiveIntegerField(default=30)
    status_filter = models.CharField(max_length=40, blank=True, default="ACTIVE")

    score = models.PositiveIntegerField(default=0)
    score_delta = models.IntegerField(default=0)
    active_count = models.PositiveIntegerField(default=0)
    measured_count = models.PositiveIntegerField(default=0)

    source = models.CharField(max_length=30, blank=True, default="openai")
    headline = models.CharField(max_length=255, blank=True, default="")
    summary = models.TextField(blank=True, default="")
    error = models.TextField(blank=True, default="")

    agents_payload = models.JSONField(default=list, blank=True)
    decision_notes = models.JSONField(default=list, blank=True)
    metrics_payload = models.JSONField(default=dict, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["user", "platform_code", "account_id", "-created_at"]),
        ]
        verbose_name = "Reklam Sağlık Merkezi AI Analizi"
        verbose_name_plural = "Reklam Sağlık Merkezi AI Analizleri"

    def __str__(self):
        scope = self.account_label or self.platform_label or "Tüm hesaplar"
        return f"{scope} - {self.score}/100 - {self.created_at:%Y-%m-%d %H:%M}"
