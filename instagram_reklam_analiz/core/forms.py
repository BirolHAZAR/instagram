# core/forms.py
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.models import AgencyClient, Campaign, ScheduledReport
from core.models.marketplace import SUPPORTED_MARKETPLACE_CODES


class ScheduledReportForm(forms.ModelForm):
    recipient_emails_input = forms.CharField(
        label="Alıcı e-postaları",
        help_text="Birden fazla alıcı için virgül kullanın veya her e-postayı yeni satıra yazın.",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "ornek@firma.com, ekip@firma.com"}),
    )
    campaigns = forms.ModelMultipleChoiceField(
        label="Kampanya filtresi",
        queryset=Campaign.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": 6}),
        help_text="Boş bırakırsanız tüm kampanyalar rapora dahil edilir.",
    )

    class Meta:
        model = ScheduledReport
        fields = [
            "name",
            "frequency",
            "recipient_emails_input",
            "campaigns",
            "send_hour",
            "include_campaign_summary",
            "include_ad_performance",
            "include_rule_recommendations",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Haftalık performans özeti"}),
            "frequency": forms.Select(attrs={"class": "form-select"}),
            "send_hour": forms.NumberInput(attrs={"class": "form-control", "min": 0, "max": 23}),
            "include_campaign_summary": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "include_ad_performance": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "include_rule_recommendations": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "name": "Rapor adı",
            "frequency": "Gönderim periyodu",
            "send_hour": "Gönderim saati",
            "include_campaign_summary": "Kampanya özeti",
            "include_ad_performance": "Reklam performansı",
            "include_rule_recommendations": "Kural bazlı öneriler",
            "is_active": "Aktif",
        }

    def __init__(self, *args, user=None, campaigns_queryset=None, agency_clients=None, **kwargs):
        super().__init__(*args, **kwargs)
        if agency_clients is not None:
            self.fields["agency_client"] = forms.ModelChoiceField(
                label="Ajans müşterisi",
                queryset=agency_clients,
                required=True,
                empty_label="Müşteri seçin",
                widget=forms.Select(attrs={"class": "form-select"}),
                help_text="Rapor yalnızca seçilen müşterinin reklam verileriyle hazırlanır.",
            )
            if self.instance and self.instance.pk:
                self.fields["agency_client"].initial = self.instance.agency_client_id
        self.fields["campaigns"].queryset = (
            campaigns_queryset.order_by("name")
            if campaigns_queryset is not None
            else Campaign.objects.filter(user=user).order_by("name") if user else Campaign.objects.none()
        )
        if self.instance and self.instance.pk:
            self.fields["recipient_emails_input"].initial = "\n".join(self.instance.recipient_emails or [])

    def clean_recipient_emails_input(self):
        raw = self.cleaned_data.get("recipient_emails_input", "")
        emails = []
        seen = set()
        for item in raw.replace(";", ",").replace("\n", ",").split(","):
            email = item.strip()
            if not email:
                continue
            try:
                validate_email(email)
            except ValidationError as exc:
                raise forms.ValidationError(f"Geçersiz e-posta: {email}") from exc
            email_key = email.casefold()
            if email_key not in seen:
                seen.add(email_key)
                emails.append(email)
        return emails

    def clean(self):
        cleaned = super().clean()
        agency_client = cleaned.get("agency_client")
        campaigns = cleaned.get("campaigns")
        emails = cleaned.get("recipient_emails_input") or []
        if not emails and agency_client and agency_client.contact_email:
            cleaned["recipient_emails_input"] = [agency_client.contact_email]
        elif not emails:
            self.add_error("recipient_emails_input", "En az bir alıcı e-posta yazın veya e-postası kayıtlı bir ajans müşterisi seçin.")
        if agency_client and campaigns and campaigns.exclude(platform_account__agency_client=agency_client).exists():
            self.add_error("campaigns", "Yalnızca seçilen müşteriye ait kampanyaları seçebilirsiniz.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if "agency_client" in self.fields:
            instance.agency_client = self.cleaned_data.get("agency_client")
        instance.recipient_emails = self.cleaned_data["recipient_emails_input"]
        if commit:
            instance.save()
            self.save_m2m()
        return instance
from .models import (
    AgencyClient,
    AgencyRoleGroup,
    BillingInfo,
    Competitor,
    MarketplaceAccount,
    MarketplaceProductResearch,
    Organization,
    OrganizationMember,
    PlatformAccount,
    Product,
)
from django.core.validators import RegexValidator
from core.services.agency_permission_matrix import AGENCY_MENU_PERMISSION_CHOICES, AGENCY_MENU_PERMISSION_GROUPS


class OrganizationBrandingForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ["logo", "report_brand_name", "report_footer_note", "use_logo_on_reports"]
        widgets = {
            "report_brand_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Raporlarda görünecek marka adı"}),
            "report_footer_note": forms.TextInput(attrs={"class": "form-control", "placeholder": "Örn: Bu rapor Ajans adı tarafından hazırlanmıştır."}),
            "use_logo_on_reports": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class AgencyClientForm(forms.ModelForm):
    class Meta:
        model = AgencyClient
        fields = ["name", "legal_name", "website", "contact_name", "contact_email", "logo", "notes", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Marka / müşteri adı"}),
            "legal_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Resmi unvan"}),
            "website": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://"}),
            "contact_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Müşteri yetkilisi"}),
            "contact_email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "yetkili@firma.com"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class AgencyPlatformAccountForm(forms.ModelForm):
    class Meta:
        model = PlatformAccount
        fields = ["agency_client", "platform", "account_name", "account_id", "access_token", "is_active"]
        widgets = {
            "agency_client": forms.Select(attrs={"class": "form-select"}),
            "platform": forms.Select(attrs={"class": "form-select"}),
            "account_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Hesap adı"}),
            "account_id": forms.TextInput(attrs={"class": "form-control", "placeholder": "Platform hesap ID"}),
            "access_token": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Erişim tokenı"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["agency_client"].label = "Bu hesap hangi müşteriye bağlı?"
        self.fields["agency_client"].required = True
        if organization is not None:
            self.fields["agency_client"].queryset = organization.clients.filter(is_active=True).order_by("name")


