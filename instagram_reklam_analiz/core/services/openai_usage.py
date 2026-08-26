from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.models import AICreditLedger, AIOperationTariff, OpenAITokenUsageLedger
from core.services.entitlements import (
    add_ai_credits,
    consume_ai_credits,
    get_access_subscription,
    get_active_subscription,
    model_table_has_column,
)
from core.models import FeatureUsageLedger
from core.services.usage_metering import UsageResult, consume_usage


@dataclass(frozen=True)
class OpenAIUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


OPENAI_OPERATION_ANALYSIS = FeatureUsageLedger.OP_OPENAI_ANALYSIS
OPENAI_OPERATION_RECOMMENDATION = FeatureUsageLedger.OP_OPENAI_RECOMMENDATION


def _read_usage_value(usage: Any, *names: str) -> int:
    for name in names:
        if usage is None:
            continue
        value = None
        if isinstance(usage, dict):
            value = usage.get(name)
        else:
            value = getattr(usage, name, None)
        if value is not None:
            try:
                return int(value or 0)
            except Exception:
                return 0
    return 0


def extract_openai_usage(response_or_payload: Any) -> OpenAIUsage:
    """Return token usage from OpenAI SDK objects or raw JSON payloads."""
    payload = response_or_payload
    usage = None
    if isinstance(payload, dict):
        usage = payload.get("usage")
    else:
        usage = getattr(payload, "usage", None)

    input_tokens = _read_usage_value(usage, "input_tokens", "prompt_tokens")
    output_tokens = _read_usage_value(usage, "output_tokens", "completion_tokens")
    total_tokens = _read_usage_value(usage, "total_tokens")
    if total_tokens <= 0:
        total_tokens = input_tokens + output_tokens
    return OpenAIUsage(
        input_tokens=max(0, input_tokens),
        output_tokens=max(0, output_tokens),
        total_tokens=max(0, total_tokens),
    )


def _extract_model_name(response_or_payload: Any) -> str:
    if isinstance(response_or_payload, dict):
        value = response_or_payload.get("model")
    else:
        value = getattr(response_or_payload, "model", None)
    return str(value or "")[:120]


def record_openai_token_usage(
    response_or_payload: Any,
    *,
    user=None,
    organization=None,
    reference: str = "",
    note: str = "",
    operation_key: str = "",
    request_id: str = "",
    usage_kind: str = "customer_usage",
    used_at=None,
) -> OpenAIUsage:
    """Record OpenAI response token usage for member ledger only.

    SaaS provider totals are synchronized from the OpenAI organization usage API
    by the sync_openai_usage management command so the admin dashboard matches
    OpenAI's own usage dashboard instead of local estimates.
    """
    usage = extract_openai_usage(response_or_payload)
    if usage.total_tokens <= 0:
        return usage

    if model_table_has_column(OpenAITokenUsageLedger, "total_tokens"):
        OpenAITokenUsageLedger.objects.create(
            user=user,
            organization=organization,
            model_name=_extract_model_name(response_or_payload),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            reference=reference[:120],
            operation_key=operation_key[:120],
            request_id=request_id[:64],
            usage_kind=usage_kind[:40],
            note=note,
            used_at=used_at or timezone.now(),
        )

    return usage


