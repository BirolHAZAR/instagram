# core/models/membership.py
"""
Üyelik ve ödeme modelleri - SADECE base.py'ye bağımlıdır
"""
from django.db import models
from django.utils import timezone
from decimal import Decimal
import hashlib
import secrets
import string

# User modelini base'den import et
from .base import User
from core.fields import EncryptedTextField


class MembershipPlan(models.Model):
    """Üyelik planı modeli"""
    PLAN_TYPE_BUSINESS = "business"
    PLAN_TYPE_AGENCY = "agency"
    PLAN_TYPE_LEGACY = "legacy"
    PLAN_TYPE_CHOICES = [
        (PLAN_TYPE_BUSINESS, "İşletme"),
        (PLAN_TYPE_AGENCY, "Ajans / Ekip"),
        (PLAN_TYPE_LEGACY, "Eski Plan"),
    ]

    name = models.CharField(max_length=50, unique=True, verbose_name="Plan Adı")
    display_name = models.CharField(max_length=100, verbose_name="Görünen Ad")
    plan_type = models.CharField(max_length=20, choices=PLAN_TYPE_CHOICES, default=PLAN_TYPE_BUSINESS, db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Fiyat (KDV Hariç)")
    price_with_kdv = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Fiyat (KDV Dahil)")
    features = models.TextField(help_text="Her satıra bir özellik", verbose_name="Özellikler")
    order = models.IntegerField(default=0, verbose_name="Sıralama")
    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")
    
    # Rozet Bilgileri
    badge = models.CharField(max_length=50, blank=True, null=True, verbose_name="Rozet")
    badge_color = models.CharField(max_length=7, blank=True, null=True, verbose_name="Rozet Rengi")
    is_most_popular = models.BooleanField(default=False, verbose_name="En Popüler")
    
    # Tüm platformlardaki bağlı hesapların toplam limiti
    max_instagram_accounts = models.IntegerField(
        default=1,
        verbose_name="Maksimum toplam platform hesabı",
        help_text="Platform başına değil, tüm platform hesaplarının toplamına uygulanır.",
    )
    
    # İçerik Çekme Limitleri
    max_content_fetch_count = models.IntegerField(default=0, help_text="0 = sınırsız, >0 = maksimum gönderi sayısı")
    content_fetch_period_days = models.IntegerField(default=0, help_text="0 = manuel, >0 = şu kadar günlük veri")
    auto_fetch_enabled = models.BooleanField(default=False)
    auto_fetch_frequency = models.CharField(
        max_length=20,
        choices=[
            ('manual', 'Manuel'), ('daily', 'Günlük'),
            ('weekly', 'Haftalık'), ('realtime', 'Gerçek Zamanlı'),
        ],
        default='manual'
    )
    ad_sync_interval_minutes = models.PositiveIntegerField(default=1440, verbose_name="Reklam güncelleme aralığı (dk)")
    competitor_sync_interval_minutes = models.PositiveIntegerField(default=1440, verbose_name="Rakip güncelleme aralığı (dk)")
    organic_sync_interval_minutes = models.PositiveIntegerField(default=1440, verbose_name="Post güncelleme aralığı (dk)")
    marketplace_sync_interval_minutes = models.PositiveIntegerField(default=1440, verbose_name="Ürün/fiyat güncelleme aralığı (dk)")
    allow_manual_ad_sync = models.BooleanField(default=True, verbose_name="Manuel reklam yenileme")
    allow_manual_competitor_sync = models.BooleanField(default=True, verbose_name="Manuel rakip yenileme")
    allow_manual_organic_sync = models.BooleanField(default=True, verbose_name="Manuel post yenileme")
    allow_manual_marketplace_sync = models.BooleanField(default=True, verbose_name="Manuel ürün/fiyat yenileme")
    max_sync_records = models.PositiveIntegerField(default=1000, verbose_name="Çalışma başına azami kayıt")
    
    # Rakip Limitleri
    max_competitors = models.IntegerField(default=0, verbose_name="Maksimum toplam rakip", help_text="0 = rakip takibi yok")
    competitor_fetch_enabled = models.BooleanField(default=False)
    competitor_fetch_frequency = models.CharField(
        max_length=20,
        choices=[('manual', 'Manuel'), ('daily', 'Günlük'), ('realtime', 'Gerçek Zamanlı')],
        default='manual'
    )
    competitor_auto_discovery = models.BooleanField(default=False)
    
    # AI Kullanım Hakları
    ai_analysis_per_month = models.IntegerField(default=0, verbose_name="Aylık AI Analiz Hakkı")
    ai_recommendation_per_month = models.IntegerField(default=0, verbose_name='Aylık AI Öneri Hakkı')
    ai_analysis_per_week = models.IntegerField(default=0, verbose_name="Haftalık AI Analiz Hakkı")
    ai_recommendation_per_week = models.IntegerField(default=0, verbose_name="Haftalık AI Öneri Hakkı")
    ai_credits_per_month = models.IntegerField(default=0, verbose_name="Aylık AI Kredi")
    allow_ai_credit_topup = models.BooleanField(default=True, verbose_name="Ek AI kredi satın alabilir mi?")
    ai_content_generation = models.BooleanField(default=False, help_text="AI ile içerik üretimi yapabilir mi?")
    marketplace_product_research_per_month = models.IntegerField(default=0, verbose_name="Aylık ürün araştırma hakkı")
    marketplace_price_check_per_month = models.IntegerField(default=0, verbose_name="Aylık fiyat kontrol hakkı")
    
    # Kampanya Limitleri
    max_campaign_templates = models.IntegerField(default=0, help_text="Aylık kampanya şablonu hakkı (0 = yok)")
    has_campaign_calendar = models.BooleanField(default=False, help_text="30 günlük otomatik içerik takvimi")
    has_ab_test_campaigns = models.BooleanField(default=False, help_text="A/B testli kampanya çiftleri")
    
    # İçerik Takvimi
    has_content_calendar = models.BooleanField(default=False, help_text="İçerik takvimi var mı?")
    content_calendar_days = models.IntegerField(default=0, help_text="İçerik takvimi kaç günlük?")
    has_ai_content_generation = models.BooleanField(default=False, help_text="AI içerik üretimi (takvim için)")
    
    # Gelişmiş Özellikler
    has_analytics = models.BooleanField(default=False, help_text="Gelişmiş analitik paneli")
    has_advanced_reporting = models.BooleanField(default=False, help_text="Gelişmiş raporlama (PDF/PPT)")
    has_opportunity_finder = models.BooleanField(default=False, help_text="Fırsat bulucu AI")
    has_api_access = models.BooleanField(default=False)
    has_white_label = models.BooleanField(default=False, help_text="Beyaz etiket raporlama")
    has_team_members = models.BooleanField(default=False)
    max_team_members = models.IntegerField(default=0, verbose_name="Ajans azami kullanıcı/koltuk")
    included_seats = models.IntegerField(
        default=1,
        verbose_name="Ajans dahil kullanıcı/koltuk",
        help_text="Ajans paketinde fiyata dahil kullanıcı/koltuk sayısıdır.",
    )
    max_client_accounts = models.IntegerField(
        default=0,
        verbose_name="Ajans müşteri/marka alanı",
        help_text="Ajans paketindeki müşteri/marka çalışma alanı limitidir.",
    )
    has_crisis_alert = models.BooleanField(default=False, help_text="Kriz alarmı")
    has_strategy_webinar = models.BooleanField(default=False, help_text="Strateji webinarı")
    
    # Destek
    priority_support = models.BooleanField(default=False)
    has_dedicated_manager = models.BooleanField(default=False, help_text="Özel hesap yöneticisi")
    
    # Eski/Kalan alanlar
    max_products = models.IntegerField(default=0, help_text="Ürün/İçerik takip limiti")
    max_campaigns = models.IntegerField(default=0, help_text="Eski kampanya limiti")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Üyelik Planı'
        verbose_name_plural = 'Üyelik Planları'
        ordering = ['order', 'price']

    def __str__(self):
        return self.display_name

    def get_feature_list(self):
        if self.features:
            return self.features.strip().split('\n')
        return []

    @property
    def yearly_price(self):
        return self.price * 12 * Decimal('0.8')

    @property
    def yearly_price_with_kdv(self):
        return self.yearly_price * self.price_with_kdv / self.price if self.price else 0


class PlanAuthorizationPolicy(MembershipPlan):
    """Admin proxy exposing plan permissions, quotas and sync policy in one place."""

    class Meta:
        proxy = True
        verbose_name = "Plan yetki ve limit tablosu"
        verbose_name_plural = "Plan yetki ve limit tablosu"


class UserSubscription(models.Model):
    BILLING_MONTHLY = "monthly"
    BILLING_YEARLY = "yearly"
    BILLING_PERIOD_CHOICES = [
        (BILLING_MONTHLY, "Aylık"),
        (BILLING_YEARLY, "Yıllık"),
    ]

    """Kullanıcı aboneliği"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey(MembershipPlan, on_delete=models.SET_NULL, null=True)
    organization = models.ForeignKey(
        "Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subscriptions",
    )
    start_date = models.DateField(verbose_name="Başlangıç Tarihi")
    end_date = models.DateField(verbose_name="Bitiş Tarihi")
    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")
    billing_period = models.CharField(max_length=20, choices=BILLING_PERIOD_CHOICES, default=BILLING_MONTHLY)
    auto_renew = models.BooleanField(default=True, verbose_name="Otomatik Yenileme")
    default_payment_method = models.ForeignKey("PaymentMethod", on_delete=models.SET_NULL, null=True, blank=True, related_name="subscriptions")
    next_renewal_date = models.DateField(null=True, blank=True, db_index=True)
    last_renewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Kullanıcı Aboneliği'
        verbose_name_plural = 'Kullanıcı Abonelikleri'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} - {self.plan.display_name if self.plan else 'Plansız'}"

    def is_expired(self):
        return self.end_date < timezone.now().date()

    def days_remaining(self):
        delta = self.end_date - timezone.now().date()
        return max(0, delta.days)
    
    def remaining_days(self):
        return self.days_remaining()


def generate_referral_code():
    alphabet = string.ascii_uppercase + string.digits
    return "RA-" + "".join(secrets.choice(alphabet) for _ in range(8))


class ReferralCode(models.Model):
    REWARD_AI_CREDITS = "ai_credits"
    REWARD_SUBSCRIPTION_DAYS = "subscription_days"
    REWARD_CHOICES = [
        (REWARD_AI_CREDITS, "AI kredi"),
        (REWARD_SUBSCRIPTION_DAYS, "Abonelik günü"),
    ]

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="referral_codes", verbose_name="Kod sahibi")
    code = models.CharField(max_length=40, unique=True, default=generate_referral_code, verbose_name="Promosyon kodu")
    reward_type = models.CharField(max_length=30, choices=REWARD_CHOICES, default=REWARD_AI_CREDITS, verbose_name="Ödül tipi")
    reward_amount = models.PositiveIntegerField(default=10000, verbose_name="Ödül miktarı")
    description = models.CharField(max_length=180, blank=True, default="", verbose_name="Açıklama")
    max_uses = models.PositiveIntegerField(null=True, blank=True, verbose_name="Toplam kullanım limiti")
    valid_until = models.DateField(null=True, blank=True, verbose_name="Son geçerlilik tarihi")
    is_active = models.BooleanField(default=True, verbose_name="Aktif")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Referans / Promosyon Kodu"
        verbose_name_plural = "Referans / Promosyon Kodları"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["owner", "is_active"]),
        ]

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.owner.email}"

    @property
    def awarded_count(self):
        return self.rewards.filter(status=ReferralReward.STATUS_AWARDED).count()

    def can_be_used(self, by_user=None, today=None):
        today = today or timezone.localdate()
        if not self.is_active:
            return False, "Bu promosyon kodu aktif değil."
        if self.valid_until and self.valid_until < today:
            return False, "Bu promosyon kodunun süresi dolmuş."
        if by_user is not None and by_user.id == self.owner_id:
            return False, "Kendi promosyon kodunuzu kullanamazsınız."
        if self.max_uses and self.awarded_count >= self.max_uses:
            return False, "Bu promosyon kodunun kullanım limiti dolmuş."
        return True, ""


class ReferralProgramSetting(models.Model):
    singleton_key = models.CharField(max_length=40, unique=True, default="default", editable=False)
    is_enabled = models.BooleanField(default=True, verbose_name="Referans/promosyon sistemi aktif")
    new_customer_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("10.00"), verbose_name="Yeni üye indirim yüzdesi")
    default_reward_type = models.CharField(max_length=30, choices=ReferralCode.REWARD_CHOICES, default=ReferralCode.REWARD_AI_CREDITS, verbose_name="Varsayılan ödül tipi")
    default_reward_amount = models.PositiveIntegerField(default=10000, verbose_name="Varsayılan ödül miktarı")
    business_reward_ai_credits = models.PositiveIntegerField(default=10000, verbose_name="İşletme planı ödül kredisi")
    agency_reward_ai_credits = models.PositiveIntegerField(default=25000, verbose_name="Ajans planı ödül kredisi")
    yearly_reward_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("2.00"), verbose_name="Yıllık abonelik ödül çarpanı")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Referans Program Ayarı"
        verbose_name_plural = "Referans Program Ayarı"

    def save(self, *args, **kwargs):
        self.singleton_key = "default"
        super().save(*args, **kwargs)

    def __str__(self):
        return "Referans programı aktif" if self.is_enabled else "Referans programı kapalı"

    @classmethod
    def current(cls):
        obj, _ = cls.objects.get_or_create(singleton_key="default")
        return obj


class ReferralProgramRule(models.Model):
    PLAN_ANY = "any"
    BILLING_ANY = "any"
    PLAN_TYPE_CHOICES = [
        (PLAN_ANY, "Tüm plan tipleri"),
        (MembershipPlan.PLAN_TYPE_BUSINESS, "İşletme"),
        (MembershipPlan.PLAN_TYPE_AGENCY, "Ajans"),
    ]
    BILLING_PERIOD_CHOICES = [
        (BILLING_ANY, "Tüm dönemler"),
        (UserSubscription.BILLING_MONTHLY, "Aylık"),
        (UserSubscription.BILLING_YEARLY, "Yıllık"),
    ]

    name = models.CharField(max_length=120, verbose_name="Kural adı")
    plan_type = models.CharField(max_length=20, choices=PLAN_TYPE_CHOICES, default=PLAN_ANY, db_index=True, verbose_name="Plan tipi")
    billing_period = models.CharField(max_length=20, choices=BILLING_PERIOD_CHOICES, default=BILLING_ANY, db_index=True, verbose_name="Faturalama dönemi")
    new_customer_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("10.00"), verbose_name="Yeni üye indirim yüzdesi")
    reward_type = models.CharField(max_length=30, choices=ReferralCode.REWARD_CHOICES, default=ReferralCode.REWARD_AI_CREDITS, verbose_name="Ödül tipi")
    reward_amount = models.PositiveIntegerField(default=10000, verbose_name="Öneren üye ödül miktarı")
    priority = models.PositiveSmallIntegerField(default=100, verbose_name="Öncelik")
    is_active = models.BooleanField(default=True, verbose_name="Aktif")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Referans Program Kuralı"
        verbose_name_plural = "Referans Program Kuralları"
        ordering = ["priority", "plan_type", "billing_period", "name"]
        indexes = [
            models.Index(fields=["is_active", "plan_type", "billing_period", "priority"]),
        ]

    def __str__(self):
        return self.name

    def specificity_score(self, plan_type, billing_period):
        score = 0
        if self.plan_type == plan_type:
            score += 2
        elif self.plan_type != self.PLAN_ANY:
            return -1
        if self.billing_period == billing_period:
            score += 2
        elif self.billing_period != self.BILLING_ANY:
            return -1
        return score


class ReferralReward(models.Model):
    STATUS_PENDING = "pending"
    STATUS_AWARDED = "awarded"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Beklemede"),
        (STATUS_AWARDED, "Hak tanımlandı"),
        (STATUS_CANCELLED, "İptal"),
    ]

    referral_code = models.ForeignKey(ReferralCode, on_delete=models.PROTECT, related_name="rewards", verbose_name="Promosyon kodu")
    referrer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="referral_rewards_earned", verbose_name="Hak sahibi")
    referred_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="referral_rewards_triggered", verbose_name="Abone olan üye")
    subscription = models.ForeignKey(UserSubscription, on_delete=models.SET_NULL, null=True, blank=True, related_name="referral_rewards")
    payment = models.ForeignKey("Payment", on_delete=models.SET_NULL, null=True, blank=True, related_name="referral_rewards")
    reward_type = models.CharField(max_length=30, choices=ReferralCode.REWARD_CHOICES, verbose_name="Ödül tipi")
    reward_amount = models.PositiveIntegerField(default=0, verbose_name="Ödül miktarı")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True, verbose_name="Durum")
    awarded_at = models.DateTimeField(null=True, blank=True, verbose_name="Hak tanımlama zamanı")
    note = models.TextField(blank=True, default="", verbose_name="Not")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Referans Ödülü"
        verbose_name_plural = "Referans Ödülleri"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["referral_code", "referred_user"], name="uniq_referral_reward_code_user"),
            models.UniqueConstraint(
                fields=["payment"],
                condition=models.Q(payment__isnull=False),
                name="uniq_referral_reward_payment",
            ),
        ]
        indexes = [
            models.Index(fields=["referrer", "status", "-created_at"]),
            models.Index(fields=["referred_user", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.referral_code.code} -> {self.referrer.email} ({self.get_status_display()})"


class PaymentMethod(models.Model):
    """Kart yerine ödeme sağlayıcı token'ı saklar; tam kart/CVV saklanmaz."""
    PROVIDER_DEMO = "demo"
    PROVIDER_CHOICES = [
        (PROVIDER_DEMO, "Demo/Sanal POS"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payment_methods")
    provider = models.CharField(max_length=40, choices=PROVIDER_CHOICES, default=PROVIDER_DEMO)
    token_encrypted = EncryptedTextField()
    card_holder = models.CharField(max_length=120, blank=True, default="")
    card_brand = models.CharField(max_length=40, blank=True, default="")
    last4 = models.CharField(max_length=4)
    expiry_month = models.PositiveSmallIntegerField()
    expiry_year = models.PositiveSmallIntegerField()
    is_default = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ödeme Yöntemi"
        verbose_name_plural = "Ödeme Yöntemleri"
        ordering = ["-is_default", "-updated_at"]
        indexes = [
            models.Index(fields=["user", "is_active", "is_default"]),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.card_brand or 'Kart'} **** {self.last4}"


class AICreditPackage(models.Model):
    """Ek AI kredi satış paketi."""
    name = models.CharField(max_length=80, unique=True)
    display_name = models.CharField(max_length=120)
    credits = models.IntegerField(default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    price_with_kdv = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AI Kredi Paketi"
        verbose_name_plural = "AI Kredi Paketleri"
        ordering = ["order", "price"]

    def __str__(self):
        return self.display_name


class AIOperationTariff(models.Model):
    """Admin tarafindan yonetilen merkezi AI islem tarifesi."""

    key = models.SlugField(max_length=120, unique=True, verbose_name="Islem anahtari")
    display_name = models.CharField(max_length=160, verbose_name="Islem adi")
    category = models.CharField(max_length=80, blank=True, default="", verbose_name="Kategori")
    credit_cost = models.PositiveIntegerField(default=1, verbose_name="Kredi bedeli")
    model_name = models.CharField(max_length=120, blank=True, default="", verbose_name="OpenAI modeli")
    max_input_tokens = models.PositiveIntegerField(default=0, verbose_name="Maksimum giris token")
    max_output_tokens = models.PositiveIntegerField(default=0, verbose_name="Maksimum cikis token")
    max_calls = models.PositiveIntegerField(default=1, verbose_name="Islem basina azami AI cagrisi")
    cache_timeout_seconds = models.PositiveIntegerField(default=0, verbose_name="Sonuc onbellegi (saniye)")
    max_cost_usd = models.DecimalField(max_digits=10, decimal_places=4, default=0, verbose_name="Azami maliyet USD")
    safety_margin_percent = models.PositiveSmallIntegerField(default=30, verbose_name="Guvenlik marji %")
    uses_openai = models.BooleanField(default=True, verbose_name="OpenAI kullanir")
    is_active = models.BooleanField(default=True, verbose_name="Aktif")
    note = models.TextField(blank=True, default="", verbose_name="Not")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AI Islem Tarifesi"
        verbose_name_plural = "AI Islem Tarifeleri"
        ordering = ["category", "display_name"]

    def __str__(self):
        return f"{self.display_name} ({self.credit_cost} kredi)"


class AICreditLedger(models.Model):
    """AI kredi hareket defteri. Pozitif yükleme, negatif kullanım."""
    ACTION_GRANT = "grant"
    ACTION_PURCHASE = "purchase"
    ACTION_CONSUME = "consume"
    ACTION_REFUND = "refund"
    ACTION_ADJUSTMENT = "adjustment"
    ACTION_CHOICES = [
        (ACTION_GRANT, "Plan kredisi"),
        (ACTION_PURCHASE, "Satın alma"),
        (ACTION_CONSUME, "Kullanım"),
        (ACTION_REFUND, "İade"),
        (ACTION_ADJUSTMENT, "Manuel düzeltme"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ai_credit_ledger")
    organization = models.ForeignKey("Organization", on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_credit_ledger")
    subscription = models.ForeignKey(UserSubscription, on_delete=models.SET_NULL, null=True, blank=True)
    package = models.ForeignKey(AICreditPackage, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    amount = models.IntegerField(help_text="Pozitif kredi ekler, negatif kredi düşer.")
    balance_after = models.IntegerField(default=0)
    reference = models.CharField(max_length=120, blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "AI Kredi Hareketi"
        verbose_name_plural = "AI Kredi Hareketleri"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["organization", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.user} {self.amount:+d} kredi ({self.action})"


class UserAICreditBalance(models.Model):
    """Kullanici/ajans bazli guncel AI token bakiyesi."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ai_credit_balances")
    organization = models.ForeignKey("Organization", on_delete=models.CASCADE, null=True, blank=True, related_name="ai_credit_balances")
    subscription = models.ForeignKey(UserSubscription, on_delete=models.SET_NULL, null=True, blank=True)
    cycle_start = models.DateField(db_index=True)
    cycle_end = models.DateField(db_index=True)
    plan_credits = models.IntegerField(default=0, verbose_name="Plan kredisi")
    purchased_credits = models.IntegerField(default=0, verbose_name="Satın alınan kredi")
    used_credits = models.IntegerField(default=0, verbose_name="Kullanılan kredi")
    current_balance = models.IntegerField(default=0, verbose_name="Kalan kredi")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Üye AI Kredi Bakiyesi"
        verbose_name_plural = "Üye AI Kredi Bakiyeleri"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "cycle_start"],
                condition=models.Q(organization__isnull=True),
                name="uniq_user_ai_balance_personal",
            ),
            models.UniqueConstraint(
                fields=["user", "organization"],
                condition=models.Q(organization__isnull=False),
                name="uniq_user_ai_balance_org",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "cycle_start"]),
            models.Index(fields=["organization", "cycle_start"]),
        ]

    def __str__(self):
        target = self.organization.name if self.organization_id else self.user.email
        return f"{target} - {self.current_balance} kredi"


class ProductResearchPackage(models.Model):
    """Ek urun arastirma hakki satis paketi."""
    name = models.CharField(max_length=80, unique=True)
    display_name = models.CharField(max_length=120)
    units = models.PositiveIntegerField(default=0, verbose_name="Araştırma hakkı")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    price_with_kdv = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ürün Araştırma Paketi"
        verbose_name_plural = "Ürün Araştırma Paketleri"
        ordering = ["order", "price"]

    def __str__(self):
        return self.display_name


class ProductResearchLedger(models.Model):
    """Urun arastirma hakki hareket defteri."""
    ACTION_PURCHASE = "purchase"
    ACTION_CONSUME = "consume"
    ACTION_REFUND = "refund"
    ACTION_ADJUSTMENT = "adjustment"
    ACTION_CHOICES = [
        (ACTION_PURCHASE, "Satın alma"),
        (ACTION_CONSUME, "Kullanım"),
        (ACTION_REFUND, "İade"),
        (ACTION_ADJUSTMENT, "Manuel düzeltme"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="product_research_ledger")
    organization = models.ForeignKey("Organization", on_delete=models.SET_NULL, null=True, blank=True, related_name="product_research_ledger")
    package = models.ForeignKey(ProductResearchPackage, on_delete=models.SET_NULL, null=True, blank=True)
    cycle_start = models.DateField(db_index=True, null=True, blank=True)
    cycle_end = models.DateField(db_index=True, null=True, blank=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    amount = models.IntegerField(help_text="Pozitif hak ekler, negatif hak düşer.")
    balance_after = models.IntegerField(default=0)
    reference = models.CharField(max_length=120, blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ürün Araştırma Hareketi"
        verbose_name_plural = "Ürün Araştırma Hareketleri"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "cycle_start", "-created_at"]),
            models.Index(fields=["organization", "cycle_start", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.user} {self.amount:+d} araştırma ({self.action})"


class UserProductResearchBalance(models.Model):
    """Kullanici/ajans bazli ek urun arastirma bakiyesi."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="product_research_balances")
    organization = models.ForeignKey("Organization", on_delete=models.CASCADE, null=True, blank=True, related_name="product_research_balances")
    cycle_start = models.DateField(db_index=True)
    cycle_end = models.DateField(db_index=True)
    purchased_units = models.IntegerField(default=0, verbose_name="Satın alınan hak")
    used_units = models.IntegerField(default=0, verbose_name="Kullanılan hak")
    current_balance = models.IntegerField(default=0, verbose_name="Kalan hak")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Üye Ürün Araştırma Bakiyesi"
        verbose_name_plural = "Üye Ürün Araştırma Bakiyeleri"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "cycle_start"],
                condition=models.Q(organization__isnull=True),
                name="uniq_user_product_research_month",
            ),
            models.UniqueConstraint(
                fields=["user", "organization", "cycle_start"],
                condition=models.Q(organization__isnull=False),
                name="uniq_user_org_product_research_month",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "cycle_start"]),
            models.Index(fields=["organization", "cycle_start"]),
        ]

    def __str__(self):
        target = self.organization.name if self.organization_id else self.user.email
        return f"{target} - {self.current_balance} araştırma hakkı"


class SaaSAICreditPool(models.Model):
    """SaaS uygulamasının sağlayıcıdan aldığı aylık AI kontör havuzu."""

    month = models.DateField(
        unique=True,
        db_index=True,
        help_text="Ayın ilk günü seçilir. Örn: 2026-06-01",
        verbose_name="Dönem",
    )
    purchased_credits = models.PositiveIntegerField(default=1_000_000, verbose_name="Aylık alınan kontör")
    used_credits = models.PositiveIntegerField(default=0, verbose_name="Kullanılan kontör")
    provider_name = models.CharField(max_length=120, blank=True, default="", verbose_name="Sağlayıcı")
    note = models.TextField(blank=True, default="", verbose_name="Not")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "SaaS AI Kontör Havuzu"
        verbose_name_plural = "SaaS AI Kontör Havuzları"
        ordering = ["-month"]

    def __str__(self):
        return f"{self.month:%Y-%m} - {self.remaining_credits:,} kalan"

    @property
    def remaining_credits(self):
        return max(0, int(self.purchased_credits or 0) - int(self.used_credits or 0))

    @property
    def usage_percent(self):
        if not self.purchased_credits:
            return 0
        return round((self.used_credits / self.purchased_credits) * 100, 2)


class OpenAITokenUsageLedger(models.Model):
    """OpenAI ham token tuketimi; uye kontor bakiyesinden tamamen bagimsizdir."""

    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="openai_token_usage"
    )
    organization = models.ForeignKey(
        "Organization", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="openai_token_usage",
    )
    model_name = models.CharField(max_length=120, blank=True, default="")
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    reference = models.CharField(max_length=120, blank=True, default="")
    operation_key = models.CharField(max_length=120, blank=True, default="", db_index=True)
    request_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    usage_kind = models.CharField(max_length=40, blank=True, default="customer_usage", db_index=True)
    note = models.TextField(blank=True, default="")
    used_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "OpenAI Token Kullanimi"
        verbose_name_plural = "OpenAI Token Kullanimlari"
        ordering = ["-used_at", "-id"]
        indexes = [
            models.Index(fields=["user", "used_at"]),
            models.Index(fields=["organization", "used_at"]),
            models.Index(fields=["reference", "used_at"]),
        ]

    def __str__(self):
        target = self.user.email if self.user_id else "Sistem"
        return f"{target} - {self.total_tokens} token"


class TavilyAPIPool(models.Model):
    """SaaS uygulamasinin Tavily hesabindan aldigi aylik arama havuzu."""

    month = models.DateField(
        unique=True,
        db_index=True,
        help_text="Ayin ilk gunu secilir. Ornek: 2026-07-01",
        verbose_name="Donem",
    )
    monthly_limit = models.PositiveIntegerField(default=1000, verbose_name="Aylik Tavily hakki")
    used_requests = models.PositiveIntegerField(default=0, verbose_name="Kullanilan istek")
    rate_limit = models.CharField(max_length=20, default="100/m", verbose_name="Rate limit")
    provider_name = models.CharField(max_length=120, blank=True, default="Tavily", verbose_name="Saglayici")
    note = models.TextField(blank=True, default="", verbose_name="Not")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tavily API Havuzu"
        verbose_name_plural = "Tavily API Havuzlari"
        ordering = ["-month"]

    def __str__(self):
        return f"{self.month:%Y-%m} - {self.remaining_requests:,} kalan"

    @property
    def remaining_requests(self):
        return max(0, int(self.monthly_limit or 0) - int(self.used_requests or 0))

    @property
    def usage_percent(self):
        if not self.monthly_limit:
            return 0
        return round((self.used_requests / self.monthly_limit) * 100, 2)


class TavilyAPIUsageLedger(models.Model):
    """Tavily API cagri gecmisi ve aylik havuz hareketleri."""

    STATUS_ALLOWED = "allowed"
    STATUS_BLOCKED = "blocked"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_ALLOWED, "Kullanildi"),
        (STATUS_BLOCKED, "Engellendi"),
        (STATUS_FAILED, "Basarisiz"),
    ]

    pool = models.ForeignKey(TavilyAPIPool, on_delete=models.CASCADE, related_name="usage_ledger")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ALLOWED)
    amount = models.IntegerField(default=-1, help_text="Negatif deger kullanim dusumudur.")
    balance_after = models.IntegerField(default=0, verbose_name="Kalan hak")
    query = models.TextField(blank=True, default="", verbose_name="Sorgu")
    reference = models.CharField(max_length=160, blank=True, default="")
    response_status = models.PositiveIntegerField(null=True, blank=True, verbose_name="HTTP durum")
    error_message = models.TextField(blank=True, default="", verbose_name="Hata")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tavily API Hareketi"
        verbose_name_plural = "Tavily API Hareketleri"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["pool", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.pool.month:%Y-%m} {self.amount:+d} Tavily ({self.status})"


class FeatureUsageLedger(models.Model):
    OP_OPENAI_ANALYSIS = "openai_analysis"
    OP_OPENAI_RECOMMENDATION = "openai_recommendation"
    OP_MARKETPLACE_PRODUCT_RESEARCH = "marketplace_product_research"
    OP_MARKETPLACE_PRICE_CHECK = "marketplace_price_check"

    OPERATION_CHOICES = [
        (OP_OPENAI_ANALYSIS, "OpenAI analiz"),
        (OP_OPENAI_RECOMMENDATION, "OpenAI öneri/yorum"),
        (OP_MARKETPLACE_PRODUCT_RESEARCH, "Ürün araştırma API"),
        (OP_MARKETPLACE_PRICE_CHECK, "Fiyat inceleme API"),
    ]

    STATUS_ALLOWED = "allowed"
    STATUS_BLOCKED = "blocked"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_ALLOWED, "Kullanıldı"),
        (STATUS_BLOCKED, "Limit nedeniyle engellendi"),
        (STATUS_FAILED, "Hata aldı"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="feature_usage_ledgers")
    organization = models.ForeignKey("Organization", on_delete=models.SET_NULL, null=True, blank=True, related_name="feature_usage_ledgers")
    subscription = models.ForeignKey(UserSubscription, on_delete=models.SET_NULL, null=True, blank=True, related_name="feature_usage_ledgers")
    operation = models.CharField(max_length=50, choices=OPERATION_CHOICES, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ALLOWED, db_index=True)
    units = models.PositiveIntegerField(default=1)
    provider_units = models.PositiveIntegerField(default=0, help_text="Token, sonuç veya harici API birimi")
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0.0000"))
    reference = models.CharField(max_length=160, blank=True, default="", db_index=True)
    note = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Özellik Kullanım Kaydı"
        verbose_name_plural = "Özellik Kullanım Kayıtları"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "operation", "created_at"], name="core_featur_user_id_76a83b_idx"),
            models.Index(fields=["organization", "operation", "created_at"], name="core_featur_organiz_307d72_idx"),
            models.Index(fields=["operation", "status", "created_at"], name="core_featur_operati_028f86_idx"),
        ]

    def __str__(self):
        return f"{self.user} - {self.get_operation_display()} - {self.units}"


