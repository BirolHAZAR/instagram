from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.models import (
    MarketplaceAccount,
    MarketplaceListing,
    MarketplaceListingMetricHistory,
    MarketplaceProductChangeHistory,
    MarketplaceSyncRun,
    Product,
    ProductVariant,
)


DEFAULT_PRODUCT_LIMIT = 250
MAX_PRODUCT_LIMIT = 5000


class MarketplaceConnectorNotReady(Exception):
    pass


@dataclass(frozen=True)
class MarketplaceProductPayload:
    product_id: str
    sku: str
    barcode: str
    name: str
    description: str = ""
    brand: str = ""
    category_id: str = ""
    category_name: str = ""
    image_url: str = ""
    image_gallery: list | None = None
    sale_price: Decimal = Decimal("0")
    discounted_price: Decimal = Decimal("0")
    stock: int = 0
    status: str = MarketplaceListing.STATUS_ACTIVE
    platform_url: str = ""
    cargo_company: str = ""
    delivery_type: str = ""
    estimated_delivery_days: int = 0
    desi: Decimal = Decimal("0")
    free_shipping: bool = False
    campaign_name: str = ""
    rating_average: Decimal = Decimal("0")
    rating_count: int = 0
    review_count: int = 0
    favorite_count: int = 0
    view_count: int = 0
    buybox_rank: int = 0
    variant_sku: str = ""
    variant_barcode: str = ""
    color: str = ""
    size: str = ""
    variant_image_url: str = ""
    raw_payload: dict | None = None


class BaseMarketplaceConnector:
    page_size = 100

    def __init__(self, account):
        self.account = account

    def fetch_products(self, *, filters, limit):
        raise MarketplaceConnectorNotReady(
            f"{self.account.marketplace.name} ürün API bağlayıcısı henüz aktif değil."
        )


class TrendyolConnector(BaseMarketplaceConnector):
    pass


class HepsiburadaConnector(BaseMarketplaceConnector):
    pass


class N11Connector(BaseMarketplaceConnector):
    pass


CONNECTORS = {
    "trendyol": TrendyolConnector,
    "hepsiburada": HepsiburadaConnector,
    "n11": N11Connector,
}


def sync_filters_for_account(account):
    filters = {
        "only_active": True,
        "min_stock": 1,
        "require_price": not account.include_products_without_price,
        "include_passive": False,
        "include_out_of_stock": False,
        "order_by": ["updated_at_desc", "stock_desc"],
    }
    if account.sync_mode == MarketplaceAccount.SYNC_MODE_INCLUDE_OUT_OF_STOCK:
        filters["min_stock"] = 0
        filters["include_out_of_stock"] = True
    elif account.sync_mode == MarketplaceAccount.SYNC_MODE_FULL_ARCHIVE:
        filters["min_stock"] = 0
        filters["include_out_of_stock"] = True
        filters["include_passive"] = True
        filters["only_active"] = False
    return filters


def effective_product_limit(account):
    raw_limit = account.sync_product_limit or DEFAULT_PRODUCT_LIMIT
    return min(max(raw_limit, 50), MAX_PRODUCT_LIMIT)


def enqueue_marketplace_sync(account, *, requested_by=None, sync_type=MarketplaceSyncRun.SYNC_TYPE_MANUAL):
    existing = account.sync_runs.filter(
        status__in=[MarketplaceSyncRun.STATUS_QUEUED, MarketplaceSyncRun.STATUS_RUNNING]
    ).first()
    if existing:
        return existing, False

    run = MarketplaceSyncRun.objects.create(
        marketplace_account=account,
        requested_by=requested_by,
        sync_type=sync_type,
        product_limit=effective_product_limit(account),
        filters=sync_filters_for_account(account),
    )
    return run, True


def connector_for_account(account):
    connector_class = CONNECTORS.get(account.marketplace.code)
    if not connector_class:
        raise MarketplaceConnectorNotReady(f"{account.marketplace.name} için bağlayıcı tanımlı değil.")
    return connector_class(account)


