from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class LegalSiteSettings(models.Model):
    company_name = models.CharField(max_length=240, verbose_name="Resmi şirket unvanı")
    brand_name = models.CharField(max_length=120, default="ReklamAnaliz.net", verbose_name="Marka adı")
    address = models.TextField(blank=True, default="", verbose_name="Açık adres")
    tax_office = models.CharField(max_length=120, blank=True, default="", verbose_name="Vergi dairesi")
    tax_number = models.CharField(max_length=32, blank=True, default="", verbose_name="Vergi numarası")
    mersis_number = models.CharField(max_length=32, blank=True, default="", verbose_name="MERSİS numarası")
    kep_address = models.EmailField(blank=True, default="", verbose_name="KEP adresi")
    support_email = models.EmailField(default="info@reklamanaliz.net", verbose_name="Destek e-postası")
    kvkk_email = models.EmailField(default="info@reklamanaliz.net", verbose_name="KVKK başvuru e-postası")
    phone = models.CharField(max_length=32, blank=True, default="", verbose_name="Telefon")
    sla_target = models.DecimalField(max_digits=5, decimal_places=2, default=99.50, verbose_name="Aylık SLA hedefi (%)")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hukuki Metin Şirket Ayarı"
        verbose_name_plural = "Hukuki Metin Şirket Ayarları"

    def __str__(self):
        return self.company_name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "company_name": "HZR Yazılım Danışmanlık Dijital Paz. LTD ŞTİ",
                "address": "Bakırköy",
            },
        )
        return obj


class LegalDocument(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_ARCHIVED = "archived"
    STATUS_CHOICES = (
        (STATUS_DRAFT, "Taslak"),
        (STATUS_PUBLISHED, "Yayında"),
        (STATUS_ARCHIVED, "Arşiv"),
    )

    CATEGORY_SALES = "sales"
    CATEGORY_PRIVACY = "privacy"
    CATEGORY_PLATFORM = "platform"
    CATEGORY_SERVICE = "service"
    CATEGORY_AI = "ai"
    CATEGORY_CHOICES = (
        (CATEGORY_SALES, "Satış ve üyelik"),
        (CATEGORY_PRIVACY, "Gizlilik ve kişisel veriler"),
        (CATEGORY_PLATFORM, "Platform verileri"),
        (CATEGORY_SERVICE, "Hizmet ve güvenlik"),
        (CATEGORY_AI, "Yapay zeka"),
    )

    slug = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=220, verbose_name="Başlık")
    category = models.CharField(max_length=24, choices=CATEGORY_CHOICES, verbose_name="Kategori")
    summary = models.TextField(blank=True, default="", verbose_name="Kısa açıklama")
    content = models.TextField(
        verbose_name="Metin (HTML)",
        help_text="Başlıklar için <h2>, paragraflar için <p>, listeler için <ul><li> kullanabilirsiniz.",
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    version = models.CharField(max_length=24, default="1.0", verbose_name="Sürüm")
    effective_date = models.DateField(null=True, blank=True, verbose_name="Yürürlük tarihi")
    published_at = models.DateTimeField(null=True, blank=True, editable=False, verbose_name="Yayın zamanı")
    display_order = models.PositiveSmallIntegerField(default=100, verbose_name="Gösterim sırası")
    requires_acceptance = models.BooleanField(default=False, verbose_name="Kullanıcı onayı gerektirir")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_legal_documents",
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hukuki Metin"
        verbose_name_plural = "Hukuki Metinler"
        ordering = ("display_order", "title")

    def __str__(self):
        return f"{self.title} (v{self.version})"

    def get_absolute_url(self):
        return reverse("legal_document_detail", kwargs={"slug": self.slug})

    def publish(self, user=None):
        self.status = self.STATUS_PUBLISHED
        self.published_at = timezone.now()
        if not self.effective_date:
            self.effective_date = timezone.localdate()
        if user and getattr(user, "is_authenticated", False):
            self.updated_by = user
        self.save(update_fields=("status", "published_at", "effective_date", "updated_by", "updated_at"))

    def unpublish(self, user=None):
        self.status = self.STATUS_DRAFT
        if user and getattr(user, "is_authenticated", False):
            self.updated_by = user
        self.save(update_fields=("status", "updated_by", "updated_at"))


class LegalAcceptance(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="legal_acceptances",
        verbose_name="Kullanıcı",
    )
    payment = models.OneToOneField(
        "core.Payment",
        on_delete=models.PROTECT,
        related_name="legal_acceptance",
        verbose_name="Ödeme",
    )
    document_snapshots = models.JSONField(default=list, verbose_name="Onaylanan belge kopyaları")
    acceptance_statement = models.TextField(verbose_name="Onay beyanı")
    immediate_service_consent = models.BooleanField(default=False, verbose_name="Hizmetin hemen başlaması onayı")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP adresi")
    user_agent = models.CharField(max_length=500, blank=True, default="", verbose_name="Tarayıcı bilgisi")
    accepted_at = models.DateTimeField(default=timezone.now, verbose_name="Onay zamanı")
    email_recipient = models.EmailField(blank=True, default="", verbose_name="E-posta alıcısı")
    email_sent_at = models.DateTimeField(null=True, blank=True, verbose_name="E-posta gönderim zamanı")
    email_error = models.TextField(blank=True, default="", verbose_name="E-posta hatası")

    class Meta:
        verbose_name = "Sözleşme Onayı"
        verbose_name_plural = "Sözleşme Onayları"
        ordering = ("-accepted_at",)

    def __str__(self):
        return f"Ödeme #{self.payment_id} - {self.user} - {self.accepted_at:%d.%m.%Y %H:%M}"