class Organization(models.Model):
    """Ajans/ekip çalışma alanı."""
    name = models.CharField(max_length=180, verbose_name="Organizasyon Adı")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_organizations")
    active_plan = models.ForeignKey(MembershipPlan, on_delete=models.SET_NULL, null=True, blank=True)
    logo = models.FileField(upload_to="agency/logos/", null=True, blank=True, verbose_name="Ajans Logosu")
    additional_seats = models.PositiveIntegerField(
        default=0,
        verbose_name="Ek alt kullanıcı koltuğu",
        help_text="Paketin dahil koltuk sayısına bu kadar ek kontenjan eklenir.",
    )
    report_brand_name = models.CharField(max_length=180, blank=True, default="", verbose_name="Rapor Marka Adı")
    report_footer_note = models.CharField(max_length=240, blank=True, default="", verbose_name="Rapor Alt Notu")
    use_logo_on_reports = models.BooleanField(default=True, verbose_name="PDF raporlarında logo kullan")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Organizasyon"
        verbose_name_plural = "Organizasyonlar"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def seat_limit(self):
        base_limit = self.active_plan.included_seats if self.active_plan and self.active_plan.included_seats else 1
        if base_limit >= 9999:
            return base_limit
        return base_limit + int(self.additional_seats or 0)

    def active_member_count(self):
        return 1 + self.members.exclude(user_id=self.owner_id).filter(is_active=True).count()

    def has_available_seat(self):
        limit = self.seat_limit
        return limit >= 9999 or self.active_member_count() < limit

    @property
    def client_limit(self):
        if self.active_plan and self.active_plan.max_client_accounts:
            return self.active_plan.max_client_accounts
        return 0

    def active_client_count(self):
        return self.clients.filter(is_active=True).count()

    def has_available_client_slot(self):
        limit = self.client_limit
        return limit >= 9999 or self.active_client_count() < limit