class AgencyAccountAssignmentForm(forms.Form):
    platform_account = forms.ModelChoiceField(
        label="Mevcut hesap",
        queryset=PlatformAccount.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, organization=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = PlatformAccount.objects.none()
        if organization is not None:
            qs = PlatformAccount.objects.filter(
                user=user or organization.owner,
                agency_client__isnull=True,
            ).select_related("platform").order_by("platform__name", "account_name")
        self.fields["platform_account"].queryset = qs


class MarketplaceAccountForm(forms.ModelForm):
    class Meta:
        model = MarketplaceAccount
        fields = [
            "marketplace",
            "agency_client",
            "store_name",
            "seller_id",
            "api_key_encrypted",
            "api_secret_encrypted",
            "sync_mode",
            "sync_product_limit",
            "include_products_without_price",
            "price_stock_sync_interval_minutes",
            "catalog_sync_interval_minutes",
            "is_active",
        ]
        labels = {
            "marketplace": "Pazaryeri",
            "agency_client": "Ajans müşterisi",
            "store_name": "Mağaza adı",
            "seller_id": "Satıcı / Mağaza ID",
            "api_key_encrypted": "API Key",
            "api_secret_encrypted": "API Secret",
            "sync_mode": "Çekilecek ürün koşulu",
            "sync_product_limit": "İlk çekim ürün limiti",
            "include_products_without_price": "Fiyatı olmayan ürünleri de al",
            "price_stock_sync_interval_minutes": "Fiyat/stok kontrol aralığı",
            "catalog_sync_interval_minutes": "Ürün bilgisi kontrol aralığı",
            "is_active": "Aktif",
        }
        widgets = {
            "marketplace": forms.Select(attrs={"class": "form-select"}),
            "agency_client": forms.Select(attrs={"class": "form-select"}),
            "store_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Örn: Marka Trendyol Mağazası"}),
            "seller_id": forms.TextInput(attrs={"class": "form-control", "placeholder": "Supplier ID / Merchant ID / Seller ID"}),
            "api_key_encrypted": forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password", "placeholder": "API anahtarı"}),
            "api_secret_encrypted": forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password", "placeholder": "API secret / şifre"}),
            "sync_mode": forms.Select(attrs={"class": "form-select"}),
            "sync_product_limit": forms.NumberInput(attrs={"class": "form-control", "min": 50, "max": 5000, "step": 50}),
            "include_products_without_price": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "price_stock_sync_interval_minutes": forms.NumberInput(attrs={"class": "form-control", "min": 60, "step": 30}),
            "catalog_sync_interval_minutes": forms.NumberInput(attrs={"class": "form-control", "min": 360, "step": 60}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        help_texts = {
            "sync_product_limit": "Sistemi yormamak için 250 önerilir. Paket büyüdükçe artırılabilir.",
            "price_stock_sync_interval_minutes": "Öneri: 240 dakika. Fiyat ve stok ürün bilgisinden ayrı kontrol edilir.",
            "catalog_sync_interval_minutes": "Öneri: 1440 dakika. Ürün adı, kategori ve varyant genelde günde 1 kez yeterlidir.",
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["marketplace"].queryset = self.fields["marketplace"].queryset.filter(
            code__in=SUPPORTED_MARKETPLACE_CODES,
            is_active=True,
        ).order_by("order", "name")
        self.fields["agency_client"].required = False
        self.fields["agency_client"].empty_label = "Bireysel hesap / müşteri seçme"
        if organization is not None:
            self.fields["agency_client"].queryset = organization.clients.filter(is_active=True).order_by("name")
        else:
            self.fields["agency_client"].queryset = AgencyClient.objects.none()
        if self.instance and self.instance.pk:
            for name in ("api_key_encrypted", "api_secret_encrypted"):
                self.fields[name].required = False
                self.fields[name].widget.attrs["placeholder"] = "Değiştirmek için yeni değer girin"
                self.fields[name].help_text = "Boş bırakırsanız mevcut şifreli değer korunur."

    def clean_api_key_encrypted(self):
        value = self.cleaned_data.get("api_key_encrypted")
        if not value and self.instance and self.instance.pk:
            return self.instance.api_key_encrypted
        return value

    def clean_api_secret_encrypted(self):
        value = self.cleaned_data.get("api_secret_encrypted")
        if not value and self.instance and self.instance.pk:
            return self.instance.api_secret_encrypted
        return value

    def clean_sync_product_limit(self):
        value = self.cleaned_data["sync_product_limit"]
        return min(max(value, 50), 5000)


class MarketplaceProductResearchForm(forms.ModelForm):
    class Meta:
        model = MarketplaceProductResearch
        fields = ["title", "product_image", "prompt"]
        labels = {
            "title": "Ürün adı",
            "product_image": "Ürün görseli",
            "prompt": "Ürün özellikleri (isteğe bağlı)",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "mpr-input", "placeholder": "Örn: Nike Air Max 270"}),
            "product_image": forms.ClearableFileInput(attrs={"class": "mpr-file", "accept": "image/*"}),
            "prompt": forms.Textarea(attrs={
                "class": "mpr-textarea",
                "rows": 7,
                "placeholder": "Örn: kırmızı, erkek, 42 numara, orijinal, yeni, Türkiye’den gönderim",
            }),
        }
        help_texts = {
            "prompt": "Özellikleri virgülle ayırın. AI her özelliği görselle birlikte ayrı bir arama kriteri olarak değerlendirecek.",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title"].required = False
        self.fields["product_image"].required = False
        self.fields["prompt"].required = False

    def clean(self):
        cleaned_data = super().clean()
        image = cleaned_data.get("product_image")
        prompt = cleaned_data.get("prompt")
        if not image:
            self.add_error("product_image", "Profesyonel araştırma promptu için bir ürün görseli yükleyin.")
        if not any((cleaned_data.get("title"), image, prompt)):
            raise forms.ValidationError(
                "Araştırma için bir görsel yükleyin veya ürün adı/özelliği girin."
            )
        return cleaned_data


class AgencyCompetitorForm(forms.ModelForm):
    class Meta:
        model = Competitor
        fields = ["agency_client", "platform", "platform_account", "platform_identifier", "name", "website", "category", "description", "is_active"]
        widgets = {
            "agency_client": forms.Select(attrs={"class": "form-select"}),
            "platform": forms.Select(attrs={"class": "form-select"}),
            "platform_account": forms.Select(attrs={"class": "form-select"}),
            "platform_identifier": forms.TextInput(attrs={"class": "form-control", "placeholder": "Rakip hesap adı / ID"}),
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Rakip marka adı"}),
            "website": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            clients = organization.clients.filter(is_active=True).order_by("name")
            self.fields["agency_client"].queryset = clients
            self.fields["platform_account"].queryset = PlatformAccount.objects.filter(agency_client__organization=organization).select_related("platform", "agency_client")


class OrganizationMemberInviteForm(forms.Form):
    first_name = forms.CharField(label="Ad", max_length=150, widget=forms.TextInput(attrs={"class": "form-control"}))
    last_name = forms.CharField(label="Soyad", max_length=150, widget=forms.TextInput(attrs={"class": "form-control"}))
    username = forms.CharField(
        label="Kullanıcı adı",
        max_length=150,
        required=True,
        help_text="Alt kullanıcı bu kullanıcı adı ve parolayla giriş yapar.",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        label="E-posta",
        required=True,
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "kullanici@ajans.com"}),
    )
    password1 = forms.CharField(
        label="Parola",
        required=False,
        strip=False,
        help_text="Yeni kullanıcı için zorunludur. Mevcut kullanıcı ekleniyorsa boş bırakın.",
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Parola tekrarı",
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
    )
    role_group = forms.ModelChoiceField(
        label="Yetki grubu",
        queryset=AgencyRoleGroup.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.fields["role_group"].queryset = organization.role_groups.filter(is_active=True).order_by("name")

    def clean(self):
        cleaned = super().clean()
        email = (cleaned.get("email") or "").strip().lower()
        password1 = cleaned.get("password1") or ""
        password2 = cleaned.get("password2") or ""
        username = (cleaned.get("username") or "").strip()
        user = None
        if email:
            user = get_user_model().objects.filter(email__iexact=email).first()
        if user is None and username:
            user = get_user_model().objects.filter(username__iexact=username).first()
        self.existing_user = user
        if not user and not password1:
            self.add_error("password1", "Yeni alt kullanıcı için parola zorunludur.")
        if password1 != password2:
            self.add_error("password2", "Parolalar eşleşmiyor.")
        if password1:
            try:
                validate_password(password1, user=user)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned


class OrganizationMemberRoleForm(forms.ModelForm):
    class Meta:
        model = OrganizationMember
        fields = ["role_group", "is_active"]
        widgets = {
            "role_group": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        if organization is not None:
            self.fields["role_group"].queryset = organization.role_groups.filter(is_active=True).order_by("name")


class AgencyRoleGroupForm(forms.ModelForm):
    menu_permissions = forms.MultipleChoiceField(
        label="Modül/link yetkileri",
        choices=AGENCY_MENU_PERMISSION_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = AgencyRoleGroup
        fields = [
            "name", "description", "can_manage_clients", "can_manage_accounts",
            "can_manage_competitors", "can_view_reports", "can_manage_members",
            "can_manage_billing", "menu_permissions", "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
            "can_manage_clients": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_manage_accounts": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_manage_competitors": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_view_reports": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_manage_members": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_manage_billing": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization
        self.menu_permission_groups = AGENCY_MENU_PERMISSION_GROUPS
        if self.instance and self.instance.pk:
            self.fields["menu_permissions"].initial = self.instance.menu_permissions or []

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.organization:
            duplicate = self.organization.role_groups.filter(name__iexact=name)
            if self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                raise ValidationError("Bu isimde bir yetki grubu zaten var.")
        return name

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.organization is not None:
            instance.organization = self.organization
        instance.menu_permissions = self.cleaned_data.get("menu_permissions", [])
        if commit:
            instance.save()
        return instance


class BillingInfoForm(forms.ModelForm):
    """Fatura bilgileri formu - BillingInfo modelini kullanır"""
    
    class Meta:
        model = BillingInfo  # İNVOICE DEĞİL! BillingInfo olmalı!
        fields = [
            'customer_type',
            'first_name', 
            'last_name', 
            'email', 
            'phone',
            'company_name', 
            'tax_office', 
            'tax_number',
            'tc_kimlik',
            'address', 
            'city', 
            'district', 
            'zip_code',
        ]
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3}),
        }


class PaymentMethodForm(forms.Form):
    """Ödeme yöntemi seçim formu"""
    PAYMENT_CHOICES = [
        ('credit_card', 'Kredi Kartı'),
        ('bank_transfer', 'Havale/EFT'),
    ]
    
    payment_method = forms.ChoiceField(
        choices=PAYMENT_CHOICES,
        widget=forms.RadioSelect(),
        initial='credit_card',
        label='Ödeme Yöntemi'
    )


class CreditCardForm(forms.Form):
    """Kredi kartı bilgileri formu"""
    card_holder = forms.CharField(
        max_length=100, 
        required=False,
        label='Kart Üzerindeki İsim',
        widget=forms.TextInput(attrs={'placeholder': 'AD SOYAD'})
    )
    card_number = forms.CharField(
        max_length=19, 
        required=False,
        label='Kart Numarası',
        widget=forms.TextInput(attrs={'placeholder': '0000 0000 0000 0000'})
    )
    expiry_month = forms.CharField(
        max_length=2, 
        required=False,
        label='Ay',
        widget=forms.TextInput(attrs={'placeholder': 'AA'})
    )
    expiry_year = forms.CharField(
        max_length=2, 
        required=False,
        label='Yıl',
        widget=forms.TextInput(attrs={'placeholder': 'YY'})
    )
    cvv = forms.CharField(
        max_length=4, 
        required=False,
        label='CVV',
        widget=forms.PasswordInput(attrs={'placeholder': '***'})
    )
    
    def clean_card_number(self):
        card_number = self.cleaned_data.get('card_number', '')
        # Boşlukları kaldır
        card_number = card_number.replace(' ', '')
        return card_number


class LegacyCheckoutForm(forms.ModelForm):
    
    # Müşteri tipi seçimi
    CUSTOMER_TYPE_CHOICES = [
        ('individual', 'Bireysel'),
        ('corporate', 'Kurumsal'),
        ('company', 'Şirket'),
    ]
    customer_type = forms.ChoiceField(
        choices=CUSTOMER_TYPE_CHOICES,
        widget=forms.RadioSelect,
        initial='individual',
        label='Müşteri Tipi'
    )
    
    # TC Kimlik No: 11 haneli, sadece rakam (algoritma kontrolü YOK)
    tc_kimlik = forms.CharField(
        max_length=11,
        min_length=11,
        required=False,
        validators=[RegexValidator(r'^\d{11}$', 'TC Kimlik No 11 haneli rakam olmalıdır.')],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '11111111111',
            'maxlength': '11',
            'inputmode': 'numeric',
            'pattern': '[0-9]{11}',
        }),
        label='TC Kimlik No'
    )
    
    # Vergi No: 10 haneli, sadece rakam
    tax_number = forms.CharField(
        max_length=10,
        min_length=10,
        required=False,
        validators=[RegexValidator(r'^\d{10}$', 'Vergi No 10 haneli rakam olmalıdır.')],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '1234567890',
            'maxlength': '10',
            'inputmode': 'numeric',
            'pattern': '[0-9]{10}',
        }),
        label='Vergi No'
    )
    
    # Vergi Dairesi
    tax_office = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Örn: Büyük Mükellefler VD',
        }),
        label='Vergi Dairesi'
    )
    
    # Ödeme yöntemi - GİZLİ, otomatik atanacak
    payment_method = forms.CharField(
        required=False,
        initial='credit_card',
        widget=forms.HiddenInput()
    )
    
    class Meta:
        model = BillingInfo
        fields = [
            'customer_type', 'first_name', 'last_name', 'email', 'phone',
            'company_name', 'tax_office', 'tax_number', 'tc_kimlik',
            'address', 'city', 'district', 'zip_code'
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Adınız',
                'required': 'required'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Soyadınız',
                'required': 'required'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control', 
                'placeholder': 'ornek@email.com',
                'required': 'required'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': '5XXXXXXXXX',
                'required': 'required'
            }),
            'company_name': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Şirket Adı'
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 3, 
                'placeholder': 'Açık adresiniz',
                'required': 'required'
            }),
            'city': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'İl',
                'required': 'required'
            }),
            'district': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'İlçe'
            }),
            'zip_code': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Posta Kodu'
            }),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        customer_type = cleaned_data.get('customer_type')
        tc_kimlik = cleaned_data.get('tc_kimlik', '')
        tax_number = cleaned_data.get('tax_number', '')
        tax_office = cleaned_data.get('tax_office', '')
        
        # Bireysel müşteri için TC Kimlik zorunlu
        if customer_type == 'individual':
            if not tc_kimlik:
                self.add_error('tc_kimlik', 'Bireysel müşteriler için TC Kimlik No zorunludur.')
            elif len(tc_kimlik) != 11:
                self.add_error('tc_kimlik', 'TC Kimlik No tam olarak 11 hane olmalıdır.')
            elif not tc_kimlik.isdigit():
                self.add_error('tc_kimlik', 'TC Kimlik No sadece rakamlardan oluşmalıdır.')
        
        # Kurumsal müşteri için Vergi No ve Vergi Dairesi zorunlu
        if customer_type in ('corporate', 'company'):
            if not tax_number:
                self.add_error('tax_number', 'Kurumsal müşteriler için Vergi No zorunludur.')
            elif len(tax_number) != 10:
                self.add_error('tax_number', 'Vergi No tam olarak 10 hane olmalıdır.')
            elif not tax_number.isdigit():
                self.add_error('tax_number', 'Vergi No sadece rakamlardan oluşmalıdır.')
            
            if not tax_office:
                self.add_error('tax_office', 'Kurumsal müşteriler için Vergi Dairesi zorunludur.')
            
            if not cleaned_data.get('company_name'):
                self.add_error('company_name', 'Kurumsal müşteriler için Şirket Adı zorunludur.')
        
        return cleaned_data


