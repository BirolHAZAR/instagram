from django.db import models
from .base import User


class AnomalyAlert(models.Model):
    ALERT_TYPES = [
        ('spend_spike', '💸 Ani Harcama Artışı'),
        ('spend_drop', '📉 Harcama Düşüşü'),
        ('impression_spike', '📈 Gösterim Patlaması'),
        ('ctr_change', '🎯 CTR Değişimi'),
        ('new_campaign', '🆕 Yeni Kampanya'),
        ('budget_increase', '💰 Bütçe Artışı'),
        ('opportunity', '🌟 Fırsat Penceresi'),
        ('gap_detected', '🎯 Boşluk Tespiti'),
    ]
    SEVERITY_CHOICES = [('low', 'Düşük'), ('medium', 'Orta'), ('high', 'Yüksek'), ('critical', 'Kritik')]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='anomaly_alerts')
    # Eski rakip FK yerine artık ilgili reklam Ad tablosundan tutulur.
    rakip = models.ForeignKey('core.Ad', on_delete=models.SET_NULL, related_name='anomalies', null=True, blank=True)
    alert_type = models.CharField(max_length=30, choices=ALERT_TYPES)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='medium')
    title = models.CharField(max_length=300)
    description = models.TextField()
    old_value = models.FloatField(null=True, blank=True)
    new_value = models.FloatField(null=True, blank=True)
    change_percent = models.FloatField(null=True, blank=True, verbose_name="Değişim %")
    suggested_action = models.TextField(blank=True, null=True)
    action_link = models.URLField(blank=True, null=True)
    is_read = models.BooleanField(default=False)
    is_dismissed = models.BooleanField(default=False)
    detected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Anomali Uyarısı'
        verbose_name_plural = 'Anomali Uyarıları'
        ordering = ['-detected_at', '-severity']

    def __str__(self):
        return f"[{self.get_severity_display()}] {self.title[:80]}"


class OpportunityWindow(models.Model):
    OPPORTUNITY_TYPES = [
        ('low_competition', '🏝️ Düşük Rekabet'), ('high_demand', '📈 Yüksek Talep'),
        ('budget_gap', '💎 Bütçe Boşluğu'), ('time_window', '⏰ Zaman Penceresi'),
        ('audience_gap', '👥 Hedef Kitle Boşluğu'), ('location_gap', '📍 Bölgesel Fırsat'),
        ('hashtag_trend', '#️⃣ Hashtag Trendi'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='opportunities')
    opportunity_type = models.CharField(max_length=30, choices=OPPORTUNITY_TYPES)
    title = models.CharField(max_length=300)
    description = models.TextField()
    estimated_savings = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estimated_reach = models.IntegerField(null=True, blank=True)
    confidence_score = models.FloatField(default=0.0, verbose_name="Güven Skoru (0-100)")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="Son Geçerlilik")
    is_expired = models.BooleanField(default=False)
    suggested_action = models.TextField()
    action_link = models.URLField(blank=True, null=True)
    is_taken = models.BooleanField(default=False, verbose_name="Aksiyon Alındı mı?")
    detected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Fırsat Penceresi'
        verbose_name_plural = 'Fırsat Pencereleri'
        ordering = ['-confidence_score', '-detected_at']

    def __str__(self):
        return f"{self.get_opportunity_type_display()} - {self.title[:80]}"