class AgencyRoleGroup(models.Model):
    """Reusable permission group for agency sub-users."""

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="role_groups",
    )
    name = models.CharField(max_length=100, verbose_name="Yetki grubu adı")
    description = models.CharField(max_length=240, blank=True, default="", verbose_name="Açıklama")
    system_key = models.CharField(max_length=30, blank=True, default="", editable=False)
    can_manage_clients = models.BooleanField(default=False, verbose_name="Müşteri yönetebilir")
    can_manage_accounts = models.BooleanField(default=False, verbose_name="Hesap bağlayabilir")
    can_manage_competitors = models.BooleanField(default=False, verbose_name="Rakip yönetebilir")
    can_view_reports = models.BooleanField(default=True, verbose_name="Rapor görebilir")
    can_manage_members = models.BooleanField(default=False, verbose_name="Kullanıcı/yetki yönetebilir")
    can_manage_billing = models.BooleanField(default=False, verbose_name="Paket/fatura yönetebilir")
    menu_permissions = models.JSONField(default=list, blank=True, verbose_name="Menü / modül yetkileri")
    is_active = models.BooleanField(default=True, verbose_name="Aktif")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ajans Yetki Grubu"
        verbose_name_plural = "Ajans Yetki Grupları"
        ordering = ["organization__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_agency_role_group_name",
            ),
        ]

    def __str__(self):
        return f"{self.organization} - {self.name}"

    def permission_map(self):
        flags = {
            "manage_clients": self.can_manage_clients,
            "manage_accounts": self.can_manage_accounts,
            "manage_competitors": self.can_manage_competitors,
            "view_reports": self.can_view_reports,
            "manage_members": self.can_manage_members,
            "manage_billing": self.can_manage_billing,
        }
        return {key for key, enabled in flags.items() if enabled}


