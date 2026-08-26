# core/models/error_log.py
from django.db import models
from django.utils import timezone
from .base import User

class SystemErrorLog(models.Model):
    """Sistem hata logları - Kendi veritabanımızda tutacağız"""
    
    SEVERITY_CHOICES = [
        ('critical', '🚨 Kritik'),
        ('error', '❌ Hata'),
        ('warning', '⚠️ Uyarı'),
        ('info', 'ℹ️ Bilgi'),
    ]
    
    STATUS_CHOICES = [
        ('new', '🆕 Yeni'),
        ('investigating', '🔍 İnceleniyor'),
        ('resolved', '✅ Çözüldü'),
        ('ignored', '📌 Görmezden Gelindi'),
    ]
    
    # Temel bilgiler
    error_id = models.CharField(max_length=100, unique=True, blank=True)
    message = models.TextField()
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='error')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    
    # Hata detayları
    traceback = models.TextField(blank=True, null=True)
    file_name = models.CharField(max_length=500, blank=True, null=True)
    line_number = models.IntegerField(blank=True, null=True)
    function_name = models.CharField(max_length=200, blank=True, null=True)
    
    # Request bilgileri
    url = models.CharField(max_length=500, blank=True, null=True)
    method = models.CharField(max_length=10, blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    
    # Kullanıcı bilgisi
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='error_logs')
    
    # Ek bilgiler
    tags = models.JSONField(default=dict, blank=True)
    extra_data = models.JSONField(default=dict, blank=True)
    
    # Çözüm bilgileri
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_errors')
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True, null=True)
    
    # Zaman damgaları
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Sistem Hatası'
        verbose_name_plural = 'Sistem Hataları'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['severity', 'status']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['user']),
        ]
    
    def __str__(self):
        return f"[{self.get_severity_display()}] {self.message[:100]}"
    
    @property
    def short_message(self):
        return self.message[:100]
    
    def mark_as_resolved(self, user, note=''):
        self.status = 'resolved'
        self.resolved_by = user
        self.resolved_at = timezone.now()
        self.resolution_note = note
        self.save()