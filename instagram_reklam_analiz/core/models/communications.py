from django.conf import settings
from django.db import models
from django.utils import timezone


class LifecycleEmailCampaign(models.Model):
    name = models.CharField(max_length=160, default="14 gün sonrası abonelik hatırlatması")
    subject = models.CharField(max_length=200, default="Reklam bütçeniz daha verimli çalışmaya hazır")
    body = models.TextField(default="14 günlük deneyiminiz tamamlandı. Şimdi reklam verilerinizi gerçek büyüme kararlarına dönüştürme zamanı.\n\nDağınık raporlar yerine tüm hesaplarınızı tek panelde izleyin; bütçe, ROAS ve kreatif kararlarında Octo AI desteğiyle daha hızlı hareket edin.")
    cta_text = models.CharField(max_length=80, default="Planınızı Seçin")
    cta_url = models.URLField(default="https://reklamanaliz.net/pricing/")
    html_template = models.TextField(blank=True, default="", help_text="İsteğe bağlıdır. Boş bırakırsanız profesyonel varsayılan tasarım kullanılır. {{ first_name }}, {{ campaign.subject }}, {{ campaign.body }}, {{ campaign.cta_url }} değişkenlerini kullanabilirsiniz.")
    delay_days = models.PositiveSmallIntegerField(default=14, help_text="Üyelik başlangıcından kaç gün sonra ilk e-posta gönderilsin?")
    repeat_days = models.PositiveSmallIntegerField(default=7, help_text="Abone olunmadıysa kaç günde bir tekrar gönderilsin?")
    max_sends = models.PositiveSmallIntegerField(default=3, help_text="Bir kullanıcıya en fazla kaç kez gönderilsin?")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Abonelik Takip E-postası"
        verbose_name_plural = "Abonelik Takip E-postaları"

    def __str__(self):
        return self.name


class LifecycleEmailDelivery(models.Model):
    STATUS_CHOICES = [("sent", "Gönderildi"), ("failed", "Başarısız")]
    campaign = models.ForeignKey(LifecycleEmailCampaign, on_delete=models.CASCADE, related_name="deliveries")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lifecycle_email_deliveries")
    sequence = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Takip E-postası Gönderimi"
        verbose_name_plural = "Takip E-postası Gönderimleri"
        constraints = [models.UniqueConstraint(fields=["campaign", "user", "sequence"], name="uniq_lifecycle_email_delivery")]
        ordering = ["-sent_at"]


class Announcement(models.Model):
    title = models.CharField(max_length=200, verbose_name="Duyuru başlığı")
    message = models.TextField(verbose_name="Duyuru metni")
    html_template = models.TextField(blank=True, default="", verbose_name="Özel e-posta HTML şablonu", help_text="Boş bırakırsanız profesyonel varsayılan duyuru tasarımı kullanılır. {{ announcement.title }}, {{ announcement.message }} ve {{ announcement.link }} değişkenlerini kullanabilirsiniz.")
    link = models.URLField(blank=True, default="", verbose_name="Bağlantı")
    publish_at = models.DateTimeField(default=timezone.now, verbose_name="Yayın zamanı")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="Bitiş zamanı")
    send_in_app = models.BooleanField(default=True, verbose_name="Panel bildirimi gönder")
    send_email = models.BooleanField(default=False, verbose_name="E-posta gönder")
    is_active = models.BooleanField(default=True, verbose_name="Aktif")
    processed_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Genel Duyuru"
        verbose_name_plural = "Genel Duyurular"
        ordering = ["-publish_at"]

    def __str__(self):
        return self.title


class AnnouncementDelivery(models.Model):
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="deliveries")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="announcement_deliveries")
    notification_created = models.BooleanField(default=False)
    email_sent = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Duyuru Teslimatı"
        verbose_name_plural = "Duyuru Teslimatları"
        constraints = [models.UniqueConstraint(fields=["announcement", "user"], name="uniq_announcement_delivery")]
        ordering = ["-created_at"]
