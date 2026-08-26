from django.conf import settings
from django.db import models

from core.fields import EncryptedTextField


SUPPORTED_MARKETPLACE_CODES = ("trendyol", "hepsiburada", "n11")


class Marketplace(models.Model):
    """Supported marketplace reference table."""

    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    api_base_url = models.URLField(blank=True, default="")
    docs_url = models.URLField(blank=True, default="")
    website_url = models.URLField(blank=True, default="", verbose_name="Mağaza ana adresi")
    search_url_template = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Arama terimi için {query} yer tutucusunu kullanın.",
        verbose_name="Arama URL şablonu",
    )
    allowed_domains = models.JSONField(default=list, blank=True, verbose_name="İzinli alan adları")
    research_enabled = models.BooleanField(default=True, db_index=True, verbose_name="Araştırmada kullan")
    browser_verification_enabled = models.BooleanField(default=False, db_index=True, verbose_name="Tarayıcı doğrulaması")
    categories = models.JSONField(default=list, blank=True, verbose_name="Öncelikli kategoriler")
    search_priority = models.PositiveIntegerField(default=100, verbose_name="Arama önceliği")
    max_results = models.PositiveIntegerField(default=10, verbose_name="Azami sonuç")
    timeout_seconds = models.PositiveIntegerField(default=20, verbose_name="Zaman aşımı (sn)")
    credit_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=1, verbose_name="Maliyet çarpanı")
    is_active = models.BooleanField(default=True, db_index=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pazaryeri"
        verbose_name_plural = "Pazaryerleri"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class MarketplaceAccount(models.Model):
    """Subscriber-owned marketplace store connection."""

    SYNC_MODE_SALES_READY = "sales_ready"
    SYNC_MODE_INCLUDE_OUT_OF_STOCK = "include_out_of_stock"
    SYNC_MODE_FULL_ARCHIVE = "full_archive"
    SYNC_MODE_CHOICES = [
        (SYNC_MODE_SALES_READY, "Satışa hazır ürünler"),
        (SYNC_MODE_INCLUDE_OUT_OF_STOCK, "Stok dışı aktif ürünler dahil"),
        (SYNC_MODE_FULL_ARCHIVE, "Tam arşiv"),
    ]

    marketplace = models.ForeignKey(Marketplace, on_delete=models.PROTECT, related_name="accounts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="marketplace_accounts")
    organization = models.ForeignKey(
        "core.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_accounts",
    )
    subscription = models.ForeignKey(
        "core.UserSubscription",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_accounts",
    )
    agency_client = models.ForeignKey(
        "core.AgencyClient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_accounts",
    )
    store_name = models.CharField(max_length=150)
    seller_id = models.CharField(max_length=120, blank=True, default="")
    api_key_encrypted = EncryptedTextField(blank=True, default="")
    api_secret_encrypted = EncryptedTextField(blank=True, default="")
    extra_credentials = models.JSONField(default=dict, blank=True)
    sync_mode = models.CharField(
        max_length=30,
        choices=SYNC_MODE_CHOICES,
        default=SYNC_MODE_SALES_READY,
        db_index=True,
    )
    sync_product_limit = models.PositiveIntegerField(default=250)
    include_products_without_price = models.BooleanField(default=False)
    price_stock_sync_interval_minutes = models.PositiveIntegerField(default=240)
    catalog_sync_interval_minutes = models.PositiveIntegerField(default=1440)
    is_active = models.BooleanField(default=True, db_index=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pazaryeri Hesabı"
        verbose_name_plural = "Pazaryeri Hesapları"
        ordering = ["marketplace__order", "store_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["marketplace", "user", "organization", "seller_id"],
                name="uniq_marketplace_account_owner_seller",
            )
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["organization", "is_active"]),
            models.Index(fields=["marketplace", "is_active"]),
        ]

    def __str__(self):
        return f"{self.marketplace.name} - {self.store_name}"


class MarketplaceSyncRun(models.Model):
    SYNC_TYPE_INITIAL = "initial"
    SYNC_TYPE_CATALOG = "catalog"
    SYNC_TYPE_PRICE_STOCK = "price_stock"
    SYNC_TYPE_MANUAL = "manual"
    SYNC_TYPE_CHOICES = [
        (SYNC_TYPE_INITIAL, "İlk senkronizasyon"),
        (SYNC_TYPE_CATALOG, "Ürün bilgileri"),
        (SYNC_TYPE_PRICE_STOCK, "Fiyat / stok"),
        (SYNC_TYPE_MANUAL, "Manuel"),
    ]

    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "Sırada"),
        (STATUS_RUNNING, "Çalışıyor"),
        (STATUS_SUCCESS, "Tamamlandı"),
        (STATUS_FAILED, "Hatalı"),
        (STATUS_SKIPPED, "Atlandı"),
    ]

    marketplace_account = models.ForeignKey(
        MarketplaceAccount,
        on_delete=models.CASCADE,
        related_name="sync_runs",
    )
    sync_type = models.CharField(max_length=20, choices=SYNC_TYPE_CHOICES, default=SYNC_TYPE_MANUAL)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED, db_index=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_marketplace_sync_runs",
    )
    product_limit = models.PositiveIntegerField(default=250)
    filters = models.JSONField(default=dict, blank=True)
    fetched_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Pazaryeri Senkronizasyonu"
        verbose_name_plural = "Pazaryeri Senkronizasyonları"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["marketplace_account", "status"]),
            models.Index(fields=["sync_type", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.marketplace_account} - {self.get_sync_type_display()} - {self.get_status_display()}"


class Product(models.Model):
    """Subscriber-owned canonical product shared by all marketplaces."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="marketplace_products")
    organization = models.ForeignKey(
        "core.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_products",
    )
    subscription = models.ForeignKey(
        "core.UserSubscription",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_products",
    )
    agency_client = models.ForeignKey(
        "core.AgencyClient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_products",
    )
    sku = models.CharField(max_length=120)
    barcode = models.CharField(max_length=120, blank=True, default="")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    brand = models.CharField(max_length=150, blank=True, default="")
    category_name = models.CharField(max_length=255, blank=True, default="")
    image_url = models.URLField(blank=True, default="")
    image_gallery = models.JSONField(default=list, blank=True)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    default_sale_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="TRY")
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=20)
    weight_kg = models.DecimalField(max_digits=8, decimal_places=3, default=0)
    width_cm = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    height_cm = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    length_cm = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ürün"
        verbose_name_plural = "Ürünler"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["user", "organization", "sku"], name="uniq_product_owner_sku")
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["organization", "is_active"]),
            models.Index(fields=["sku"]),
            models.Index(fields=["barcode"]),
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.sku})"


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField(max_length=120)
    barcode = models.CharField(max_length=120, blank=True, default="")
    color = models.CharField(max_length=100, blank=True, default="")
    size = models.CharField(max_length=100, blank=True, default="")
    image_url = models.URLField(blank=True, default="")
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ürün Varyantı"
        verbose_name_plural = "Ürün Varyantları"
        ordering = ["product__name", "color", "size"]
        constraints = [
            models.UniqueConstraint(fields=["product", "sku"], name="uniq_product_variant_sku")
        ]
        indexes = [
            models.Index(fields=["sku"]),
            models.Index(fields=["barcode"]),
            models.Index(fields=["size"]),
        ]

    def __str__(self):
        label = " / ".join(part for part in [self.color, self.size] if part)
        return f"{self.product.name} - {label or self.sku}"


class MarketplaceListing(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_PASSIVE = "passive"
    STATUS_PENDING = "pending"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Aktif"),
        (STATUS_PASSIVE, "Pasif"),
        (STATUS_PENDING, "Onayda"),
        (STATUS_REJECTED, "Reddedildi"),
    ]

    marketplace_account = models.ForeignKey(
        MarketplaceAccount,
        on_delete=models.CASCADE,
        related_name="listings",
    )
    marketplace = models.ForeignKey(Marketplace, on_delete=models.PROTECT, related_name="listings")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="marketplace_listings")
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="marketplace_listings",
    )
    platform_product_id = models.CharField(max_length=150, blank=True, default="")
    platform_sku = models.CharField(max_length=150, blank=True, default="")
    platform_barcode = models.CharField(max_length=150, blank=True, default="")
    platform_category_id = models.CharField(max_length=150, blank=True, default="")
    platform_category_name = models.CharField(max_length=255, blank=True, default="")
    platform_url = models.URLField(blank=True, default="")
    platform_brand = models.CharField(max_length=150, blank=True, default="")
    platform_image_url = models.URLField(blank=True, default="")
    platform_description = models.TextField(blank=True, default="")
    sale_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discounted_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock = models.IntegerField(default=0)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    cargo_company = models.CharField(max_length=120, blank=True, default="")
    delivery_type = models.CharField(max_length=80, blank=True, default="")
    estimated_delivery_days = models.PositiveIntegerField(default=0)
    desi = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    free_shipping = models.BooleanField(default=False)
    campaign_name = models.CharField(max_length=180, blank=True, default="")
    rating_average = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    rating_count = models.PositiveIntegerField(default=0)
    review_count = models.PositiveIntegerField(default=0)
    favorite_count = models.PositiveIntegerField(default=0)
    view_count = models.PositiveIntegerField(default=0)
    buybox_rank = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pazaryeri Ürün Kaydı"
        verbose_name_plural = "Pazaryeri Ürün Kayıtları"
        ordering = ["product__name", "marketplace__order"]
        constraints = [
            models.UniqueConstraint(
                fields=["marketplace_account", "platform_sku", "platform_product_id"],
                name="uniq_marketplace_listing_external_identity",
            )
        ]
        indexes = [
            models.Index(fields=["marketplace", "status"]),
            models.Index(fields=["marketplace_account", "status"]),
            models.Index(fields=["platform_sku"]),
            models.Index(fields=["platform_barcode"]),
            models.Index(fields=["last_synced_at"]),
        ]

    @property
    def effective_sale_price(self):
        return self.discounted_price or self.sale_price

    @property
    def purchase_price(self):
        if self.variant_id and self.variant.purchase_price:
            return self.variant.purchase_price
        return self.product.purchase_price

    @property
    def gross_profit(self):
        return self.effective_sale_price - self.purchase_price

    def __str__(self):
        return f"{self.marketplace.name} - {self.product.name}"


class MarketplaceListingMetricHistory(models.Model):
    """Daily marketplace listing snapshot for stock, price and commercial metrics."""

    listing = models.ForeignKey(
        MarketplaceListing,
        on_delete=models.CASCADE,
        related_name="metric_history",
    )
    marketplace_account = models.ForeignKey(
        MarketplaceAccount,
        on_delete=models.CASCADE,
        related_name="listing_metric_history",
    )
    marketplace = models.ForeignKey(Marketplace, on_delete=models.PROTECT, related_name="listing_metric_history")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="marketplace_metric_history")
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_metric_history",
    )
    date = models.DateField(db_index=True)
    sale_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discounted_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    stock = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=MarketplaceListing.STATUS_CHOICES, default=MarketplaceListing.STATUS_ACTIVE, db_index=True)
    gross_profit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gross_margin_rate = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    orders = models.PositiveIntegerField(default=0)
    units_sold = models.PositiveIntegerField(default=0)
    revenue = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    view_count = models.PositiveIntegerField(default=0)
    favorite_count = models.PositiveIntegerField(default=0)
    review_count = models.PositiveIntegerField(default=0)
    return_count = models.PositiveIntegerField(default=0)
    buybox_rank = models.PositiveIntegerField(default=0)
    raw_metrics = models.JSONField(default=dict, blank=True)
    sync_run = models.ForeignKey(
        MarketplaceSyncRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="listing_metric_history",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Pazaryeri Listeleme Metrik Geçmişi"
        verbose_name_plural = "Pazaryeri Listeleme Metrik Geçmişleri"
        ordering = ["-date", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["listing", "date"], name="uniq_marketplace_listing_metric_date")
        ]
        indexes = [
            models.Index(fields=["marketplace_account", "date"]),
            models.Index(fields=["marketplace", "date"]),
            models.Index(fields=["product", "date"]),
            models.Index(fields=["status", "date"]),
        ]

    def __str__(self):
        return f"{self.listing} - {self.date}"


class MarketplaceProductChangeHistory(models.Model):
    CHANGE_CREATED = "created"
    CHANGE_UPDATED = "updated"
    CHANGE_PRICE = "price"
    CHANGE_STOCK = "stock"
    CHANGE_STATUS = "status"
    CHANGE_CATEGORY = "category"
    CHANGE_CHOICES = [
        (CHANGE_CREATED, "Oluşturuldu"),
        (CHANGE_UPDATED, "Güncellendi"),
        (CHANGE_PRICE, "Fiyat değişti"),
        (CHANGE_STOCK, "Stok değişti"),
        (CHANGE_STATUS, "Durum değişti"),
        (CHANGE_CATEGORY, "Kategori değişti"),
    ]

    listing = models.ForeignKey(
        MarketplaceListing,
        on_delete=models.CASCADE,
        related_name="change_history",
    )
    marketplace_account = models.ForeignKey(
        MarketplaceAccount,
        on_delete=models.CASCADE,
        related_name="product_change_history",
    )
    marketplace = models.ForeignKey(Marketplace, on_delete=models.PROTECT, related_name="product_change_history")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="marketplace_change_history")
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_change_history",
    )
    sync_run = models.ForeignKey(
        MarketplaceSyncRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="product_change_history",
    )
    change_type = models.CharField(max_length=20, choices=CHANGE_CHOICES, db_index=True)
    field_name = models.CharField(max_length=80, blank=True, default="")
    old_value = models.CharField(max_length=255, blank=True, default="")
    new_value = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Pazaryeri Ürün Değişim Geçmişi"
        verbose_name_plural = "Pazaryeri Ürün Değişim Geçmişleri"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["marketplace_account", "created_at"]),
            models.Index(fields=["marketplace", "change_type"]),
            models.Index(fields=["product", "created_at"]),
        ]

    def __str__(self):
        return f"{self.listing} - {self.get_change_type_display()}"


class MarketplaceProductResearch(models.Model):
    MODE_IMAGE_AUTO = "image_auto"
    MODE_CHOICES = [
        (MODE_IMAGE_AUTO, "Görselden AI araştırma promptu"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_QUEUED = "queued"
    STATUS_ANALYZING = "analyzing"
    STATUS_SEARCHING = "searching"
    STATUS_VERIFYING = "verifying"
    STATUS_MATCHING = "matching"
    STATUS_COMPLETED = "completed"
    STATUS_PARTIAL = "partial"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Taslak"),
        (STATUS_QUEUED, "Kuyrukta"),
        (STATUS_ANALYZING, "Görsel ve talimat analiz ediliyor"),
        (STATUS_SEARCHING, "Pazaryerleri aranıyor"),
        (STATUS_VERIFYING, "Ürün sayfaları doğrulanıyor"),
        (STATUS_MATCHING, "Sonuçlar eşleştiriliyor"),
        (STATUS_COMPLETED, "Tamamlandı"),
        (STATUS_PARTIAL, "Kısmi tamamlandı"),
        (STATUS_FAILED, "Hatalı"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="marketplace_product_researches")
    organization = models.ForeignKey(
        "core.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_product_researches",
    )
    subscription = models.ForeignKey(
        "core.UserSubscription",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_product_researches",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_researches",
    )
    title = models.CharField(max_length=180, blank=True, default="")
    product_image = models.ImageField(upload_to="marketplace/research/%Y/%m/", null=True, blank=True)
    prompt = models.TextField(help_text="Virgül ile ayrılmış ürün özellikleri, kullanım alanı, materyal, marka vb.")
    search_mode = models.CharField(max_length=20, choices=MODE_CHOICES, default=MODE_IMAGE_AUTO, db_index=True)
    generated_prompt = models.TextField(blank=True, default="")
    parsed_intent = models.JSONField(default=dict, blank=True)
    search_plan = models.JSONField(default=dict, blank=True)
    selected_marketplaces = models.ManyToManyField(Marketplace, blank=True, related_name="product_researches")
    progress_percent = models.PositiveSmallIntegerField(default=0)
    current_step = models.CharField(max_length=180, blank=True, default="")
    celery_task_id = models.CharField(max_length=80, blank=True, default="", db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    detected_product_name = models.CharField(max_length=180, blank=True, default="")
    detected_category = models.CharField(max_length=180, blank=True, default="")
    detected_attributes = models.JSONField(default=list, blank=True)
    result_items = models.JSONField(default=list, blank=True)
    price_bands = models.JSONField(default=list, blank=True)
    min_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    max_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    average_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    recommended_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    recommendation_summary = models.TextField(blank=True, default="")
    confidence_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    track_price = models.BooleanField(default=False, db_index=True)
    tracking_interval_hours = models.PositiveIntegerField(default=24)
    last_tracked_at = models.DateTimeField(null=True, blank=True)
    next_tracking_at = models.DateTimeField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    source = models.CharField(max_length=30, default="live_market")
    raw_result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pazaryeri Ürün Pazar Araştırması"
        verbose_name_plural = "Pazaryeri Ürün Pazar Araştırmaları"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["product", "-created_at"]),
            models.Index(fields=["track_price", "next_tracking_at"]),
        ]

    def __str__(self):
        return self.title or self.detected_product_name or f"Araştırma #{self.pk}"


class MarketplaceProductResearchResult(models.Model):
    research = models.ForeignKey(
        MarketplaceProductResearch,
        on_delete=models.CASCADE,
        related_name="normalized_results",
    )
    marketplace = models.ForeignKey(
        Marketplace,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="research_results",
    )
    provider = models.CharField(max_length=50, blank=True, default="")
    title = models.CharField(max_length=500)
    product_url = models.URLField(max_length=2000)
    image_url = models.URLField(max_length=2000, blank=True, default="")
    seller_name = models.CharField(max_length=255, blank=True, default="")
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, default="TRY")
    in_stock = models.BooleanField(null=True, blank=True)
    variant = models.CharField(max_length=180, blank=True, default="")
    match_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    visual_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    authenticity_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_eligible = models.BooleanField(default=True, db_index=True)
    verification_status = models.CharField(max_length=30, blank=True, default="discovered", db_index=True)
    match_explanation = models.JSONField(default=list, blank=True)
    authenticity_evidence = models.JSONField(default=list, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ürün Araştırma Sonucu"
        verbose_name_plural = "Ürün Araştırma Sonuçları"
        ordering = ["total_price", "-match_score", "id"]
        indexes = [
            models.Index(fields=["research", "is_eligible"]),
            models.Index(fields=["marketplace", "verification_status"]),
        ]

    def __str__(self):
        return f"{self.title} - {self.total_price} {self.currency}"


class MarketplaceProductResearchMetricHistory(models.Model):
    """Tracked price intelligence snapshots for a product research."""

    CHANGE_STABLE = "stable"
    CHANGE_UP = "up"
    CHANGE_DOWN = "down"
    CHANGE_CHOICES = [
        (CHANGE_STABLE, "Değişmedi"),
        (CHANGE_UP, "Yükseldi"),
        (CHANGE_DOWN, "Düştü"),
    ]

    research = models.ForeignKey(
        MarketplaceProductResearch,
        on_delete=models.CASCADE,
        related_name="metric_history",
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="marketplace_research_metric_history")
    organization = models.ForeignKey(
        "core.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_research_metric_history",
    )
    subscription = models.ForeignKey(
        "core.UserSubscription",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_research_metric_history",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marketplace_research_metric_history",
    )
    checked_at = models.DateTimeField(db_index=True)
    min_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    max_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    average_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    recommended_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    previous_recommended_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    recommended_price_change = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    recommended_price_change_percent = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    change_direction = models.CharField(max_length=12, choices=CHANGE_CHOICES, default=CHANGE_STABLE, db_index=True)
    result_count = models.PositiveIntegerField(default=0)
    high_competition_count = models.PositiveIntegerField(default=0)
    medium_competition_count = models.PositiveIntegerField(default=0)
    low_competition_count = models.PositiveIntegerField(default=0)
    result_items = models.JSONField(default=list, blank=True)
    price_bands = models.JSONField(default=list, blank=True)
    raw_result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Pazaryeri Araştırma Fiyat Takip Geçmişi"
        verbose_name_plural = "Pazaryeri Araştırma Fiyat Takip Geçmişleri"
        ordering = ["-checked_at"]
        indexes = [
            models.Index(fields=["user", "-checked_at"]),
            models.Index(fields=["research", "-checked_at"]),
            models.Index(fields=["product", "-checked_at"]),
        ]

    def __str__(self):
        return f"{self.research} - {self.checked_at:%Y-%m-%d %H:%M}"
