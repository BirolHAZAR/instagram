# core/models/campaigns.py
"""
Kampanya modelleri - instagram.py ve base.py'ye bağımlıdır
"""
from django.db import models
from .base import User
from .instagram import InstagramAccount


class AdCampaign(models.Model):
    """Reklam kampanyası modeli"""
    AD_TYPES = [
        ('image', 'Görsel Reklam'),
        ('video', 'Video Reklam'),
        ('carousel', 'Carousel Reklam'),
        ('story', 'Hikaye Reklam'),
        ('reels', 'Reels Reklam'),
    ]
    OBJECTIVE_CHOICES = [
        ('AWARENESS', 'Marka Farkındalığı'),
        ('TRAFFIC', 'Trafik'),
        ('ENGAGEMENT', 'Etkileşim'),
        ('LEADS', 'Potansiyel Müşteri'),
        ('CONVERSIONS', 'Dönüşüm'),
        ('SALES', 'Satış'),
    ]
    STATUS_CHOICES = [
        ('active', 'Aktif'),
        ('paused', 'Duraklatıldı'),
        ('ended', 'Sona Erdi'),
        ('draft', 'Taslak'),
        ('sent_to_instagram', "Instagram'a Gönderildi"),
    ]
    platform_account = models.ForeignKey(
        'core.PlatformAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='campaigns'
    )
    instagram_account = models.ForeignKey(
        InstagramAccount, on_delete=models.CASCADE, related_name='campaigns',
        db_column='instagram_account_id'
    )
    campaign_name = models.CharField(max_length=255)
    ad_type = models.CharField(max_length=20, choices=AD_TYPES, default='image')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    start_date = models.DateTimeField()
    end_date = models.DateTimeField(null=True, blank=True)
    budget = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    spent_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    target_audience = models.JSONField(default=dict, blank=True)
    media_file = models.FileField(upload_to='campaign_media/%Y/%m/%d/', null=True, blank=True)
    media_type = models.CharField(max_length=200, null=True, blank=True)
    carousel_items = models.JSONField(default=list, blank=True)
    
    # AI Analiz
    ai_analysis = models.JSONField(default=dict, blank=True)
    ai_score = models.FloatField(default=0)
    ai_recommendations = models.JSONField(default=list, blank=True)
    
    # Instagram Gönderme
    sent_to_instagram_at = models.DateTimeField(null=True, blank=True)
    instagram_campaign_id = models.CharField(max_length=255, null=True, blank=True)
    
    # Manuel override
    manual_override = models.BooleanField(default=False, verbose_name="Manuel Durum")
    manual_status = models.CharField(max_length=20, choices=[
        ('active', 'Aktif'),
        ('paused', 'Duraklatıldı'),
        ('completed', 'Tamamlandı'),
        ('cancelled', 'İptal Edildi'),
    ], blank=True, null=True, verbose_name="Manuel Durum Seçimi")
    override_reason = models.TextField(blank=True, null=True, verbose_name="Müdahale Sebebi")
    override_date = models.DateTimeField(blank=True, null=True, verbose_name="Müdahale Tarihi")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Reklam Kampanyası'
        verbose_name_plural = 'Reklam Kampanyaları'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.campaign_name} - {self.instagram_account.username}"
    
    def get_media_url(self):
        if self.media_file:
            return self.media_file.url
        return None
    
    @property
    def has_carousel_items(self):
        if self.ad_type != 'carousel':
            return False
        items = self.carousel_items
        return isinstance(items, list) and len(items) > 0
    
    @property
    def budget_percentage(self):
        try:
            budget = float(self.budget) if self.budget else 0
            spent = float(self.spent_amount) if self.spent_amount else 0
            if budget > 0:
                return int((spent / budget) * 100)
            return 0
        except (ValueError, TypeError, ZeroDivisionError):
            return 0
    
    @property
    def remaining_budget(self):
        try:
            budget = float(self.budget) if self.budget else 0
            spent = float(self.spent_amount) if self.spent_amount else 0
            return max(0, budget - spent)
        except (ValueError, TypeError):
            return 0
    
    def get_effective_status(self):
        from django.utils import timezone
        
        if self.status == 'cancelled':
            return 'cancelled'
        
        if hasattr(self, 'manual_override') and self.manual_override:
            return self.manual_status if hasattr(self, 'manual_status') else self.status
        
        now = timezone.now()
        if self.end_date and self.end_date <= now:
            return 'completed'
        if self.start_date and self.start_date > now:
            return 'scheduled'
        if self.status == 'paused':
            return 'paused'
        if self.status == 'draft':
            return 'draft'
        
        return 'active'
    
    def update_status_from_dates(self):
        from django.utils import timezone
        
        if hasattr(self, 'manual_override') and self.manual_override:
            return self.status
        
        now = timezone.now()
        if self.end_date and self.end_date <= now:
            self.status = 'completed'
        elif self.start_date and self.start_date > now:
            self.status = 'scheduled'
        elif self.status not in ['paused', 'draft', 'cancelled']:
            self.status = 'active'
        
        self.save(update_fields=['status'])
        return self.status


class AdMetric(models.Model):
    """Reklam metrikleri modeli"""
    campaign = models.ForeignKey(AdCampaign, on_delete=models.CASCADE, related_name='metrics')
    date = models.DateField()
    impressions = models.IntegerField(default=0)
    clicks = models.IntegerField(default=0)
    likes = models.IntegerField(default=0)
    comments = models.IntegerField(default=0)
    shares = models.IntegerField(default=0)
    views = models.IntegerField(default=0)
    ctr = models.FloatField(default=0.0)
    engagement_rate = models.FloatField(default=0.0)
    spend = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    revenue = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    
    class Meta:
        verbose_name = 'Reklam Metriği'
        verbose_name_plural = 'Reklam Metrikleri'
        unique_together = ['campaign', 'date']
        ordering = ['-date']
    
    def __str__(self):
        return f"{self.campaign.campaign_name} - {self.date}"