from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.models import FeatureUsageLedger
from core.services.entitlements import get_access_subscription, get_active_subscription, get_limit, is_unlimited
from core.services.product_research_credits import consume_product_research_units, refund_product_research_units


OPERATION_LIMITS = {
    FeatureUsageLedger.OP_OPENAI_ANALYSIS: {
        "monthly": "ai_analysis",
        "weekly": "ai_analysis_weekly",
        "label": "AI analiz",
    },
    FeatureUsageLedger.OP_OPENAI_RECOMMENDATION: {
        "monthly": "ai_recommendation",
        "weekly": "ai_recommendation_weekly",
        "label": "AI öneri/yorum",
    },
    FeatureUsageLedger.OP_MARKETPLACE_PRODUCT_RESEARCH: {
        "monthly": "marketplace_product_research",
        "weekly": None,
        "label": "ürün araştırma",
    },
    FeatureUsageLedger.OP_MARKETPLACE_PRICE_CHECK: {
        "monthly": "marketplace_price_check",
        "weekly": None,
        "label": "fiyat kontrol",
    },
}


@dataclass(frozen=True)
class UsageResult:
    allowed: bool
    reason: str = ""
    limit: int | None = None
    used: int = 0
    remaining: int | None = None
    ledger: FeatureUsageLedger | None = None
    subscription: object | None = None
    code: str = ""


def month_start():
    today = timezone.localdate()
    return today.replace(day=1)


def week_start():
    today = timezone.localdate()
    return today - timezone.timedelta(days=today.weekday())


def usage_count(user, operation, *, organization=None, since=None, status=FeatureUsageLedger.STATUS_ALLOWED):
    qs = FeatureUsageLedger.objects.filter(user=user, operation=operation, status=status)
    if organization is not None:
        qs = qs.filter(organization=organization)
    if since is not None:
        qs = qs.filter(created_at__date__gte=since)
    return sum(row.units for row in qs.only("units"))


def record_usage(
    *,
    user,
    operation,
    organization=None,
    subscription=None,
    status=FeatureUsageLedger.STATUS_ALLOWED,
    units=1,
    provider_units=0,
    estimated_cost=Decimal("0.0000"),
    reference="",
    note="",
    metadata=None,
):
    return FeatureUsageLedger.objects.create(
        user=user,
        organization=organization,
        subscription=subscription,
        operation=operation,
        status=status,
        units=max(1, int(units or 1)),
        provider_units=max(0, int(provider_units or 0)),
        estimated_cost=estimated_cost or Decimal("0.0000"),
        reference=(reference or "")[:160],
        note=note or "",
        metadata=metadata or {},
    )


def check_usage_allowed(user, operation, *, organization=None, units=1):
    config = OPERATION_LIMITS.get(operation)
    if not config:
        return UsageResult(False, f"Bilinmeyen kullanım türü: {operation}", code="unknown_operation")

    subscription = get_active_subscription(user, organization=organization)
    if not subscription:
        return UsageResult(False, "Bu işlem için aktif paket gerekli.", code="subscription_required")

    monthly_limit = get_limit(user, config["monthly"], organization=organization)
    if monthly_limit is not None and not is_unlimited(monthly_limit):
        used_month = usage_count(user, operation, organization=organization, since=month_start())
        if used_month + units > monthly_limit:
            return UsageResult(
                False,
                f"Bu paket aylık {monthly_limit} {config['label']} hakkı içeriyor. Aylık limit doldu.",
                limit=monthly_limit,
                used=used_month,
                remaining=max(0, monthly_limit - used_month),
                code="monthly_limit_reached",
            )

    weekly_key = config.get("weekly")
    if weekly_key:
        weekly_limit = get_limit(user, weekly_key, organization=organization)
        if weekly_limit is not None and not is_unlimited(weekly_limit) and weekly_limit > 0:
            used_week = usage_count(user, operation, organization=organization, since=week_start())
            if used_week + units > weekly_limit:
                return UsageResult(
                    False,
                    f"Bu paket haftalık {weekly_limit} {config['label']} hakkı içeriyor. Haftalık limit doldu.",
                    limit=weekly_limit,
                    used=used_week,
                    remaining=max(0, weekly_limit - used_week),
                    code="weekly_limit_reached",
                )

    return UsageResult(True, subscription=subscription)