def consume_openai_operation(
    *,
    user,
    operation=OPENAI_OPERATION_ANALYSIS,
    organization=None,
    subscription=None,
    credit_amount=1,
    tariff_key="",
    reference="",
    reason="OpenAI kullanimi",
    metadata=None,
) -> UsageResult:
    if organization is None and subscription is None:
        subscription = get_active_subscription(user)
        if subscription is None:
            subscription = get_access_subscription(user)
            if subscription is not None and subscription.organization_id:
                organization = subscription.organization
    if tariff_key and model_table_has_column(AIOperationTariff, "credit_cost"):
        try:
            tariff = AIOperationTariff.objects.get(key=tariff_key, is_active=True)
        except AIOperationTariff.DoesNotExist:
            return UsageResult(False, "AI islem tarifesi aktif degil.", 0, 0, None, None, subscription, "tariff_unavailable")
        credit_amount = int(tariff.credit_cost or 0)
        metadata = {
            **(metadata or {}),
            "tariff_key": tariff.key,
            "tariff_credits": credit_amount,
            "credit_state": "consumed",
        }

    usage_result = consume_usage(
        user=user,
        organization=organization,
        subscription=subscription,
        operation=operation,
        units=1,
        reference=reference,
        note=reason,
        metadata=metadata,
    )
    if not usage_result.allowed:
        return usage_result

    if credit_amount and credit_amount > 0 and usage_result.code != "duplicate_suppressed":
        credit_result = consume_ai_credits(
            user,
            credit_amount,
            reason=reason,
            organization=organization,
            reference=reference,
        )
        if not credit_result.allowed:
            if usage_result.ledger is not None:
                usage_result.ledger.status = FeatureUsageLedger.STATUS_BLOCKED
                usage_result.ledger.note = credit_result.reason
                usage_result.ledger.metadata = {
                    **(usage_result.ledger.metadata or {}),
                    "credit_state": "blocked",
                    "required_credits": int(credit_result.used or credit_amount or 0),
                    "available_credits": int(credit_result.limit or 0),
                }
                usage_result.ledger.save(update_fields=["status", "note", "metadata"])
            return UsageResult(
                False,
                credit_result.reason,
                credit_result.limit,
                credit_result.used or 0,
                None,
                usage_result.ledger,
                usage_result.subscription,
                "insufficient_ai_credits",
            )

    return usage_result


def refund_ai_tariff_credits(*, user, tariff_key, reason, organization=None, reference=""):
    """Refund a failed tariff-backed AI operation; zero-credit tariffs are ignored."""
    if organization is None:
        subscription = get_active_subscription(user) or get_access_subscription(user)
        if subscription is not None and subscription.organization_id:
            organization = subscription.organization
    if not tariff_key or not model_table_has_column(AIOperationTariff, "credit_cost"):
        return None
    try:
        tariff = AIOperationTariff.objects.get(key=tariff_key)
    except AIOperationTariff.DoesNotExist:
        return None
    amount = int(tariff.credit_cost or 0)
    if amount <= 0:
        return None
    with transaction.atomic():
        user.__class__.objects.select_for_update().get(pk=user.pk)
        consumes = AICreditLedger.objects.filter(
            user=user,
            organization=organization,
            action=AICreditLedger.ACTION_CONSUME,
            amount=-amount,
        )
        if reference:
            consumes = consumes.filter(reference=reference)
        consume = consumes.order_by("-created_at", "-id").first()
        if consume is None:
            return None
        refund_reference = f"refund-ledger:{consume.id}"
        existing = AICreditLedger.objects.filter(
            user=user,
            organization=organization,
            action=AICreditLedger.ACTION_REFUND,
            reference=refund_reference,
        ).first()
        if existing is not None:
            return existing
        refund = add_ai_credits(
            user=user,
            organization=organization,
            amount=amount,
            action=AICreditLedger.ACTION_REFUND,
            reference=refund_reference,
            note=f"Basarisiz AI islemi kredi iadesi: {reason}",
        )
        usage_row = FeatureUsageLedger.objects.filter(
            user=user,
            organization=organization,
            reference=reference,
            status=FeatureUsageLedger.STATUS_ALLOWED,
        ).order_by("-created_at", "-id").first()
        if usage_row is not None:
            usage_row.status = FeatureUsageLedger.STATUS_FAILED
            usage_row.note = f"AI islemi basarisiz; kredi iade edildi: {reason}"
            usage_row.metadata = {**(usage_row.metadata or {}), "credit_state": "refunded"}
            usage_row.save(update_fields=["status", "note", "metadata"])
        return refund
