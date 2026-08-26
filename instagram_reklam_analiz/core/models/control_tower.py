from django.conf import settings
from django.db import models
from django.utils import timezone


class ControlTowerSnapshot(models.Model):
    PERIOD_DAILY = "daily"
    PERIOD_WEEKLY = "weekly"
    PERIOD_MONTHLY = "monthly"
    PERIOD_QUARTERLY = "quarterly"
    PERIOD_CUSTOM = "custom"

    PERIOD_CHOICES = (
        (PERIOD_DAILY, "Daily"),
        (PERIOD_WEEKLY, "Weekly"),
        (PERIOD_MONTHLY, "Monthly"),
        (PERIOD_QUARTERLY, "Quarterly"),
        (PERIOD_CUSTOM, "Custom"),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="control_tower_snapshots")
    period = models.CharField(max_length=20, choices=PERIOD_CHOICES, default=PERIOD_MONTHLY)
    date_from = models.DateField()
    date_to = models.DateField()
    snapshot_date = models.DateTimeField(default=timezone.now, db_index=True)
    octo_score = models.PositiveSmallIntegerField(default=0)
    summary = models.JSONField(default=dict, blank=True)
    decision_center = models.JSONField(default=dict, blank=True)
    source_version = models.CharField(max_length=40, default="ct_snapshot_v1")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-snapshot_date"]
        indexes = [
            models.Index(fields=["user", "period", "date_from", "date_to"]),
            models.Index(fields=["user", "snapshot_date"]),
        ]
        verbose_name = "Control Tower Snapshot"
        verbose_name_plural = "Control Tower Snapshots"

    def __str__(self):
        return f"{self.user_id} · {self.period} · {self.date_from} - {self.date_to}"


class ControlTowerCardSnapshot(models.Model):
    CARD_KPI = "kpi_strip"
    CARD_DECISION = "decision_center"
    CARD_TASK = "octo_task_center"
    CARD_ALERT = "critical_alerts"
    CARD_CAMPAIGN_HEALTH = "campaign_health"
    CARD_CREATIVE = "creative_wall"
    CARD_COMPETITOR = "competitor_intelligence"
    CARD_PLATFORM = "platform_status"

    CARD_CHOICES = (
        (CARD_KPI, "KPI Strip"),
        (CARD_DECISION, "Octo Decision Center"),
        (CARD_TASK, "Octo Task Center"),
        (CARD_ALERT, "Critical Alerts"),
        (CARD_CAMPAIGN_HEALTH, "Campaign Health Center"),
        (CARD_CREATIVE, "Creative Performance Wall"),
        (CARD_COMPETITOR, "Competitor Intelligence Center"),
        (CARD_PLATFORM, "Platform Status Center"),
    )

    snapshot = models.ForeignKey(ControlTowerSnapshot, on_delete=models.CASCADE, related_name="cards")
    card_key = models.CharField(max_length=50, choices=CARD_CHOICES)
    title_tr = models.CharField(max_length=120)
    title_en = models.CharField(max_length=120)
    status = models.CharField(max_length=20, default="stable")
    score = models.IntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)
    ai_summary = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("snapshot", "card_key")
        indexes = [models.Index(fields=["card_key", "status"])]
        verbose_name = "Control Tower Card Snapshot"
        verbose_name_plural = "Control Tower Card Snapshots"

    def __str__(self):
        return f"{self.card_key} · {self.snapshot_id}"


