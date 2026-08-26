from django.db import models
from django.utils import timezone


class AdminManagedCelerySchedule(models.Model):
    INTERVAL_MINUTES = "minutes"
    INTERVAL_HOURS = "hours"
    INTERVAL_DAYS = "days"
    INTERVAL_CHOICES = [
        (INTERVAL_MINUTES, "Dakika"),
        (INTERVAL_HOURS, "Saat"),
        (INTERVAL_DAYS, "Gün"),
    ]

    name = models.CharField(max_length=160, unique=True, verbose_name="Görev adı")
    task_name = models.CharField(max_length=240, verbose_name="Celery task adı")
    args = models.JSONField(default=list, blank=True, verbose_name="Args")
    kwargs = models.JSONField(default=dict, blank=True, verbose_name="Kwargs")
    interval_every = models.PositiveIntegerField(default=60, verbose_name="Her")
    interval_period = models.CharField(max_length=20, choices=INTERVAL_CHOICES, default=INTERVAL_MINUTES, verbose_name="Periyot")
    is_active = models.BooleanField(default=True, verbose_name="Aktif")
    description = models.TextField(blank=True, default="", verbose_name="Açıklama")
    last_run_at = models.DateTimeField(null=True, blank=True, verbose_name="Son çalışma")
    last_task_id = models.CharField(max_length=120, blank=True, default="", verbose_name="Son task id")
    last_error = models.TextField(blank=True, default="", verbose_name="Son hata")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Admin Celery Görevi"
        verbose_name_plural = "Admin Celery Görevleri"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def interval_seconds(self):
        multiplier = {
            self.INTERVAL_MINUTES: 60,
            self.INTERVAL_HOURS: 60 * 60,
            self.INTERVAL_DAYS: 60 * 60 * 24,
        }.get(self.interval_period, 60)
        return max(1, int(self.interval_every or 1)) * multiplier

    def is_due(self, now=None):
        if not self.is_active:
            return False
        now = now or timezone.now()
        if not self.last_run_at:
            return True
        return (now - self.last_run_at).total_seconds() >= self.interval_seconds
