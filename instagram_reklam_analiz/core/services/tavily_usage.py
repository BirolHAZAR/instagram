from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core.models import TavilyAPIPool, TavilyAPIUsageLedger
from core.services.rate_limit import check_rate_limit


@dataclass(frozen=True)
class TavilyReservation:
    allowed: bool
    pool: TavilyAPIPool | None = None
    ledger: TavilyAPIUsageLedger | None = None
    reason: str = ""
    code: str = ""
    retry_after: int = 0


def current_month_start():
    today = timezone.localdate()
    return today.replace(day=1)


def get_current_tavily_pool() -> TavilyAPIPool:
    monthly_limit = int(getattr(settings, "TAVILY_MONTHLY_LIMIT", 1000) or 1000)
    rate_limit = str(getattr(settings, "TAVILY_RATE_LIMIT", "100/m") or "100/m")
    pool, created = TavilyAPIPool.objects.get_or_create(
        month=current_month_start(),
        defaults={
            "monthly_limit": monthly_limit,
            "rate_limit": rate_limit,
            "provider_name": "Tavily",
        },
    )
    updates = []
    if not pool.provider_name:
        pool.provider_name = "Tavily"
        updates.append("provider_name")
    if not pool.rate_limit:
        pool.rate_limit = rate_limit
        updates.append("rate_limit")
    if created is False and updates:
        pool.save(update_fields=[*updates, "updated_at"])
    return pool


def reserve_tavily_request(*, query: str = "", reference: str = "") -> TavilyReservation:
    pool = get_current_tavily_pool()
    rate = check_rate_limit(
        namespace="tavily_api",
        identity="account:default",
        rate=pool.rate_limit or getattr(settings, "TAVILY_RATE_LIMIT", "100/m"),
    )
    if not rate.allowed:
        ledger = TavilyAPIUsageLedger.objects.create(
            pool=pool,
            status=TavilyAPIUsageLedger.STATUS_BLOCKED,
            amount=0,
            balance_after=pool.remaining_requests,
            query=query[:2000],
            reference=reference[:160],
            error_message=f"Rate limit asildi: {pool.rate_limit}. {rate.retry_after} sn sonra tekrar denenebilir.",
        )
        return TavilyReservation(
            allowed=False,
            pool=pool,
            ledger=ledger,
            reason="Tavily API rate limit asildi. Bir dakika icinde en fazla 100 istek yapilabilir.",
            code="tavily_rate_limited",
            retry_after=rate.retry_after,
        )

    with transaction.atomic():
        locked_pool = TavilyAPIPool.objects.select_for_update().get(pk=pool.pk)
        if locked_pool.used_requests >= locked_pool.monthly_limit:
            ledger = TavilyAPIUsageLedger.objects.create(
                pool=locked_pool,
                status=TavilyAPIUsageLedger.STATUS_BLOCKED,
                amount=0,
                balance_after=locked_pool.remaining_requests,
                query=query[:2000],
                reference=reference[:160],
                error_message="Aylik Tavily API hakki doldu.",
            )
            return TavilyReservation(
                allowed=False,
                pool=locked_pool,
                ledger=ledger,
                reason="Aylik Tavily API hakki doldu. Admin panelden yeni hak tanimlayin veya ay yenilenmesini bekleyin.",
                code="tavily_monthly_quota_exhausted",
            )

        locked_pool.used_requests = F("used_requests") + 1
        locked_pool.save(update_fields=["used_requests", "updated_at"])
        locked_pool.refresh_from_db(fields=["used_requests", "monthly_limit", "month", "rate_limit"])
        ledger = TavilyAPIUsageLedger.objects.create(
            pool=locked_pool,
            status=TavilyAPIUsageLedger.STATUS_ALLOWED,
            amount=-1,
            balance_after=locked_pool.remaining_requests,
            query=query[:2000],
            reference=reference[:160],
        )
        return TavilyReservation(True, locked_pool, ledger)


def mark_tavily_request_result(
    reservation: TavilyReservation | None,
    *,
    response_status: int | None = None,
    error_message: str = "",
) -> None:
    if reservation is None or reservation.ledger is None:
        return
    ledger = reservation.ledger
    update_fields = ["response_status", "error_message"]
    ledger.response_status = response_status
    ledger.error_message = error_message[:2000]
    if error_message:
        ledger.status = TavilyAPIUsageLedger.STATUS_FAILED
        update_fields.append("status")
    ledger.save(update_fields=update_fields)
