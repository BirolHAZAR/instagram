from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class NotificationPreference(models.Model):
    """Kullanıcının uygulama içi ve e-posta bildirim tercihleri."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="notification_preferences")

    competitor_notifications = models.BooleanField(default=True)
    ai_notifications = models.BooleanField(default=True)
    campaign_notifications = models.BooleanField(default=True)
    optimization_notifications = models.BooleanField(default=True)
    system_notifications = models.BooleanField(default=True)
    critical_notifications = models.BooleanField(default=True)

    in_app_enabled = models.BooleanField(default=True)
    realtime_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=False)
    daily_summary_enabled = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Bildirim Tercihi"
        verbose_name_plural = "Bildirim Tercihleri"

    def __str__(self):
        return f"{self.user} bildirim tercihleri"


class ActivityLog(models.Model):
    """Kullanıcı aktivite akışı / audit log."""

    ACTION_CHOICES = [
        ("notification", "Bildirim"),
        ("competitor", "Rakip"),
        ("campaign", "Kampanya"),
        ("ad", "Reklam"),
        ("ai", "AI"),
        ("optimization", "Optimizasyon"),
        ("account", "Hesap"),
        ("payment", "Ödeme"),
        ("system", "Sistem"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="activity_logs")
    action_type = models.CharField(max_length=40, choices=ACTION_CHOICES, default="system")
    title = models.CharField(max_length=220)
    message = models.TextField(blank=True)
    level = models.CharField(max_length=20, default="info")
    icon = models.CharField(max_length=50, default="📌")
    link = models.CharField(max_length=500, blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["user", "action_type", "-created_at"]),
        ]
        verbose_name = "Aktivite Kaydı"
        verbose_name_plural = "Aktivite Kayıtları"

    def __str__(self):
        return f"{self.user} - {self.title[:60]}"