def should_keep_payload(payload, filters):
    if filters.get("only_active") and payload.status != MarketplaceListing.STATUS_ACTIVE:
        return False
    if not filters.get("include_passive") and payload.status == MarketplaceListing.STATUS_PASSIVE:
        return False
    if payload.stock < int(filters.get("min_stock", 0)):
        return False
    if filters.get("require_price") and payload.sale_price <= 0:
        return False
    return True


def run_marketplace_sync(sync_run_id):
    run = MarketplaceSyncRun.objects.select_related(
        "marketplace_account",
        "marketplace_account__marketplace",
        "marketplace_account__user",
        "marketplace_account__organization",
        "marketplace_account__subscription",
        "marketplace_account__agency_client",
    ).get(id=sync_run_id)

    account = run.marketplace_account
    run.status = MarketplaceSyncRun.STATUS_RUNNING
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])

    try:
        connector = connector_for_account(account)
        payloads = connector.fetch_products(filters=run.filters, limit=run.product_limit)
    except MarketplaceConnectorNotReady as exc:
        run.status = MarketplaceSyncRun.STATUS_SKIPPED
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        return {"status": run.status, "message": run.error_message}
    except Exception as exc:
        run.status = MarketplaceSyncRun.STATUS_FAILED
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        raise

    counters = {"fetched": 0, "created": 0, "updated": 0, "skipped": 0}
    for payload in payloads:
        counters["fetched"] += 1
        if counters["fetched"] > run.product_limit:
            break
        if not should_keep_payload(payload, run.filters):
            counters["skipped"] += 1
            continue
        created = upsert_marketplace_payload(account, payload, sync_run=run)
        counters["created" if created else "updated"] += 1

    now = timezone.now()
    account.last_sync_at = now
    account.save(update_fields=["last_sync_at"])
    run.status = MarketplaceSyncRun.STATUS_SUCCESS
    run.fetched_count = counters["fetched"]
    run.created_count = counters["created"]
    run.updated_count = counters["updated"]
    run.skipped_count = counters["skipped"]
    run.finished_at = now
    run.save(
        update_fields=[
            "status",
            "fetched_count",
            "created_count",
            "updated_count",
            "skipped_count",
            "finished_at",
        ]
    )
    return {"status": run.status, **counters}


@transaction.atomic
def upsert_marketplace_payload(account, payload, sync_run=None):
    product_sku = payload.sku or payload.barcode or payload.product_id
    product, _ = Product.objects.update_or_create(
        user=account.user,
        organization=account.organization,
        sku=product_sku,
        defaults={
            "subscription": account.subscription,
            "agency_client": account.agency_client,
            "barcode": payload.barcode,
            "name": payload.name,
            "description": payload.description,
            "brand": payload.brand,
            "category_name": payload.category_name,
            "image_url": payload.image_url,
            "image_gallery": payload.image_gallery or [],
            "default_sale_price": payload.sale_price,
            "is_active": payload.status == MarketplaceListing.STATUS_ACTIVE,
        },
    )

    variant = None
    if payload.variant_sku:
        variant, _ = ProductVariant.objects.update_or_create(
            product=product,
            sku=payload.variant_sku,
            defaults={
                "barcode": payload.variant_barcode,
                "color": payload.color,
                "size": payload.size,
                "image_url": payload.variant_image_url or payload.image_url,
                "is_active": payload.status == MarketplaceListing.STATUS_ACTIVE,
            },
        )

    lookup = {
        "marketplace_account": account,
        "platform_sku": payload.sku,
        "platform_product_id": payload.product_id,
    }
    existing_listing = MarketplaceListing.objects.filter(**lookup).first()
    previous_values = listing_trackable_values(existing_listing) if existing_listing else {}

    listing, created = MarketplaceListing.objects.update_or_create(
        **lookup,
        defaults={
            "marketplace": account.marketplace,
            "product": product,
            "variant": variant,
            "platform_barcode": payload.barcode,
            "platform_category_id": payload.category_id,
            "platform_category_name": payload.category_name,
            "platform_url": payload.platform_url,
            "platform_brand": payload.brand,
            "platform_image_url": payload.variant_image_url or payload.image_url,
            "platform_description": payload.description,
            "sale_price": payload.sale_price,
            "discounted_price": payload.discounted_price,
            "stock": payload.stock,
            "cargo_company": payload.cargo_company,
            "delivery_type": payload.delivery_type,
            "estimated_delivery_days": payload.estimated_delivery_days,
            "desi": payload.desi,
            "free_shipping": payload.free_shipping,
            "campaign_name": payload.campaign_name,
            "rating_average": payload.rating_average,
            "rating_count": payload.rating_count,
            "review_count": payload.review_count,
            "favorite_count": payload.favorite_count,
            "view_count": payload.view_count,
            "buybox_rank": payload.buybox_rank,
            "status": payload.status,
            "raw_payload": payload.raw_payload or {},
            "last_synced_at": timezone.now(),
        },
    )
    record_listing_metric_history(listing, sync_run=sync_run)
    record_listing_change_history(
        listing,
        previous_values=previous_values,
        created=created,
        sync_run=sync_run,
    )
    return created


