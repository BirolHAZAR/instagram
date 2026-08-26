from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.models import (
    AICreditLedger,
    Invoice,
    MembershipPlan,
    Organization,
    OrganizationMember,
    Payment,
    PaymentTransaction,
    ReferralReward,
    UserSubscription,
)
from core.services.cache_service import CacheService
from core.services.entitlements import add_ai_credits, get_active_subscription, grant_plan_ai_credits
from core.services.product_research_credits import add_product_research_units
from core.services.referrals import award_referral_for_subscription


def _infer_billing_period(payment):
    period = getattr(payment, "billing_period", "") or ""
    plan = payment.plan
    if not plan:
        return period if period in {UserSubscription.BILLING_MONTHLY, UserSubscription.BILLING_YEARLY} else UserSubscription.BILLING_MONTHLY

    try:
        net_amount = payment.amount - payment.kdv_amount
        monthly_net = plan.price
        if monthly_net and net_amount > monthly_net * 6:
            return UserSubscription.BILLING_YEARLY
    except Exception:
        pass
    if period in {UserSubscription.BILLING_MONTHLY, UserSubscription.BILLING_YEARLY}:
        return period
    return UserSubscription.BILLING_MONTHLY


def _invoice_notes(payment, extra_note=""):
    parts = []
    if extra_note:
        parts.append(extra_note)
    if payment.notes:
        parts.append(payment.notes)
    return "\n".join(part for part in parts if part).strip() or None


def approve_bank_transfer_payment(payment, approved_by=None, note=""):
    if payment.plan_id:
        return approve_bank_transfer_subscription_payment(payment, approved_by=approved_by, note=note)
    return approve_bank_transfer_addon_payment(payment, approved_by=approved_by, note=note)


@transaction.atomic
def approve_bank_transfer_addon_payment(payment, approved_by=None, note=""):
    payment = (
        Payment.objects.select_for_update()
        .get(id=payment.id)
    )
    if not get_active_subscription(payment.user):
        return {"approved": False, "reason": "active_subscription_required"}
    if payment.payment_method != "bank_transfer":
        return {"approved": False, "reason": "not_bank_transfer"}
    if payment.status == "completed":
        return {"approved": False, "reason": "already_completed"}
    if payment.status not in {"pending", ""}:
        return {"approved": False, "reason": f"invalid_status:{payment.status}"}

    if payment.ai_credit_package_id:
        package = payment.ai_credit_package
        reference = f"bank-ai-credit-package:{package.id}:{payment.id}"
        add_ai_credits(
            user=payment.user,
            amount=package.credits,
            action=AICreditLedger.ACTION_PURCHASE,
            package=package,
            reference=reference,
            note=f"{package.display_name} havale/EFT ödemesi onaylandı.",
        )
        description = f"{package.display_name} - AI Kredi Paketi - Havale/EFT onaylandı"
    elif payment.product_research_package_id:
        package = payment.product_research_package
        reference = f"bank-product-research-package:{package.id}:{payment.id}"
        add_product_research_units(
            user=payment.user,
            amount=package.units,
            package=package,
            reference=reference,
            note=f"{package.display_name} havale/EFT ödemesi onaylandı.",
        )
        description = f"{package.display_name} - Ürün Araştırma Paketi - Havale/EFT onaylandı"
    else:
        return {"approved": False, "reason": "missing_purchase_product"}

    payment.status = "completed"
    payment.transaction_id = payment.transaction_id or f"bank-{timezone.now().strftime('%Y%m%d%H%M%S')}-{payment.id}"
    if note:
        payment.notes = ((payment.notes or "") + "\n" + note).strip()
    payment.save(update_fields=["status", "transaction_id", "notes", "updated_at"])

    PaymentTransaction.objects.get_or_create(
        payment=payment,
        transaction_type="payment",
        defaults={
            "user": payment.user,
            "amount": payment.amount,
            "status": "success",
            "reference_id": payment.transaction_id,
            "notes": f"Havale/EFT admin onayı. Onaylayan: {getattr(approved_by, 'email', '') or getattr(approved_by, 'username', '') or '-'}",
        },
    )

    invoice = (
        Invoice.objects.filter(invoice_number__contains=f"-{payment.id}", user=payment.user)
        .order_by("-created_at")
        .first()
    )
    invoice_defaults = {
        "subscription": None,
        "billing_info": payment.billing_info,
        "amount": payment.amount - payment.kdv_amount,
        "kdv_amount": payment.kdv_amount,
        "total_amount": payment.amount,
        "payment_method": "bank_transfer",
        "is_paid": True,
        "payment_date": timezone.now(),
        "due_date": timezone.localdate(),
        "status": "paid",
        "description": description,
        "notes": _invoice_notes(payment, "Havale/EFT ödemesi admin tarafından onaylandı."),
    }
    if invoice:
        for field, value in invoice_defaults.items():
            setattr(invoice, field, value)
        invoice.save(update_fields=[*invoice_defaults.keys(), "updated_at"])
    else:
        invoice = Invoice.objects.create(
            user=payment.user,
            invoice_number=f"INV-{timezone.now().strftime('%Y%m%d')}-{payment.user_id}-{payment.id}",
            **invoice_defaults,
        )

    return {"approved": True, "payment_id": payment.id, "invoice_id": invoice.id, "purchase_type": "addon"}