def consume_usage(
    *,
    user,
    operation,
    organization=None,
    subscription=None,
    units=1,
    provider_units=0,
    estimated_cost=Decimal("0.0000"),
    reference="",
    note="",
    metadata=None,
):
    """Sayaç tüketimini atomik ve kısa süreli tekrar çağrılara karşı güvenli yapar."""
    if organization is None and subscription is None:
        subscription = get_active_subscription(user)
        if subscription is None:
            subscription = get_access_subscription(user)
            if subscription is not None and subscription.organization_id:
                organization = subscription.organization
    with transaction.atomic():
        user.__class__.objects.select_for_update().get(pk=user.pk)
        if reference:
            duplicate = (
                FeatureUsageLedger.objects.filter(
                    user=user,
                    organization=organization,
                    operation=operation,
                    status=FeatureUsageLedger.STATUS_ALLOWED,
                    reference=reference[:160],
                    created_at__gte=timezone.now() - timezone.timedelta(seconds=10),
                )
                .order_by("-created_at", "-id")
                .first()
            )
            if duplicate is not None:
                return UsageResult(
                    True,
                    "Aynı işlem kısa süre önce sayıldı; yeniden sayaç düşülmedi.",
                    ledger=None,
                    subscription=duplicate.subscription,
                    code="duplicate_suppressed",
                )
        return _consume_usage_locked(
            user=user,
            operation=operation,
            organization=organization,
            subscription=subscription,
            units=units,
            provider_units=provider_units,
            estimated_cost=estimated_cost,
            reference=reference,
            note=note,
            metadata=metadata,
        )


def _consume_usage_locked(
    *,
    user,
    operation,
    organization=None,
    subscription=None,
    units=1,
    provider_units=0,
    estimated_cost=Decimal("0.0000"),
    reference="",
    note="",
    metadata=None,
):
    result = check_usage_allowed(user, operation, organization=organization, units=units)
    if not result.allowed:
        if (
            operation == FeatureUsageLedger.OP_MARKETPLACE_PRODUCT_RESEARCH
            and result.code == "monthly_limit_reached"
        ):
            extra_result = consume_product_research_units(
                user=user,
                organization=organization,
                amount=units,
                reference=reference,
                note="Plan limiti dolduktan sonra ek ürün araştırma bakiyesinden düşüldü.",
            )
            if extra_result.allowed:
                subscription = subscription or result.subscription or get_active_subscription(user, organization=organization)
                ledger = record_usage(
                    user=user,
                    organization=organization,
                    subscription=subscription,
                    operation=operation,
                    status=FeatureUsageLedger.STATUS_ALLOWED,
                    units=units,
                    provider_units=provider_units,
                    estimated_cost=estimated_cost,
                    reference=reference,
                    note=note or "Ek ürün araştırma bakiyesi kullanıldı.",
                    metadata={**(metadata or {}), "source": "purchased_product_research"},
                )
                return UsageResult(True, ledger=ledger, subscription=subscription)

        ledger = record_usage(
            user=user,
            organization=organization,
            subscription=subscription,
            operation=operation,
            status=FeatureUsageLedger.STATUS_BLOCKED,
            units=units,
            reference=reference,
            note=result.reason,
            metadata={
                **(metadata or {}),
                "limit_code": result.code,
                "limit": result.limit,
                "used": result.used,
                "remaining": result.remaining,
            },
        )
        return UsageResult(False, result.reason, result.limit, result.used, result.remaining, ledger, result.subscription, result.code)

    subscription = subscription or result.subscription or get_active_subscription(user, organization=organization)
    ledger = record_usage(
        user=user,
        organization=organization,
        subscription=subscription,
        operation=operation,
        status=FeatureUsageLedger.STATUS_ALLOWED,
        units=units,
        provider_units=provider_units,
        estimated_cost=estimated_cost,
        reference=reference,
        note=note,
        metadata=metadata,
    )
    return UsageResult(True, ledger=ledger, subscription=subscription)


def record_usage_failure(
    *, user, operation, organization=None, subscription=None, reference="", note="",
    metadata=None, usage_ledger=None,
):
    if usage_ledger is not None:
        original_metadata = dict(usage_ledger.metadata or {})
        if (
            operation == FeatureUsageLedger.OP_MARKETPLACE_PRODUCT_RESEARCH
            and original_metadata.get("source") == "purchased_product_research"
        ):
            refund_product_research_units(
                user=user,
                organization=organization,
                amount=usage_ledger.units,
                reference=reference,
                note="Başarısız ürün araştırması için otomatik hak iadesi.",
            )
        usage_ledger.status = FeatureUsageLedger.STATUS_FAILED
        usage_ledger.reference = (reference or usage_ledger.reference)[:160]
        usage_ledger.note = note or usage_ledger.note
        usage_ledger.metadata = {**original_metadata, **(metadata or {}), "refunded_after_failure": True}
        usage_ledger.save(update_fields=["status", "reference", "note", "metadata"])
        return usage_ledger
    return record_usage(
        user=user,
        organization=organization,
        subscription=subscription,
        operation=operation,
        status=FeatureUsageLedger.STATUS_FAILED,
        reference=reference,
        note=note,
        metadata=metadata,
    )