class OrganizationMember(models.Model):
    """Organizasyon içi rol ve üyelik."""
    ROLE_OWNER = "owner"
    ROLE_ADMIN = "admin"
    ROLE_EDITOR = "editor"
    ROLE_VIEWER = "viewer"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_ADMIN, "Admin"),
        (ROLE_EDITOR, "Editor"),
        (ROLE_VIEWER, "Viewer"),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="organization_memberships")
    role_group = models.ForeignKey(
        AgencyRoleGroup,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="members",
        verbose_name="Yetki grubu",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_VIEWER)
    can_manage_clients = models.BooleanField(default=False, verbose_name="Müşteri yönetebilir")
    can_manage_accounts = models.BooleanField(default=False, verbose_name="Hesap bağlayabilir")
    can_manage_competitors = models.BooleanField(default=False, verbose_name="Rakip yönetebilir")
    can_view_reports = models.BooleanField(default=True, verbose_name="Rapor görebilir")
    can_manage_members = models.BooleanField(default=False, verbose_name="Kullanıcı/yetki yönetebilir")
    can_manage_billing = models.BooleanField(default=False, verbose_name="Paket/fatura yönetebilir")
    menu_permissions = models.JSONField(default=list, blank=True, verbose_name="Menü / modül yetkileri")
    is_managed_subaccount = models.BooleanField(
        default=False,
        editable=False,
        verbose_name="Ajans tarafından oluşturulan alt hesap",
    )
    is_active = models.BooleanField(default=True)
    invited_email = models.EmailField(blank=True, default="")
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Organizasyon Üyesi"
        verbose_name_plural = "Organizasyon Üyeleri"
        unique_together = ("organization", "user")
        ordering = ["organization__name", "role", "user__email"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=~models.Q(role="owner"),
                name="unique_agency_membership_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.organization} - {self.user} ({self.role})"

    def permission_map(self):
        if self.role_group_id:
            if not self.role_group.is_active:
                return set()
            return self.role_group.permission_map()

        role_permissions = {
            self.ROLE_OWNER: {
                "manage_clients",
                "manage_accounts",
                "manage_competitors",
                "view_reports",
                "manage_members",
                "manage_billing",
            },
            self.ROLE_ADMIN: {
                "manage_clients",
                "manage_accounts",
                "manage_competitors",
                "view_reports",
                "manage_members",
            },
            self.ROLE_EDITOR: {
                "manage_clients",
                "manage_accounts",
                "manage_competitors",
                "view_reports",
            },
            self.ROLE_VIEWER: {"view_reports"},
        }
        allowed = set(role_permissions.get(self.role, set()))
        custom_flags = {
            "manage_clients": self.can_manage_clients,
            "manage_accounts": self.can_manage_accounts,
            "manage_competitors": self.can_manage_competitors,
            "view_reports": self.can_view_reports,
            "manage_members": self.can_manage_members,
            "manage_billing": self.can_manage_billing,
        }
        allowed.update(key for key, value in custom_flags.items() if value)
        return allowed

    def has_permission(self, permission):
        if not self.is_active:
            return False
        return permission in self.permission_map()

    def has_menu_permission(self, permission_key):
        if not self.is_active:
            return False
        if self.role == self.ROLE_OWNER:
            return True
        if self.role_group_id:
            if not self.role_group.is_active:
                return False
            return permission_key in set(self.role_group.menu_permissions or [])
        return permission_key in set(self.menu_permissions or [])


class AgencyClient(models.Model):
    """Ajansın yönettiği müşteri/marka çalışma alanı."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="clients")
    name = models.CharField(max_length=180, verbose_name="Müşteri / Marka Adı")
    legal_name = models.CharField(max_length=220, blank=True, default="", verbose_name="Resmi Unvan")
    website = models.URLField(blank=True, default="", verbose_name="Web Sitesi")
    contact_name = models.CharField(max_length=160, blank=True, default="", verbose_name="Yetkili Kişi")
    contact_email = models.EmailField(blank=True, default="", verbose_name="Yetkili E-posta")
    logo = models.FileField(upload_to="agency/client-logos/", null=True, blank=True, verbose_name="Müşteri Logosu")
    notes = models.TextField(blank=True, default="", verbose_name="Notlar")
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ajans Müşterisi"
        verbose_name_plural = "Ajans Müşterileri"
        ordering = ["organization__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="uniq_agency_client_org_name")
        ]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return f"{self.organization} - {self.name}"

class BillingInfo(models.Model):
    """Fatura bilgileri"""
    CUSTOMER_TYPE_CHOICES = [
        ('individual', 'Bireysel'),
        ('company', 'Şirket'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='billing_infos')
    customer_type = models.CharField(max_length=20, choices=CUSTOMER_TYPE_CHOICES, default='individual')
    first_name = models.CharField(max_length=100, verbose_name="Ad")
    last_name = models.CharField(max_length=100, verbose_name="Soyad")
    email = models.EmailField(verbose_name="E-posta")
    phone = models.CharField(max_length=20, verbose_name="Telefon")
    company_name = models.CharField(max_length=200, blank=True, null=True, default='', verbose_name="Şirket Adı")
    tax_office = models.CharField(max_length=100, blank=True, null=True, default='', verbose_name="Vergi Dairesi")
    tax_number = models.CharField(max_length=50, blank=True, null=True, default='', verbose_name="Vergi No")
    tc_kimlik = models.CharField(max_length=11, blank=True, null=True, default='', verbose_name="TC Kimlik No")
    address = models.TextField(verbose_name="Adres")
    city = models.CharField(max_length=100, verbose_name="İl")
    district = models.CharField(max_length=100, blank=True, null=True, default='', verbose_name="İlçe")
    zip_code = models.CharField(max_length=10, blank=True, null=True, default='', verbose_name="Posta Kodu")
    identity_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Fatura Bilgisi'
        verbose_name_plural = 'Fatura Bilgileri'
        constraints = [
            models.UniqueConstraint(fields=["user", "identity_hash"], name="uniq_billing_info_user_identity"),
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @staticmethod
    def normalize_identity_value(value, lower=False):
        value = str(value or "").strip()
        value = " ".join(value.split())
        return value.lower() if lower else value

    @classmethod
    def build_identity_hash(cls, values):
        parts = [
            cls.normalize_identity_value(values.get("customer_type")) or "individual",
            cls.normalize_identity_value(values.get("first_name")),
            cls.normalize_identity_value(values.get("last_name")),
            cls.normalize_identity_value(values.get("email"), lower=True),
            cls.normalize_identity_value(values.get("phone")),
            cls.normalize_identity_value(values.get("company_name")),
            cls.normalize_identity_value(values.get("tax_office")),
            cls.normalize_identity_value(values.get("tax_number")),
            cls.normalize_identity_value(values.get("tc_kimlik")),
            cls.normalize_identity_value(values.get("address")),
            cls.normalize_identity_value(values.get("city")),
            cls.normalize_identity_value(values.get("district")),
            cls.normalize_identity_value(values.get("zip_code")),
        ]
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()

    def save(self, *args, **kwargs):
        self.identity_hash = self.build_identity_hash({
            "customer_type": self.customer_type,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "phone": self.phone,
            "company_name": self.company_name,
            "tax_office": self.tax_office,
            "tax_number": self.tax_number,
            "tc_kimlik": self.tc_kimlik,
            "address": self.address,
            "city": self.city,
            "district": self.district,
            "zip_code": self.zip_code,
        })
        super().save(*args, **kwargs)


class Invoice(models.Model):
    """Fatura modeli"""
    STATUS_CHOICES = [
        ('draft', 'Taslak'),
        ('paid', 'Ödendi'),
        ('cancelled', 'İptal'),
        ('refunded', 'İade Edildi'),
    ]
    PAYMENT_METHOD_CHOICES = [
        ('credit_card', 'Kredi Kartı'),
        ('bank_transfer', 'Havale/EFT'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='invoices')
    subscription = models.ForeignKey(UserSubscription, on_delete=models.SET_NULL, null=True, blank=True)
    billing_info = models.ForeignKey(BillingInfo, on_delete=models.SET_NULL, null=True, blank=True)
    invoice_number = models.CharField(max_length=50, unique=True, verbose_name="Fatura No")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="KDV Hariç Tutar")
    kdv_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="KDV Tutarı")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Toplam Tutar")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='credit_card', verbose_name="Ödeme Yöntemi")
    is_paid = models.BooleanField(default=False, verbose_name="Ödendi mi?")
    payment_date = models.DateTimeField(null=True, blank=True, verbose_name="Ödeme Tarihi")
    due_date = models.DateField(blank=True, null=True, verbose_name='Son Ödeme Tarihi')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft', verbose_name="Durum")
    description = models.TextField(blank=True, null=True, verbose_name='Açıklama')
    notes = models.TextField(blank=True, null=True, verbose_name="Notlar")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Fatura'
        verbose_name_plural = 'Faturalar'
        ordering = ['-created_at']

    def __str__(self):
        return f"Fatura #{self.invoice_number} - {self.user.email}"

    def mark_as_paid(self):
        self.is_paid = True
        self.payment_date = timezone.now()
        self.status = 'paid'
        self.save()



class Payment(models.Model):
    """Ödeme kaydı"""
    PAYMENT_METHOD_CHOICES = [
        ('credit_card', 'Kredi Kartı'),
        ('bank_transfer', 'Havale/EFT'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Beklemede'),
        ('completed', 'Tamamlandı'),
        ('failed', 'Başarısız'),
        ('refunded', 'İade Edildi'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments')
    plan = models.ForeignKey(MembershipPlan, on_delete=models.SET_NULL, null=True)
    ai_credit_package = models.ForeignKey(
        AICreditPackage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    product_research_package = models.ForeignKey(
        ProductResearchPackage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    billing_info = models.ForeignKey(BillingInfo, on_delete=models.SET_NULL, null=True, blank=True)
    billing_period = models.CharField(max_length=20, choices=UserSubscription.BILLING_PERIOD_CHOICES, default=UserSubscription.BILLING_MONTHLY, verbose_name="Faturalama dönemi")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Tutar")
    kdv_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="KDV")
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, verbose_name="Ödeme Yöntemi")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="Durum")
    transaction_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="İşlem ID")
    notes = models.TextField(blank=True, null=True, verbose_name="Notlar")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Ödeme'
        verbose_name_plural = 'Ödemeler'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} - {self.amount} TL - {self.get_status_display()}"

    @property
    def purchase_label(self):
        product = self.plan or self.ai_credit_package or self.product_research_package
        return getattr(product, "display_name", "Ödeme")

class PaymentTransaction(models.Model):
    """Ödeme işlemi detayı"""
    TRANSACTION_TYPE_CHOICES = [
        ('payment', 'Ödeme'),
        ('refund', 'İade'),
        ('chargeback', 'Ters İbraz'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Beklemede'),
        ('success', 'Başarılı'),
        ('failed', 'Başarısız'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_transactions')
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='transactions', null=True, blank=True)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES, default='payment', verbose_name="İşlem Tipi")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Tutar")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="Durum")
    reference_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="Referans ID")
    response_data = models.JSONField(null=True, blank=True, verbose_name="Yanıt Verisi")
    notes = models.TextField(blank=True, null=True, verbose_name="Notlar")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Ödeme İşlemi'
        verbose_name_plural = 'Ödeme İşlemleri'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} - {self.amount} TL - {self.get_transaction_type_display()}"
