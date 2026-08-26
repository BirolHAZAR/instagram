from django.db import models
from .base import User
from .campaigns import AdCampaign
from .instagram import InstagramAccount


class AIAnalysis(models.Model):
    ANALYSIS_TYPES = [
        ('campaign', 'Kampanya Analizi'),
        ('account', 'Hesap Analizi'),
        ('competitor', 'Rakip Analizi'),
        ('ad', 'Reklam Analizi'),
    ]

    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE, related_name='analyses', null=True, blank=True)
    instagram_account = models.ForeignKey(InstagramAccount, on_delete=models.CASCADE, related_name='analyses', null=True, blank=True)
    analysis_date = models.DateTimeField(auto_now_add=True)
    analysis_type = models.CharField(max_length=50, choices=ANALYSIS_TYPES, default='campaign')
    performance_score = models.FloatField(default=0)
    analysis_text = models.TextField()
    recommendations = models.TextField(blank=True)
    predictions = models.TextField(blank=True)
    insights = models.JSONField(default=dict, blank=True)
    ai_model_used = models.CharField(max_length=100, default='gpt-4o')
    processing_time = models.FloatField(default=0)
    objective = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        verbose_name = 'AI Analiz'
        verbose_name_plural = 'AI Analizler'
        ordering = ['-analysis_date']

    def __str__(self):
        return f"AI Analysis - {self.analysis_date}"


class ReklamAIAnaliz(models.Model):
    REPORT_TYPE_CHOICES = [
        ('analysis', 'Reklam Analizi'),
        ('recommendation', 'Reklam Önerisi'),
    ]
    STATUS_CHOICES = [
        ('completed', '✅ Tamamlandı'),
        ('failed', '❌ Başarısız'),
    ]

    reklam = models.ForeignKey('core.Ad', on_delete=models.SET_NULL, null=True, blank=True, related_name='ai_analizler')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='ad_ai_reports')
    report_type = models.CharField(max_length=20, choices=REPORT_TYPE_CHOICES, default='analysis', db_index=True)
    reklam_adi = models.CharField(max_length=500, verbose_name="Reklam Adı")
    Ins_reklam_id = models.CharField(max_length=100, verbose_name="Platform Reklam ID")
    overall_score = models.IntegerField(default=0, verbose_name="Genel Skor (0-100)")
    analysis_summary = models.TextField(blank=True, null=True, verbose_name="Analiz Özeti")
    agents_results = models.JSONField(default=list, verbose_name="Ajan Sonuçları")
    recommendation_summary = models.TextField(blank=True, null=True, verbose_name="Öneri Özeti")
    metrics_payload = models.JSONField(default=dict, blank=True)
    creative_payload = models.JSONField(default=dict, blank=True)
    rules_payload = models.JSONField(default=list, blank=True)
    strategy_payload = models.JSONField(default=dict, blank=True)
    active_rule_count = models.PositiveIntegerField(default=0)
    matched_rule_count = models.PositiveIntegerField(default=0)
    visual_analyzed = models.BooleanField(default=False)
    ai_model_used = models.CharField(max_length=100, blank=True, default="")
    sentiment_score = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="Duygu Skoru")
    content_quality_score = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="İçerik Kalitesi")
    hashtag_score = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="Hashtag Skoru")
    competitor_score = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="Rakip Skoru")
    performance_score = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="Performans Skoru")
    budget_score = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="Bütçe Skoru")
    lead_score = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="Lead Skoru")
    market_score = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name="Pazar Skoru")
    processing_time = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name="İşlem Süresi (sn)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Analiz Tarihi")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "🤖 Reklam AI Analiz"
        verbose_name_plural = "🤖 Reklam AI Analizleri"
        ordering = ['-created_at']
        indexes = [models.Index(fields=['reklam', 'report_type', '-created_at'], name='core_reklam_reklam__9f7384_idx')]

    def __str__(self):
        return f"AI Analiz: {self.reklam_adi[:50]} ({self.overall_score}/100)"


class Report(models.Model):
    REPORT_TYPES = [('daily', 'Günlük Rapor'), ('weekly', 'Haftalık Rapor'), ('monthly', 'Aylık Rapor'), ('custom', 'Özel Rapor')]
    FORMATS = [('pdf', 'PDF'), ('excel', 'Excel'), ('csv', 'CSV')]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reports')
    name = models.CharField(max_length=200)
    report_type = models.CharField(max_length=20, choices=REPORT_TYPES)
    format = models.CharField(max_length=10, choices=FORMATS, default='pdf')
    file = models.FileField(upload_to='reports/', null=True, blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_ready = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Rapor'
        verbose_name_plural = 'Raporlar'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.user.username}"


class ScheduledReport(models.Model):
    FREQUENCY_CHOICES = [
        ("daily", "Gunluk"),
        ("weekly", "Haftalik"),
        ("biweekly", "15 Gunluk"),
        ("monthly", "Aylik"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scheduled_reports")
    agency_client = models.ForeignKey(
        "core.AgencyClient", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="scheduled_reports", verbose_name="Ajans müşterisi",
    )
    name = models.CharField(max_length=180)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default="weekly")
    recipient_emails = models.JSONField(default=list, blank=True)
    campaigns = models.ManyToManyField("core.Campaign", blank=True, related_name="scheduled_reports")

    include_campaign_summary = models.BooleanField(default=True)
    include_ad_performance = models.BooleanField(default=True)
    include_rule_recommendations = models.BooleanField(default=True)

    is_active = models.BooleanField(default=True)
    send_hour = models.PositiveSmallIntegerField(default=9)
    last_sent_at = models.DateTimeField(blank=True, null=True)
    next_run_at = models.DateTimeField(blank=True, null=True)
    last_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Otomatik Rapor"
        verbose_name_plural = "Otomatik Raporlar"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["next_run_at"]),
        ]

    def __str__(self):
        return f"{self.name} - {self.user.username}"