@transaction.atomic
def approve_bank_transfer_subscription_payment(payment, approved_by=None, note=""):
    payment = (
        Payment.objects.select_for_update()
        .get(id=payment.id)
    )

    if payment.payment_method != "bank_transfer":
        return {"approved": False, "reason": "not_bank_transfer"}
    if not payment.plan_id:
        return {"approved": False, "reason": "not_subscription_payment"}
    if payment.status == "completed":
        return {"approved": False, "reason": "already_completed"}
    if payment.status not in {"pending", ""}:
        return {"approved": False, "reason": f"invalid_status:{payment.status}"}

    billing_period = _infer_billing_period(payment)
    today = timezone.localdate()
    duration = timedelta(days=365) if billing_period == UserSubscription.BILLING_YEARLY else timedelta(days=30)
    plan = payment.plan

    organization = None
    if getattr(plan, "plan_type", "") == MembershipPlan.PLAN_TYPE_AGENCY:
        agency_name = (
            getattr(payment.billing_info, "company_name", "") or
            f"{payment.user.get_full_name() or payment.user.email} Ajansi"
        ).strip()
        organization, _ = Organization.objects.update_or_create(
            owner=payment.user,
            name=agency_name,
            defaults={
                "active_plan": plan,
                "is_active": True,
                "report_brand_name": agency_name,
            },
        )
        OrganizationMember.objects.update_or_create(
            organization=organization,
            user=payment.user,
            defaults={
                "role": OrganizationMember.ROLE_OWNER,
                "is_active": True,
                "invited_email": payment.user.email or "",
            },
        )
        CacheService.bump_version("agency_dashboard", organization.id)

    subscription, _ = UserSubscription.objects.update_or_create(
        user=payment.user,
        organization=organization,
        defaults={
            "plan": plan,
            "start_date": today,
            "end_date": today + duration,
            "billing_period": billing_period,
            "auto_renew": True,
            "next_renewal_date": today + duration,
            "is_active": True,
        },
    )
    grant_plan_ai_credits(subscription)

    payment.status = "completed"
    payment.transaction_id = payment.transaction_id or f"bank-{timezone.now().strftime('%Y%m%d%H%M%S')}-{payment.id}"
    payment.billing_period = billing_period
    if note:
        payment.notes = ((payment.notes or "") + "\n" + note).strip()
    payment.save(update_fields=["status", "transaction_id", "billing_period", "notes", "updated_at"])

    PaymentTransaction.objects.get_or_create(
        payment=payment,
        transaction_type="payment",
        defaults={
            "user": payment.user,
            "amount": payment.amount,
            "status": "success",
            "reference_id": payment.transaction_id,
            "notes": f"Havale/EFT admin onayi. Onaylayan: {getattr(approved_by, 'email', '') or getattr(approved_by, 'username', '') or '-'}",
        },
    )

    invoice = (
        Invoice.objects.filter(user=payment.user, billing_info=payment.billing_info, payment_method="bank_transfer")
        .filter(invoice_number__contains=f"-{payment.id}")
        .order_by("-created_at")
        .first()
    )
    invoice_defaults = {
        "subscription": subscription,
        "billing_info": payment.billing_info,
        "amount": payment.amount - payment.kdv_amount,
        "kdv_amount": payment.kdv_amount,
        "total_amount": payment.amount,
        "payment_method": "bank_transfer",
        "is_paid": True,
        "payment_date": timezone.now(),
        "due_date": today,
        "status": "paid",
        "description": f"{plan.display_name} - {'Yillik' if billing_period == UserSubscription.BILLING_YEARLY else 'Aylik'} Abonelik - Havale/EFT onaylandi",
        "notes": _invoice_notes(payment, "Havale/EFT odemesi admin tarafindan onaylandi."),
    }
    if invoice:
        for field, value in invoice_defaults.items():
            setattr(invoice, field, value)
        invoice.save(update_fields=[*invoice_defaults.keys(), "updated_at"])
    else:
        invoice = Invoice.objects.create(
            user=payment.user,
            invoice_number=f"INV-{timezone.now().strftime('%Y%m%d')}-{payment.user.id}-{payment.id}",
            **invoice_defaults,
        )

    pending_reward = ReferralReward.objects.filter(payment=payment).select_related("referral_code").first()
    referral_result = None
    if pending_reward:
        referral_result = award_referral_for_subscription(
            code=pending_reward.referral_code.code,
            referred_user=payment.user,
            subscription=subscription,
            payment=payment,
            reward_type=pending_reward.reward_type,
            reward_amount=pending_reward.reward_amount,
        )

    return {
        "approved": True,
        "payment_id": payment.id,
        "subscription_id": subscription.id,
        "invoice_id": invoice.id,
        "referral_result": referral_result,
    }