def listing_trackable_values(listing):
    if not listing:
        return {}
    return {
        "sale_price": listing.sale_price,
        "discounted_price": listing.discounted_price,
        "stock": listing.stock,
        "status": listing.status,
        "platform_category_id": listing.platform_category_id,
        "platform_category_name": listing.platform_category_name,
    }


def record_listing_metric_history(listing, *, sync_run=None, metric_date=None):
    metric_date = metric_date or timezone.now().date()
    effective_price = listing.effective_sale_price
    purchase_price = listing.purchase_price
    gross_profit = effective_price - purchase_price
    gross_margin_rate = Decimal("0")
    if effective_price:
        gross_margin_rate = (gross_profit / effective_price) * Decimal("100")

    MarketplaceListingMetricHistory.objects.update_or_create(
        listing=listing,
        date=metric_date,
        defaults={
            "marketplace_account": listing.marketplace_account,
            "marketplace": listing.marketplace,
            "product": listing.product,
            "variant": listing.variant,
            "sale_price": listing.sale_price,
            "discounted_price": listing.discounted_price,
            "purchase_price": purchase_price,
            "commission_rate": listing.commission_rate,
            "stock": listing.stock,
            "status": listing.status,
            "gross_profit": gross_profit,
            "gross_margin_rate": gross_margin_rate,
            "view_count": listing.view_count,
            "favorite_count": listing.favorite_count,
            "review_count": listing.review_count,
            "buybox_rank": listing.buybox_rank,
            "sync_run": sync_run,
            "raw_metrics": {
                "platform_sku": listing.platform_sku,
                "platform_product_id": listing.platform_product_id,
                "platform_barcode": listing.platform_barcode,
            },
        },
    )


def record_listing_change_history(listing, *, previous_values, created=False, sync_run=None):
    if created:
        MarketplaceProductChangeHistory.objects.create(
            listing=listing,
            marketplace_account=listing.marketplace_account,
            marketplace=listing.marketplace,
            product=listing.product,
            variant=listing.variant,
            sync_run=sync_run,
            change_type=MarketplaceProductChangeHistory.CHANGE_CREATED,
            field_name="listing",
            old_value="",
            new_value="created",
        )
        return

    current_values = listing_trackable_values(listing)
    change_type_by_field = {
        "sale_price": MarketplaceProductChangeHistory.CHANGE_PRICE,
        "discounted_price": MarketplaceProductChangeHistory.CHANGE_PRICE,
        "stock": MarketplaceProductChangeHistory.CHANGE_STOCK,
        "status": MarketplaceProductChangeHistory.CHANGE_STATUS,
        "platform_category_id": MarketplaceProductChangeHistory.CHANGE_CATEGORY,
        "platform_category_name": MarketplaceProductChangeHistory.CHANGE_CATEGORY,
    }
    for field_name, new_value in current_values.items():
        old_value = previous_values.get(field_name)
        if str(old_value) == str(new_value):
            continue
        MarketplaceProductChangeHistory.objects.create(
            listing=listing,
            marketplace_account=listing.marketplace_account,
            marketplace=listing.marketplace,
            product=listing.product,
            variant=listing.variant,
            sync_run=sync_run,
            change_type=change_type_by_field.get(field_name, MarketplaceProductChangeHistory.CHANGE_UPDATED),
            field_name=field_name,
            old_value="" if old_value is None else str(old_value)[:255],
            new_value="" if new_value is None else str(new_value)[:255],
        )
