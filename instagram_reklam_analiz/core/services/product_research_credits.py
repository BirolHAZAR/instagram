from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from core.models import ProductResearchLedger, UserProductResearchBalance
from core.services.entitlements import get_active_subscription


def _active_subscription(user, organization=None):
    return get_active_subscription(user, organization=organization) or (
        get_active_subscription(user) if organization is not None else None
    )


@dataclass(frozen=True)
class ProductResearchCreditResult:
    allowed: bool
    reason: str = ""
    balance: UserProductResearchBalance | None = None
    ledger: ProductResearchLedger | None = None


def current_cycle(today=None):
    start = (today or timezone.localdate()).replace(day=1)
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    return start, next_month - timezone.timedelta(days=1)


def get_product_research_balance(user, organization=None, today=None):
    cycle_start, cycle_end = current_cycle(today)
    balance, _ = UserProductResearchBalance.objects.get_or_create(
        user=user,
        organization=organization,
        cycle_start=cycle_start,
        defaults={"cycle_end": cycle_end},
    )
    if balance.cycle_end != cycle_end:
        balance.cycle_end = cycle_end
        balance.save(update_fields=["cycle_end", "updated_at"])
    return balance


@transaction.atomic
def add_product_research_units(*, user, amount, organization=None, package=None, reference="", note=""):
    amount = int(amount or 0)
    if not _active_subscription(user, organization=organization):
        raise ValueError("Ürün araştırma paketi için aktif deneme veya abonelik gerekli.")
    if amount <= 0:
        raise ValueError("Eklenecek ürün araştırma hakkı pozitif olmalı.")
    balance = get_product_research_balance(user, organization=organization)
    balance.purchased_units = int(balance.purchased_units or 0) + amount
    balance.current_balance = int(balance.current_balance or 0) + amount
    balance.save(update_fields=["purchased_units", "current_balance", "updated_at"])
    ledger = ProductResearchLedger.objects.create(
        user=user,
        organization=organization,
        package=package,
        cycle_start=balance.cycle_start,
        cycle_end=balance.cycle_end,
        action=ProductResearchLedger.ACTION_PURCHASE,
        amount=amount,
        balance_after=balance.current_balance,
        reference=reference[:120],
        note=note,
    )
    return ProductResearchCreditResult(True, balance=balance, ledger=ledger)


@transaction.atomic
def consume_product_research_units(*, user, amount=1, organization=None, reference="", note=""):
    amount = int(amount or 1)
    if not _active_subscription(user, organization=organization):
        return ProductResearchCreditResult(False, "Aktif deneme veya abonelik bulunamadı.")
    if amount <= 0:
        raise ValueError("Kullanılacak ürün araştırma hakkı pozitif olmalı.")
    balance = get_product_research_balance(user, organization=organization)
    if int(balance.current_balance or 0) < amount:
        return ProductResearchCreditResult(False, "Aylık ek ürün araştırma hakkı yetersiz.", balance=balance)
    balance.used_units = int(balance.used_units or 0) + amount
    balance.current_balance = int(balance.current_balance or 0) - amount
    balance.save(update_fields=["used_units", "current_balance", "updated_at"])
    ledger = ProductResearchLedger.objects.create(
        user=user,
        organization=organization,
        cycle_start=balance.cycle_start,
        cycle_end=balance.cycle_end,
        action=ProductResearchLedger.ACTION_CONSUME,
        amount=-amount,
        balance_after=balance.current_balance,
        reference=reference[:120],
        note=note,
    )
    return ProductResearchCreditResult(True, balance=balance, ledger=ledger)


@transaction.atomic
def refund_product_research_units(*, user, amount=1, organization=None, reference="", note=""):
    """Başarısız sağlayıcı işlemi için daha önce tüketilen ek hakkı iade eder."""
    amount = int(amount or 1)
    if amount <= 0:
        raise ValueError("İade edilecek ürün araştırma hakkı pozitif olmalı.")
    balance = get_product_research_balance(user, organization=organization)
    refundable = min(amount, int(balance.used_units or 0))
    if refundable <= 0:
        return ProductResearchCreditResult(False, "İade edilebilir kullanılmış hak bulunamadı.", balance=balance)
    balance.used_units = int(balance.used_units or 0) - refundable
    balance.current_balance = int(balance.current_balance or 0) + refundable
    balance.save(update_fields=["used_units", "current_balance", "updated_at"])
    ledger = ProductResearchLedger.objects.create(
        user=user,
        organization=organization,
        cycle_start=balance.cycle_start,
        cycle_end=balance.cycle_end,
        action=ProductResearchLedger.ACTION_REFUND,
        amount=refundable,
        balance_after=balance.current_balance,
        reference=reference[:120],
        note=note,
    )
    return ProductResearchCreditResult(True, balance=balance, ledger=ledger)
