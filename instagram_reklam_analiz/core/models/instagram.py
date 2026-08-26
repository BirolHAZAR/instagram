# core/models/instagram.py
"""
Instagram hesap modelleri - base.py ve membership.py'ye bağımlıdır
"""
from django.db import models
from core.fields import EncryptedTextField
from .base import User


class InstagramAccount(models.Model):
    """Instagram hesap modeli"""
    ACCOUNT_TYPES = [
        ('personal', 'Kişisel Hesap'),
        ('business', 'İşletme Hesabı'),
        ('creator', 'Creator Hesabı'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='instagram_accounts')
    username = models.CharField(max_length=100, verbose_name="Kullanıcı Adı")
    instagram_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="Instagram ID")
    access_token = EncryptedTextField(blank=True, null=True, verbose_name="Access Token")
    followers_count = models.IntegerField(default=0, verbose_name="Takipçi Sayısı")
    following_count = models.IntegerField(default=0, verbose_name="Takip Edilen")
    media_count = models.IntegerField(default=0, verbose_name="Medya Sayısı")
    account_type = models.CharField(max_length=50, choices=ACCOUNT_TYPES, default='personal', verbose_name="Hesap Türü")
    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")
    last_sync = models.DateTimeField(null=True, blank=True, verbose_name="Son Senkronizasyon")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    instagram_business_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="İşletme ID")
    full_name = models.CharField(max_length=200, blank=True, null=True, verbose_name="Tam Ad")
    profile_picture = models.URLField(blank=True, null=True, verbose_name="Profil Resmi")
    has_ads_permission = models.BooleanField(default=False, verbose_name="Reklam İzni")
    has_publish_permission = models.BooleanField(default=False, verbose_name="Yayınlama İzni")
    ad_account_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="Reklam Hesabı ID")
    
    class Meta:
        verbose_name = 'Instagram Hesabı'
        verbose_name_plural = 'Instagram Hesapları'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"@{self.username}"
    
    def get_followers_count_display(self):
        if self.followers_count >= 1000000:
            return f"{self.followers_count / 1000000:.1f}M"
        elif self.followers_count >= 1000:
            return f"{self.followers_count / 1000:.1f}K"
        return str(self.followers_count)


class InstagramMedia(models.Model):
    """Instagram medya modeli"""
    MEDIA_TYPES = [
        ('image', 'Görsel'),
        ('video', 'Video'),
        ('carousel', 'Karousel'),
    ]
    
    instagram_account = models.ForeignKey(InstagramAccount, on_delete=models.CASCADE, related_name='medias')
    media_id = models.CharField(max_length=100, unique=True)
    media_type = models.CharField(max_length=20, choices=MEDIA_TYPES)
    caption = models.TextField(blank=True, null=True)
    media_url = models.URLField(blank=True, null=True)
    permalink = models.URLField(blank=True, null=True)
    timestamp = models.DateTimeField(null=True, blank=True)
    like_count = models.IntegerField(default=0)
    comments_count = models.IntegerField(default=0)
    insights = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Instagram Medya'
        verbose_name_plural = 'Instagram Medyaları'
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.instagram_account.username} - {self.timestamp}"


class InstagramInsight(models.Model):
    """Instagram içgörü modeli"""
    instagram_account = models.ForeignKey(InstagramAccount, on_delete=models.CASCADE, related_name='insights')
    date = models.DateField()
    impressions = models.IntegerField(default=0)
    reach = models.IntegerField(default=0)
    profile_views = models.IntegerField(default=0)
    website_clicks = models.IntegerField(default=0)
    email_contacts = models.IntegerField(default=0)
    phone_calls = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Instagram İçgörü'
        verbose_name_plural = 'Instagram İçgörüleri'
        unique_together = ['instagram_account', 'date']
        ordering = ['-date']
    
    def __str__(self):
        return f"{self.instagram_account.username} - {self.date}"


class InstagramPostQueue(models.Model):
    """Instagram paylaşım kuyruğu"""
    STATUS_CHOICES = [
        ('pending', 'Beklemede'),
        ('processing', 'Gönderiliyor'),
        ('published', 'Paylaşıldı'),
        ('failed', 'Hata Oluştu'),
    ]
    
    instagram_account = models.ForeignKey(InstagramAccount, on_delete=models.CASCADE)
    image_url = models.URLField(help_text="Paylaşılacak görselin URL'i")
    caption = models.TextField()
    container_id = models.CharField(max_length=100, blank=True, null=True)
    media_id = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True, null=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Instagram Paylaşım Kuyruğu'
        verbose_name_plural = 'Instagram Paylaşım Kuyruğu'
    
    def __str__(self):
        return f"{self.instagram_account.username} - {self.status}"