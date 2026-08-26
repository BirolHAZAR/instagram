from django.db import models
from .base import User
from .instagram import InstagramAccount, InstagramPostQueue
from .campaigns import AdCampaign


class CreativeTemplate(models.Model):
    TEMPLATE_TYPES = [
        ('ad_copy', 'Reklam Metni'), ('visual_brief', 'Görsel Briefi'),
        ('campaign_strategy', 'Kampanya Stratejisi'), ('hashtag_set', 'Hashtag Seti'),
        ('full_package', 'Tam Paket (Metin + Görsel + Strateji)'),
    ]
    TONE_CHOICES = [
        ('professional', 'Profesyonel'), ('friendly', 'Samimi'), ('urgent', 'Acil/Harekete Geçirici'),
        ('luxury', 'Lüks/Premium'), ('humorous', 'Eğlenceli/Esprili'), ('emotional', 'Duygusal'), ('educational', 'Eğitici'),
    ]

    name = models.CharField(max_length=200, verbose_name="Şablon Adı")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='creative_templates', null=True, blank=True)
    is_premium = models.BooleanField(default=False, verbose_name="Premium Şablon")
    is_public = models.BooleanField(default=False, verbose_name="Herkese Açık")
    template_type = models.CharField(max_length=30, choices=TEMPLATE_TYPES, default='ad_copy')
    tone = models.CharField(max_length=20, choices=TONE_CHOICES, default='professional')
    prompt_template = models.TextField(help_text="AI prompt şablonu. {placeholders} kullanılabilir.")
    default_settings = models.JSONField(default=dict, blank=True)
    example_output = models.JSONField(default=dict, blank=True)
    usage_count = models.IntegerField(default=0, verbose_name="Kullanım Sayısı")
    rating = models.FloatField(default=0.0, verbose_name="Ortalama Puan")
    rating_count = models.IntegerField(default=0, verbose_name="Oy Sayısı")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Yaratıcı Şablon'
        verbose_name_plural = 'Yaratıcı Şablonlar'
        ordering = ['-usage_count', '-rating']

    def __str__(self):
        return f"{self.name} ({self.get_template_type_display()})"


class CreativeProject(models.Model):
    STATUS_CHOICES = [('draft', 'Taslak'), ('generating', 'Üretiliyor'), ('completed', 'Tamamlandı'), ('approved', 'Onaylandı'), ('published', 'Yayınlandı'), ('rejected', 'Reddedildi')]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='creative_projects')
    name = models.CharField(max_length=300, verbose_name="Proje Adı")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    source_type = models.CharField(max_length=30, choices=[('competitor_ad', 'Rakip Reklamı'), ('my_ad', 'Kendi Reklamım'), ('trend', 'Trend Konu'), ('scratch', 'Sıfırdan')])
    source_competitor = models.ForeignKey('core.Ad', on_delete=models.SET_NULL, null=True, blank=True, related_name='creative_source_competitor_projects')
    source_ad = models.ForeignKey('core.Ad', on_delete=models.SET_NULL, null=True, blank=True, related_name='creative_source_projects')
    target_instagram_account = models.ForeignKey(InstagramAccount, on_delete=models.SET_NULL, null=True, blank=True)
    target_campaign = models.ForeignKey(AdCampaign, on_delete=models.SET_NULL, null=True, blank=True)
    template = models.ForeignKey(CreativeTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    tone = models.CharField(max_length=20, choices=CreativeTemplate.TONE_CHOICES, default='professional')
    target_audience = models.TextField(blank=True, null=True, help_text="Hedef kitle açıklaması")
    product_description = models.TextField(blank=True, null=True, help_text="Ürün/hizmet açıklaması")
    keywords = models.JSONField(default=list, blank=True, help_text="Anahtar kelimeler")
    generated_variants = models.JSONField(default=list, blank=True, verbose_name="Üretilen Varyantlar")
    selected_variant = models.IntegerField(null=True, blank=True, verbose_name="Seçilen Varyant")
    ai_model = models.CharField(max_length=50, default='gpt-4o')
    ai_tokens_used = models.IntegerField(default=0)
    generation_time = models.FloatField(default=0.0, verbose_name="Üretim Süresi (sn)")
    published_to_queue = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Yaratıcı Proje'
        verbose_name_plural = 'Yaratıcı Projeler'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.status}"

from django.utils import timezone
class GeneratedContent(models.Model):
    CONTENT_TYPES = [('caption', 'Caption'), ('headline', 'Başlık'), ('description', 'Açıklama'), ('hashtag', 'Hashtag'), ('full_ad', 'Tam Reklam')]
    project = models.ForeignKey(CreativeProject, on_delete=models.CASCADE, related_name='contents')
    content_type = models.CharField(max_length=20, choices=CONTENT_TYPES)
    content = models.TextField()
    score = models.FloatField(default=0.0, verbose_name="AI Skoru")
    is_selected = models.BooleanField(default=False)
    created_at = models.DateTimeField(
    default=timezone.now)

    class Meta:
        verbose_name = 'Üretilen İçerik'
        verbose_name_plural = 'Üretilen İçerikler'
        ordering = ['-score', '-created_at']

    def __str__(self):
        return f"{self.get_content_type_display()} - {self.score}"
