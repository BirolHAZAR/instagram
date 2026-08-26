from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
import secrets
import string

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from core.models import AICreditLedger, Payment, ReferralCode, ReferralProgramRule, ReferralProgramSetting, ReferralReward, User
from core.services.entitlements import add_ai_credits, get_ai_credit_balance, refresh_ai_credit_balance


def referral_program_enabled():
    if not bool(getattr(settings, "REFERRAL_PROGRAM_ENABLED", True)):
        return False
    try:
        if ReferralProgramSetting._meta.db_table not in connection.introspection.table_names():
            return True
        return ReferralProgramSetting.current().is_enabled
    except Exception:
        return True


def referral_program_settings():
    try:
        if ReferralProgramSetting._meta.db_table not in connection.introspection.table_names():
            return None
        return ReferralProgramSetting.current()
    except Exception:
        return None


def normalize_referral_code(value):
    return (value or "").strip().upper()


def _short_suffix(length=4):
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def build_user_referral_code(user):
    return f"RA-{user.id}-{_short_suffix()}"


def ensure_user_referral_code(user, *, reward_type=ReferralCode.REWARD_AI_CREDITS, reward_amount=10000):
    if not referral_program_enabled():
        return None, False
    program_settings = referral_program_settings()
    if program_settings:
        reward_type = program_settings.default_reward_type
        reward_amount = program_settings.default_reward_amount
    existing = ReferralCode.objects.filter(owner=user).order_by("-is_active", "-created_at").first()
    if existing:
        return existing, False
    for _ in range(10):
        code = build_user_referral_code(user)
        if not ReferralCode.objects.filter(code=code).exists():
            return ReferralCode.objects.create(
                owner=user,
                code=code,
                reward_type=reward_type,
                reward_amount=reward_amount,
                description="Otomatik oluşturulan üye referans kodu.",
            ), True
    return ReferralCode.objects.create(
        owner=user,
        reward_type=reward_type,
        reward_amount=reward_amount,
        description="Otomatik oluşturulan üye referans kodu.",
    ), True


def ensure_referral_codes_for_all_users(*, only_active=True, reward_amount=10000):
    if not referral_program_enabled():
        return {"enabled": False, "created": 0, "existing": 0, "checked": 0}
    qs = User.objects.all().order_by("id")
    if only_active:
        qs = qs.filter(is_active=True)
    created = 0
    existing = 0
    checked = 0
    for user in qs.iterator():
        _, was_created = ensure_user_referral_code(user, reward_amount=reward_amount)
        checked += 1
        if was_created:
            created += 1
        else:
            existing += 1
    return {"enabled": True, "created": created, "existing": existing, "checked": checked}


def get_usable_referral_code(code, user=None):
    if not referral_program_enabled():
        return None, "Referans/promosyon sistemi şu anda kapalı."
    code = normalize_referral_code(code)
    if not code:
        return None, ""
    referral_code = ReferralCode.objects.filter(code=code).select_related("owner").first()
    if referral_code is None:
        return None, "Promosyon kodu bulunamadı."
    usable, reason = referral_code.can_be_used(by_user=user)
    if not usable:
        return None, reason
    return referral_code, ""


def _clean_identity(value):
    return (value or "").strip()


