from django.conf import settings
from django.db import models
from django.utils import timezone


class CampaignOctoAnalysis(models.Model):
    SUCCESS_LEVEL_CHOICES = [
        ("success", "Başarılı"),
        ("warning", "Geliştirilebilir"),
        ("danger", "Riskli / Başarısız"),
        ("learning", "Öğrenme Aşaması"),
        ("neutral", "İzleniyor"),
    ]

    STATUS_CHOICES = [
        ("excellent", "Başarılı"),
        ("good", "İyi"),
        ("watch", "İzlenmeli"),
        ("risky", "Riskli"),
        ("critical", "Kritik"),
    ]

    RISK_CHOICES = [
        ("low", "Düşük"),
        ("medium", "Orta"),
        ("high", "Yüksek"),
        ("critical", "Kritik"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="campaign_octo_analyses",
        null=True,
        blank=True,
    )
    campaign = models.ForeignKey(
        "core.Campaign",
        on_delete=models.CASCADE,
        related_name="octo_analyses",
    )

    campaign_name = models.CharField(max_length=255, default="Kampanya")
    platform_name = models.CharField(max_length=120, blank=True, default="")
    account_name = models.CharField(max_length=255, blank=True, default="")
    objective = models.CharField(max_length=120, blank=True, default="")

    octo_score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    analysis_score = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="watch")
    risk_level = models.CharField(max_length=20, choices=RISK_CHOICES, default="medium")
    success_level = models.CharField(max_length=20, choices=SUCCESS_LEVEL_CHOICES, default="neutral")
    success_label = models.CharField(max_length=120, default="İzleniyor")
    success_reason = models.TextField(blank=True, default="")

    roas = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    ctr = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cpc = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cpm = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    spend = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    budget = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    conversions = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    conversion_value = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    roas_score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    ctr_score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    cpc_score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    conversion_score = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    analysis_text = models.TextField(blank=True, default="")
    recommendation_text = models.TextField(blank=True, default="")
    agents_payload = models.JSONField(default=list, blank=True)
    raw_ai_payload = models.JSONField(default=dict, blank=True)
    strengths = models.TextField(blank=True, default="")
    weaknesses = models.TextField(blank=True, default="")
    next_actions = models.TextField(blank=True, default="")
    expected_impact = models.TextField(blank=True, default="")
    priority = models.CharField(max_length=20, blank=True, default="medium")

    # Octo v2 alanları
    best_metric = models.CharField(max_length=80, blank=True, default="")
    worst_metric = models.CharField(max_length=80, blank=True, default="")
    risk_score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    risk_label = models.CharField(max_length=40, blank=True, default="")
    trend_7d = models.CharField(max_length=40, blank=True, default="")
    trend_30d = models.CharField(max_length=40, blank=True, default="")
    competitor_position = models.CharField(max_length=120, blank=True, default="")
    main_strength = models.TextField(blank=True, default="")
    main_weakness = models.TextField(blank=True, default="")
    risk_reason = models.TextField(blank=True, default="")

    source = models.CharField(max_length=20, default="real")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Octo Kampanya Analizi"
        verbose_name_plural = "Octo Kampanya Analizleri"

    def __str__(self):
        return f"{self.campaign_name} - {self.success_label} ({self.octo_score}/100)"


class CampaignOctoRecommendation(models.Model):
    PRIORITY_CHOICES = [
        ("low", "Düşük"),
        ("medium", "Orta"),
        ("high", "Yüksek"),
        ("urgent", "Acil"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="campaign_octo_recommendations",
        null=True,
        blank=True,
    )
    campaign = models.ForeignKey(
        "core.Campaign",
        on_delete=models.CASCADE,
        related_name="octo_recommendations",
    )
    analysis = models.ForeignKey(
        "core.CampaignOctoAnalysis",
        on_delete=models.SET_NULL,
        related_name="recommendations",
        null=True,
        blank=True,
    )

    campaign_name = models.CharField(max_length=255, blank=True, default="Kampanya")
    platform_name = models.CharField(max_length=120, blank=True, default="")
    account_name = models.CharField(max_length=255, blank=True, default="")

    summary = models.TextField(blank=True, default="")
    strengths = models.TextField(blank=True, default="")
    weaknesses = models.TextField(blank=True, default="")
    recommendations = models.TextField(blank=True, default="")
    agents_payload = models.JSONField(default=list, blank=True)
    raw_ai_payload = models.JSONField(default=dict, blank=True)
    expected_impact = models.TextField(blank=True, default="")
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default="medium")

    # Octo v2 öneri etki alanları
    difficulty_level = models.CharField(max_length=40, blank=True, default="")
    estimated_roas_gain = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    estimated_ctr_gain = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    estimated_conversion_gain = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    implementation_time = models.CharField(max_length=80, blank=True, default="")
    action_type = models.CharField(max_length=80, blank=True, default="")

    # Uygulandı mı ve sonuç takibi
    is_applied = models.BooleanField(default=False)
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="applied_campaign_octo_recommendations",
    )
    apply_note = models.TextField(blank=True, default="")

    success_check_after_days = models.IntegerField(default=7)
    baseline_roas = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    baseline_ctr = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    baseline_cpc = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    baseline_conversions = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    result_roas = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    result_ctr = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    result_cpc = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    result_conversions = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    result_roas_before = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    result_roas_after = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    result_ctr_before = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    result_ctr_after = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    result_conversion_before = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    result_conversion_after = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    result_checked_at = models.DateTimeField(null=True, blank=True)

    outcome_status = models.CharField(max_length=40, blank=True, default="")
    outcome_note = models.TextField(blank=True, default="")
    outcome_checked_at = models.DateTimeField(null=True, blank=True)
    success_rate = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    source = models.CharField(max_length=20, default="real")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Octo Kampanya Yorum ve Önerisi"
        verbose_name_plural = "Octo Kampanya Yorum ve Önerileri"

    def __str__(self):
        return f"{self.campaign_name} - Octo Öneri #{self.pk}"
