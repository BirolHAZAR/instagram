from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.models import BillingInfo, Invoice, Payment, PaymentTransaction, UserSubscription
from core.services.entitlements import grant_plan_ai_credits


def renewal_period_delta(subscription):
    if subscription.billing_period == UserSubscription.BILLING_YEARLY:
        return timedelta(days=365)
    return timedelta(days=30)


def renewal_base_amount(subscription):
    plan = subscription.plan
    if subscription.billing_period == UserSubscription.BILLING_YEARLY:
        return plan.yearly_price
    return plan.price


def due_auto_renewal_subscriptions(today=None):
    today = today or timezone.localdate()
    return (
        UserSubscription.objects
        .select_related("user", "plan", "organization", "default_payment_method")
        .filter(
            is_active=True,
            auto_renew=True,
            next_renewal_date__lte=today,
            plan__isnull=False,
            default_payment_method__isnull=False,
            default_payment_method__is_active=True,
        )
    )


@transaction.atomic
def renew_subscription(subscription):
    subscription = (
        UserSubscription.objects
        .select_for_update()
        .select_related("user", "plan", "organization", "default_payment_method")
        .get(id=subscription.id)
    )
    if not subscription.auto_renew or not subscription.default_payment_method or not subscription.plan:
        return {"success": False, "reason": "renewal_not_available", "subscription_id": subscription.id}

    base_amount = renewal_base_amount(subscription)
    kdv_amount = base_amount * Decimal("0.20")
    total_amount = base_amount + kdv_amount
    payment_method = subscription.default_payment_method

    payment = Payment.objects.create(
        user=subscription.user,
        plan=subscription.plan,
        billing_info=None,
        amount=total_amount,
        kdv_amount=kdv_amount,
        payment_method="credit_card",
        status="completed",
        transaction_id=f"auto-{timezone.now().strftime('%Y%m%d%H%M%S')}-{subscription.id}",
        notes=f"Otomatik yenileme: {subscription.plan.display_name} ({subscription.billing_period}) - {payment_method.card_brand} **** {payment_method.last4}",
    )
    PaymentTransaction.objects.create(
        user=subscription.user,
        payment=payment,
        transaction_type="payment",
        amount=total_amount,
        status="success",
        reference_id=payment.transaction_id,
        response_data={"provider": payment_method.provider, "last4": payment_method.last4, "auto_renew": True},
        notes="Otomatik yenileme tahsilatı başarılı.",
    )

    old_end = subscription.end_date
    delta = renewal_period_delta(subscription)
    subscription.start_date = old_end
    subscription.end_date = old_end + delta
    subscription.next_renewal_date = subscription.end_date
    subscription.last_renewed_at = timezone.now()
    subscription.save(update_fields=["start_date", "end_date", "next_renewal_date", "last_renewed_at", "updated_at"])
    grant_plan_ai_credits(subscription)

    Invoice.objects.create(
        user=subscription.user,
        subscription=subscription,
        billing_info=BillingInfo.objects.filter(user=subscription.user).order_by("-created_at").first(),
        invoice_number=f"INV-{timezone.now().strftime('%Y%m%d')}-{subscription.user_id}-{payment.id}",
        amount=base_amount,
        kdv_amount=kdv_amount,
        total_amount=total_amount,
        payment_method="credit_card",
        is_paid=True,
        payment_date=timezone.now(),
        due_date=timezone.localdate(),
        status="paid",
        description=f"{subscription.plan.display_name} - Otomatik {'Yıllık' if subscription.billing_period == UserSubscription.BILLING_YEARLY else 'Aylık'} Yenileme",
    )
    return {"success": True, "subscription_id": subscription.id, "payment_id": payment.id}


def process_due_auto_renewals(limit=100):
    results = []
    for subscription in due_auto_renewal_subscriptions()[:limit]:
        try:
            results.append(renew_subscription(subscription))
        except Exception as exc:
            results.append({"success": False, "subscription_id": subscription.id, "reason": str(exc)})
    return results