class ControlTowerAIAnalysis(models.Model):
    SEVERITY_INFO = "info"
    SEVERITY_SUCCESS = "success"
    SEVERITY_WARNING = "warning"
    SEVERITY_CRITICAL = "critical"

    SEVERITY_CHOICES = (
        (SEVERITY_INFO, "Info"),
        (SEVERITY_SUCCESS, "Success"),
        (SEVERITY_WARNING, "Warning"),
        (SEVERITY_CRITICAL, "Critical"),
    )

    snapshot = models.ForeignKey(ControlTowerSnapshot, on_delete=models.CASCADE, related_name="ai_analyses")
    card_key = models.CharField(max_length=50)
    title_tr = models.CharField(max_length=160)
    title_en = models.CharField(max_length=160, blank=True, default="")
    analysis_tr = models.TextField()
    analysis_en = models.TextField(blank=True, default="")
    recommendation_tr = models.TextField(blank=True, default="")
    recommendation_en = models.TextField(blank=True, default="")
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default=SEVERITY_INFO)
    confidence = models.PositiveSmallIntegerField(default=80)
    payload = models.JSONField(default=dict, blank=True)

    # Premium Strategic Advisor alanları. Tek tablo yaklaşımı:
    # kısa AI yorumu + derin danışman analizi aynı kayıtta tutulur.
    analysis_type = models.CharField(max_length=50, blank=True, default="")
    what_happened = models.TextField(blank=True, default="")
    root_cause = models.TextField(blank=True, default="")
    forecast = models.TextField(blank=True, default="")
    action_plan = models.TextField(blank=True, default="")
    expected_impact = models.TextField(blank=True, default="")

    expected_revenue_gain = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    expected_revenue_loss = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    expected_roas_change = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    expected_ctr_change = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    priority = models.CharField(max_length=20, default="medium")
    status = models.CharField(max_length=20, default="active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["snapshot", "card_key", "severity"]),
            models.Index(fields=["snapshot", "analysis_type", "status"]),
            models.Index(fields=["severity", "priority"]),
        ]
        verbose_name = "Control Tower AI Analysis"
        verbose_name_plural = "Control Tower AI Analyses"

    def __str__(self):
        return f"{self.card_key} · {self.severity}"


class ControlTowerActionItem(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPLIED = "applied"
    STATUS_DISMISSED = "dismissed"

    PRIORITY_LOW = "low"
    PRIORITY_MEDIUM = "medium"
    PRIORITY_HIGH = "high"
    PRIORITY_CRITICAL = "critical"

    snapshot = models.ForeignKey(ControlTowerSnapshot, on_delete=models.CASCADE, related_name="action_items")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="control_tower_action_items")
    card_key = models.CharField(max_length=50)
    title_tr = models.CharField(max_length=180)
    title_en = models.CharField(max_length=180, blank=True, default="")
    description_tr = models.TextField(blank=True, default="")
    description_en = models.TextField(blank=True, default="")
    expected_impact = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    priority = models.CharField(max_length=20, default=PRIORITY_MEDIUM)
    status = models.CharField(max_length=20, default=STATUS_PENDING)
    action_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["status", "-expected_impact", "-created_at"]
        indexes = [models.Index(fields=["user", "status", "priority"])]
        verbose_name = "Control Tower Action Item"
        verbose_name_plural = "Control Tower Action Items"

    def __str__(self):
        return self.title_tr



class ControlTowerDecision(models.Model):
    """Octo Karar Merkezi karar geçmişi.

    ActionItem yapılacak işi temsil eder; Decision ise karar merkezi tarafından
    üretilen kararın gerekçe/etki kaydıdır. Böylece dashboard analizleri geçmişe
    dönük raporlanabilir.
    """
    STATUS_OPEN = "open"
    STATUS_APPLIED = "applied"
    STATUS_DISMISSED = "dismissed"

    snapshot = models.ForeignKey(ControlTowerSnapshot, on_delete=models.CASCADE, related_name="decisions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="control_tower_decisions")
    title_tr = models.CharField(max_length=180)
    title_en = models.CharField(max_length=180, blank=True, default="")
    reason_tr = models.TextField(blank=True, default="")
    reason_en = models.TextField(blank=True, default="")
    expected_gain = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    priority = models.CharField(max_length=20, default="medium")
    status = models.CharField(max_length=20, default=STATUS_OPEN)
    payload = models.JSONField(default=dict, blank=True)

    # Premium Strategic Advisor alanları. Tek tablo yaklaşımı:
    # kısa AI yorumu + derin danışman analizi aynı kayıtta tutulur.
    analysis_type = models.CharField(max_length=50, blank=True, default="")
    what_happened = models.TextField(blank=True, default="")
    root_cause = models.TextField(blank=True, default="")
    forecast = models.TextField(blank=True, default="")
    action_plan = models.TextField(blank=True, default="")
    expected_impact = models.TextField(blank=True, default="")

    expected_revenue_gain = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    expected_revenue_loss = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    expected_roas_change = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    expected_ctr_change = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    priority = models.CharField(max_length=20, default="medium")
    status = models.CharField(max_length=20, default="active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["status", "-expected_gain", "-created_at"]
        indexes = [models.Index(fields=["user", "status", "priority"])]
        verbose_name = "Control Tower Decision"
        verbose_name_plural = "Control Tower Decisions"

    def __str__(self):
        return self.title_tr
