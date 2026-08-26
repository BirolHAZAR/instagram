from django.conf import settings
from django.db import models
from django.utils import timezone


class OctoTaskRule(models.Model):
    SEVERITY_CHOICES = [
        ("critical", "Kritik"),
        ("warning", "Uyarı"),
        ("info", "Bilgi"),
        ("opportunity", "Fırsat"),
    ]

    MODULE_CHOICES = [
        ("performance", "Performans"),
        ("creative", "Kreatif"),
        ("budget", "Bütçe"),
        ("competitor", "Rakip"),
        ("conversion", "Dönüşüm"),
    ]

    code = models.CharField(max_length=50, unique=True)
    module = models.CharField(max_length=50, choices=MODULE_CHOICES)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)

    title_tr = models.CharField(max_length=255)
    message_tr = models.TextField()
    action_text_tr = models.CharField(max_length=255, blank=True, null=True)

    title_en = models.CharField(max_length=255, blank=True, null=True)
    message_en = models.TextField(blank=True, null=True)
    action_text_en = models.CharField(max_length=255, blank=True, null=True)

    condition_key = models.CharField(max_length=100)
    condition_description = models.TextField(blank=True, null=True)

    root_cause = models.TextField(blank=True, null=True)
    expected_result = models.TextField(blank=True, null=True)
    cta_text = models.CharField(max_length=255, blank=True, null=True)
    user_condition = models.TextField(blank=True, null=True)
    source_platform = models.CharField(max_length=100, blank=True, null=True)
    source_table = models.CharField(max_length=100, blank=True, null=True)

    priority_score = models.PositiveIntegerField(default=50)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Octo Görev Kuralı"
        verbose_name_plural = "Octo Görev Kuralları"
        ordering = ["-priority_score", "code"]

    def __str__(self):
        return f"{self.code} - {self.title_tr}"


class OctoTaskInstance(models.Model):
    STATUS_CHOICES = [
        ("open", "Açık"),
        ("viewed", "İncelendi"),
        ("done", "Tamamlandı"),
        ("dismissed", "Kapatıldı"),
        ("snoozed", "Ertelendi"),
    ]

    rule = models.ForeignKey(
        OctoTaskRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="instances"
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="octo_tasks"
    )

    platform_connection = models.ForeignKey(
        "core.PlatformConnection",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="octo_tasks"
    )

    platform_account = models.ForeignKey(
        "core.PlatformAccount",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="octo_tasks"
    )

    campaign = models.ForeignKey(
        "core.Campaign",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="octo_tasks"
    )

    ad_group = models.ForeignKey(
        "core.AdGroup",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="octo_tasks"
    )

    ad = models.ForeignKey(
        "core.Ad",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="octo_tasks"
    )

    creative = models.ForeignKey(
        "core.Creative",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="octo_tasks"
    )

    module = models.CharField(max_length=50)
    severity = models.CharField(max_length=20)

    title_tr = models.CharField(max_length=255)
    message_tr = models.TextField()
    action_text_tr = models.CharField(max_length=255, blank=True, null=True)

    title_en = models.CharField(max_length=255, blank=True, null=True)
    message_en = models.TextField(blank=True, null=True)
    action_text_en = models.CharField(max_length=255, blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")

    priority_score = models.PositiveIntegerField(default=50)

    detected_value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    previous_value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    change_percent = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    source_period_start = models.DateField(null=True, blank=True)
    source_period_end = models.DateField(null=True, blank=True)

    unique_key = models.CharField(max_length=255, unique=True)

    first_detected_at = models.DateTimeField(default=timezone.now)
    last_detected_at = models.DateTimeField(default=timezone.now)

    completed_at = models.DateTimeField(null=True, blank=True)
    dismissed_at = models.DateTimeField(null=True, blank=True)
    snoozed_until = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Octo Görevi"
        verbose_name_plural = "Octo Görevleri"
        ordering = ["-priority_score", "-last_detected_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["platform_connection", "status"]),
            models.Index(fields=["platform_account", "status"]),
            models.Index(fields=["campaign", "status"]),
            models.Index(fields=["severity", "status"]),
            models.Index(fields=["unique_key"]),
        ]

    def __str__(self):
        return f"{self.title_tr} - {self.user}"


class OctoTaskActionLog(models.Model):
    ACTION_CHOICES = [
        ("viewed", "İncelendi"),
        ("done", "Tamamlandı"),
        ("dismissed", "Kapatıldı"),
        ("snoozed", "Ertelendi"),
        ("reopened", "Tekrar Açıldı"),
    ]

    task = models.ForeignKey(
        OctoTaskInstance,
        on_delete=models.CASCADE,
        related_name="action_logs"
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="octo_task_logs"
    )

    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    note = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Octo Görev İşlem Kaydı"
        verbose_name_plural = "Octo Görev İşlem Kayıtları"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.task_id} - {self.action}"


class OctoRuleEngineRun(models.Model):
    STATUS_CHOICES = [
        ("running", "Çalışıyor"),
        ("completed", "Tamamlandı"),
        ("failed", "Hatalı"),
        ("skipped", "Atlandı"),
    ]

    TRIGGER_CHOICES = [
        ("ad_sync", "Reklam senkronizasyonu"),
        ("metric_refresh", "Metrik güncellemesi"),
        ("periodic_sweep", "Periyodik güvenlik taraması"),
        ("manual", "Manuel"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="octo_rule_engine_runs",
    )
    platform_account = models.ForeignKey(
        "core.PlatformAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="octo_rule_engine_runs",
    )
    trigger = models.CharField(max_length=30, choices=TRIGGER_CHOICES, default="manual")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="running")
    celery_task_id = models.CharField(max_length=255, blank=True, default="")
    active_rule_count = models.PositiveIntegerField(default=0)
    campaigns_evaluated = models.PositiveIntegerField(default=0)
    signals_matched = models.PositiveIntegerField(default=0)
    tasks_created = models.PositiveIntegerField(default=0)
    tasks_skipped = models.PositiveIntegerField(default=0)
    details = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status="running"),
                name="unique_running_octo_engine_per_user",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "status", "started_at"],
                name="core_octoru_user_id_3b348a_idx",
            ),
            models.Index(
                fields=["platform_account", "started_at"],
                name="core_octoru_platfor_6c83dc_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user_id} - {self.trigger} - {self.status}"