def _money(value):
    return Decimal(value or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _positive_percent(value):
    value = Decimal(value or 0)
    if value < 0:
        return Decimal("0")
    if value > 100:
        return Decimal("100")
    return value


def _paid_subscription_payment_filter():
    return Q(status="completed", plan__isnull=False)


def _identity_used_in_completed_payment(*, user=None, email="", phone="", tax_number="", tc_kimlik=""):
    qs = Payment.objects.filter(_paid_subscription_payment_filter()).select_related("billing_info")
    identity_filter = Q()
    email = _clean_identity(email).lower()
    phone = _clean_identity(phone)
    tax_number = _clean_identity(tax_number)
    tc_kimlik = _clean_identity(tc_kimlik)
    if user is not None:
        identity_filter |= Q(user=user)
    if email:
        identity_filter |= Q(user__email__iexact=email) | Q(billing_info__email__iexact=email)
    if phone:
        identity_filter |= Q(billing_info__phone=phone)
    if tax_number:
        identity_filter |= Q(billing_info__tax_number=tax_number)
    if tc_kimlik:
        identity_filter |= Q(billing_info__tc_kimlik=tc_kimlik)
    if not identity_filter:
        return False, ""
    match = qs.filter(identity_filter).order_by("-created_at").first()
    if not match:
        return False, ""
    if user is not None and match.user_id == user.id:
        return True, "Bu üyelik hesabı daha önce ödeme yaptığı için promosyon kodu tekrar kullanılamaz."
    if email and ((match.user.email or "").lower() == email or (getattr(match.billing_info, "email", "") or "").lower() == email):
        return True, "Bu e-posta ile daha önce ödeme yapıldığı için promosyon kodu kullanılamaz."
    if phone and getattr(match.billing_info, "phone", "") == phone:
        return True, "Bu telefon numarası ile daha önce ödeme yapıldığı için promosyon kodu kullanılamaz."
    if tax_number and getattr(match.billing_info, "tax_number", "") == tax_number:
        return True, "Bu vergi numarası ile daha önce ödeme yapıldığı için promosyon kodu kullanılamaz."
    if tc_kimlik and getattr(match.billing_info, "tc_kimlik", "") == tc_kimlik:
        return True, "Bu TC kimlik numarası ile daha önce ödeme yapıldığı için promosyon kodu kullanılamaz."
    return True, "Bu bilgilerle daha önce ödeme yapıldığı için promosyon kodu kullanılamaz."


def validate_referral_for_checkout(code, *, user, email="", phone="", tax_number="", tc_kimlik=""):
    referral_code, reason = get_usable_referral_code(code, user)
    if referral_code is None:
        return None, reason
    used, used_reason = _identity_used_in_completed_payment(
        user=user,
        email=email,
        phone=phone,
        tax_number=tax_number,
        tc_kimlik=tc_kimlik,
    )
    if used:
        return None, used_reason
    if ReferralReward.objects.filter(referral_code=referral_code, referred_user=user).exists():
        return None, "Bu promosyon kodu bu kullanıcı tarafından daha önce kullanılmış."
    return referral_code, ""


def referral_checkout_benefits(*, plan, billing_period, base_amount):
    rule = referral_rule_for_checkout(plan=plan, billing_period=billing_period)
    if rule:
        discount_percent = _positive_percent(rule.new_customer_discount_percent)
        return {
            "discount_percent": discount_percent,
            "discount_amount": _money(Decimal(base_amount or 0) * discount_percent / Decimal("100")),
            "reward_type": rule.reward_type,
            "reward_amount": int(rule.reward_amount or 0),
            "rule": rule,
        }
    program_settings = referral_program_settings()
    discount_percent = _positive_percent(getattr(program_settings, "new_customer_discount_percent", Decimal("0")) if program_settings else Decimal("0"))
    discount_amount = _money(Decimal(base_amount or 0) * discount_percent / Decimal("100"))
    return {
        "discount_percent": discount_percent,
        "discount_amount": discount_amount,
        "reward_type": getattr(program_settings, "default_reward_type", ReferralCode.REWARD_AI_CREDITS) if program_settings else ReferralCode.REWARD_AI_CREDITS,
        "reward_amount": int(getattr(program_settings, "default_reward_amount", 0) if program_settings else 0),
        "rule": None,
    }


def referral_rule_for_checkout(*, plan, billing_period):
    if not referral_program_enabled():
        return None
    plan_type = getattr(plan, "plan_type", "") or ReferralProgramRule.PLAN_ANY
    candidates = list(
        ReferralProgramRule.objects.filter(is_active=True)
        .filter(plan_type__in=[ReferralProgramRule.PLAN_ANY, plan_type])
        .filter(billing_period__in=[ReferralProgramRule.BILLING_ANY, billing_period])
        .order_by("priority", "id")
    )
    scored = [
        (rule.specificity_score(plan_type, billing_period), rule.priority, rule.id, rule)
        for rule in candidates
    ]
    scored = [item for item in scored if item[0] >= 0]
    if not scored:
        return None
    return sorted(scored, key=lambda item: (-item[0], item[1], item[2]))[0][3]


def _validate_award_context(*, referred_user, subscription, payment=None):
    if subscription is None or not getattr(subscription, "is_active", False):
        return False, "Promosyon kodu sadece aktif abonelik satın alımında çalışır."
    if getattr(subscription, "user_id", None) != getattr(referred_user, "id", None):
        return False, "Abonelik ile promosyon kodunu kullanan kullanıcı eşleşmiyor."
    if getattr(subscription, "end_date", None) and subscription.end_date < timezone.localdate():
        return False, "Promosyon kodu süresi dolmuş abonelik için çalışmaz."
    if payment is not None:
        if getattr(payment, "status", "") != "completed":
            return False, "Promosyon ödülü sadece başarılı ödeme sonrası tanımlanır."
        if getattr(payment, "plan_id", None) is None:
            return False, "Promosyon kodu sadece abonelik ödemelerinde çalışır."
    return True, ""


@transaction.atomic
def record_pending_referral(*, code, referred_user, payment=None, note="", reward_type=None, reward_amount=None):
    referral_code, reason = get_usable_referral_code(code, referred_user)
    if referral_code is None:
        return {"recorded": False, "reason": reason or "invalid_code"}
    reward, created = ReferralReward.objects.get_or_create(
        referral_code=referral_code,
        referred_user=referred_user,
        defaults={
            "referrer": referral_code.owner,
            "payment": payment,
            "reward_type": reward_type or referral_code.reward_type,
            "reward_amount": int(reward_amount if reward_amount is not None else referral_code.reward_amount),
            "status": ReferralReward.STATUS_PENDING,
            "note": note or f"{referred_user.email} için bekleyen referans kaydı.",
        },
    )
    if not created and payment and not reward.payment_id:
        reward.payment = payment
        reward.save(update_fields=["payment", "updated_at"])
    return {"recorded": True, "created": created, "reward_id": reward.id, "code": referral_code.code}


@transaction.atomic
def award_referral_for_subscription(*, code, referred_user, subscription, payment=None, reward_type=None, reward_amount=None):
    referral_code, reason = get_usable_referral_code(code, referred_user)
    if referral_code is None:
        return {"awarded": False, "reason": reason or "invalid_code"}
    valid_context, context_reason = _validate_award_context(
        referred_user=referred_user,
        subscription=subscription,
        payment=payment,
    )
    if not valid_context:
        return {"awarded": False, "reason": context_reason}

    existing = ReferralReward.objects.filter(
        referral_code=referral_code,
        referred_user=referred_user,
    ).first()
    if existing:
        if existing.status == ReferralReward.STATUS_PENDING:
            existing.subscription = subscription
            existing.payment = payment or existing.payment
            existing.reward_type = reward_type or referral_code.reward_type
            existing.reward_amount = int(reward_amount if reward_amount is not None else referral_code.reward_amount)
            existing.save(update_fields=["subscription", "payment", "reward_type", "reward_amount", "updated_at"])
            grant_referral_reward(existing)
            return {"awarded": True, "reason": "pending_awarded", "reward_id": existing.id, "code": referral_code.code}
        return {"awarded": existing.status == ReferralReward.STATUS_AWARDED, "reason": "already_recorded", "reward_id": existing.id}
    if payment is not None and ReferralReward.objects.filter(payment=payment).exists():
        return {"awarded": False, "reason": "Bu ödeme için daha önce promosyon ödülü oluşturulmuş."}

    reward = ReferralReward.objects.create(
        referral_code=referral_code,
        referrer=referral_code.owner,
        referred_user=referred_user,
        subscription=subscription,
        payment=payment,
        reward_type=reward_type or referral_code.reward_type,
        reward_amount=int(reward_amount if reward_amount is not None else referral_code.reward_amount),
        status=ReferralReward.STATUS_PENDING,
        note=f"{referred_user.email} aboneliği ile oluşan referans hakkı.",
    )
    grant_referral_reward(reward)
    return {"awarded": True, "reward_id": reward.id, "code": referral_code.code}


@transaction.atomic
def grant_referral_reward(reward):
    reward = (
        ReferralReward.objects
        .select_related("referral_code", "referrer", "referred_user")
        .select_for_update()
        .get(id=reward.id)
    )
    if reward.status == ReferralReward.STATUS_AWARDED:
        return reward

    if reward.reward_type == ReferralCode.REWARD_AI_CREDITS:
        add_ai_credits(
            user=reward.referrer,
            amount=reward.reward_amount,
            action=AICreditLedger.ACTION_ADJUSTMENT,
            reference=f"referral-reward:{reward.id}",
            note=f"{reward.referred_user.email} aboneliği için referans ödülü.",
        )
    elif reward.reward_type == ReferralCode.REWARD_SUBSCRIPTION_DAYS:
        subscription = reward.referrer.subscriptions.filter(is_active=True).order_by("-end_date").first()
        if subscription:
            base_end = max(subscription.end_date, timezone.localdate())
            subscription.end_date = base_end + timedelta(days=reward.reward_amount)
            subscription.next_renewal_date = subscription.end_date
            subscription.save(update_fields=["end_date", "next_renewal_date", "updated_at"])
        else:
            reward.note = (reward.note + "\nAktif abonelik bulunamadığı için gün ödülü uygulanamadı.").strip()

    reward.status = ReferralReward.STATUS_AWARDED
    reward.awarded_at = timezone.now()
    reward.save(update_fields=["status", "awarded_at", "note", "updated_at"])
    return reward


@transaction.atomic
def cancel_referral_rewards_for_payment(payment, note=""):
    cancelled = 0
    for reward in ReferralReward.objects.select_for_update().filter(payment=payment).exclude(status=ReferralReward.STATUS_CANCELLED):
        was_awarded = reward.status == ReferralReward.STATUS_AWARDED
        if was_awarded and reward.reward_type == ReferralCode.REWARD_AI_CREDITS and reward.reward_amount:
            reversal_reference = f"referral-reward-cancel:{reward.id}"
            if not AICreditLedger.objects.filter(user=reward.referrer, reference=reversal_reference).exists():
                current_balance = get_ai_credit_balance(reward.referrer)
                amount = int(reward.reward_amount)
                AICreditLedger.objects.create(
                    user=reward.referrer,
                    action=AICreditLedger.ACTION_REFUND,
                    amount=-amount,
                    balance_after=current_balance - amount,
                    reference=reversal_reference,
                    note=note or "Referans odulu iptal edildigi icin AI kredi geri alindi.",
                )
                refresh_ai_credit_balance(reward.referrer)
        reward.status = ReferralReward.STATUS_CANCELLED
        reward.note = (reward.note + "\n" + (note or "Ödeme iade/iptal olduğu için referans ödülü iptal edildi.")).strip()
        reward.save(update_fields=["status", "note", "updated_at"])
        cancelled += 1
    return cancelled