class CheckoutForm(forms.ModelForm):
    CUSTOMER_TYPE_CHOICES = [
        ("individual", "Bireysel"),
        ("company", "Şirket"),
    ]
    customer_type = forms.ChoiceField(
        choices=CUSTOMER_TYPE_CHOICES,
        widget=forms.RadioSelect,
        initial="individual",
        label="Müşteri Tipi",
    )
    tc_kimlik = forms.CharField(
        max_length=11,
        min_length=11,
        required=False,
        error_messages={
            "min_length": "TC Kimlik No tam olarak 11 hane olmalıdır.",
            "max_length": "TC Kimlik No en fazla 11 hane olmalıdır.",
        },
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "11111111111",
            "maxlength": "11",
            "inputmode": "numeric",
            "pattern": "[0-9]{11}",
        }),
        label="TC Kimlik No",
    )
    tax_number = forms.CharField(
        max_length=10,
        min_length=10,
        required=False,
        error_messages={
            "min_length": "Vergi No tam olarak 10 hane olmalıdır.",
            "max_length": "Vergi No en fazla 10 hane olmalıdır.",
        },
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "1234567890",
            "maxlength": "10",
            "inputmode": "numeric",
            "pattern": "[0-9]{10}",
        }),
        label="Vergi No",
    )
    tax_office = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Örn: Büyük Mükellefler VD",
        }),
        label="Vergi Dairesi",
    )
    payment_method = forms.CharField(
        required=False,
        initial="credit_card",
        widget=forms.HiddenInput(),
    )
    referral_code = forms.CharField(
        max_length=40,
        required=False,
        label="Promosyon kodu",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Varsa promosyon kodunuz",
            "autocomplete": "off",
        }),
    )
    card_holder = forms.CharField(max_length=120, required=False)
    card_number = forms.CharField(max_length=19, required=False)
    expiry_month = forms.CharField(max_length=2, required=False)
    expiry_year = forms.CharField(max_length=2, required=False)
    cvv = forms.CharField(max_length=4, required=False)
    legal_acceptance = forms.BooleanField(
        required=True,
        label="Satış ve üyelik sözleşmelerini okudum ve kabul ediyorum.",
        error_messages={"required": "Ödemeye devam etmek için satış ve üyelik sözleşmelerini onaylamalısınız."},
    )
    immediate_service_consent = forms.BooleanField(
        required=True,
        label="Hizmetin cayma süresi dolmadan başlatılmasını talep ediyorum.",
        error_messages={"required": "Dijital hizmetin hemen başlatılması için açık talebinizi onaylamalısınız."},
    )

    class Meta:
        model = BillingInfo
        fields = [
            "customer_type", "first_name", "last_name", "email", "phone",
            "company_name", "tax_office", "tax_number", "tc_kimlik",
            "address", "city", "district", "zip_code",
        ]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Adınız", "required": "required"}),
            "last_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Soyadınız", "required": "required"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "ornek@email.com", "required": "required"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "5XXXXXXXXX", "required": "required"}),
            "company_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Şirket Unvanı"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Açık adresiniz", "required": "required"}),
            "city": forms.TextInput(attrs={"class": "form-control", "placeholder": "İl", "required": "required"}),
            "district": forms.TextInput(attrs={"class": "form-control", "placeholder": "İlçe", "required": "required"}),
            "zip_code": forms.TextInput(attrs={"class": "form-control", "placeholder": "Posta Kodu", "required": "required", "maxlength": "10"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        from core.services.legal_documents import purchase_documents_ready

        if not purchase_documents_ready():
            self.add_error(None, "Ödeme için zorunlu sözleşmelerin tamamı yayında değil. Lütfen destek ekibiyle iletişime geçin.")
        customer_type = cleaned_data.get("customer_type")
        tc_kimlik = (cleaned_data.get("tc_kimlik") or "").strip()
        tax_number = (cleaned_data.get("tax_number") or "").strip()
        tax_office = (cleaned_data.get("tax_office") or "").strip()

        required_fields = {
            "first_name": "Ad",
            "last_name": "Soyad",
            "email": "E-posta",
            "phone": "Telefon",
            "address": "Adres",
            "city": "İl",
            "district": "İlçe",
            "zip_code": "Posta kodu",
        }
        for field_name, label in required_fields.items():
            if not (cleaned_data.get(field_name) or "").strip():
                self.add_error(field_name, f"{label} alanı zorunludur.")

        if customer_type == "individual" and "tc_kimlik" not in self.errors:
            if not tc_kimlik:
                self.add_error("tc_kimlik", "Bireysel müşteriler için TC Kimlik No zorunludur.")
            elif len(tc_kimlik) != 11:
                self.add_error("tc_kimlik", "TC Kimlik No tam olarak 11 hane olmalıdır.")
            elif not tc_kimlik.isdigit():
                self.add_error("tc_kimlik", "TC Kimlik No sadece rakamlardan oluşmalıdır.")

        if customer_type == "company":
            if not (cleaned_data.get("company_name") or "").strip():
                self.add_error("company_name", "Şirket unvanı zorunludur.")
            if not tax_office:
                self.add_error("tax_office", "Şirket için Vergi Dairesi zorunludur.")
            if not tax_number and "tax_number" not in self.errors:
                self.add_error("tax_number", "Şirket için Vergi No zorunludur.")
            elif tax_number and "tax_number" not in self.errors and len(tax_number) != 10:
                self.add_error("tax_number", "Vergi No tam olarak 10 hane olmalıdır.")
            elif tax_number and "tax_number" not in self.errors and not tax_number.isdigit():
                self.add_error("tax_number", "Vergi No sadece rakamlardan oluşmalıdır.")

        cleaned_data["tc_kimlik"] = tc_kimlik
        cleaned_data["tax_number"] = tax_number
        cleaned_data["tax_office"] = tax_office
        cleaned_data["card_number"] = (cleaned_data.get("card_number") or "").replace(" ", "")
        cleaned_data["expiry_month"] = (cleaned_data.get("expiry_month") or "").strip()
        cleaned_data["expiry_year"] = (cleaned_data.get("expiry_year") or "").strip()
        cleaned_data["cvv"] = (cleaned_data.get("cvv") or "").strip()
        cleaned_data["referral_code"] = (cleaned_data.get("referral_code") or "").strip().upper()

        if cleaned_data.get("payment_method") != "bank_transfer":
            if not (cleaned_data.get("card_holder") or "").strip():
                self.add_error("card_holder", "Kart üzerindeki isim zorunludur.")
            if len(cleaned_data["card_number"]) != 16 or not cleaned_data["card_number"].isdigit():
                self.add_error("card_number", "Kart numarası 16 haneden oluşmalıdır.")
            month = int(cleaned_data["expiry_month"]) if cleaned_data["expiry_month"].isdigit() else 0
            year = int(cleaned_data["expiry_year"]) if cleaned_data["expiry_year"].isdigit() else 0
            if not 1 <= month <= 12:
                self.add_error("expiry_month", "Geçerli bir son kullanma ayı girin.")
            if year < 1:
                self.add_error("expiry_year", "Son kullanma yılı zorunludur.")
            else:
                full_year = 2000 + year if year < 100 else year
                today = timezone.localdate()
                if full_year < today.year or (full_year == today.year and month < today.month):
                    self.add_error("expiry_year", "Kartın son kullanma tarihi geçmiş.")
            if len(cleaned_data["cvv"]) < 3 or not cleaned_data["cvv"].isdigit():
                self.add_error("cvv", "CVV zorunludur.")
        return cleaned_data
