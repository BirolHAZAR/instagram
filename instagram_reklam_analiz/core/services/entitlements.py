from dataclasses import dataclass
from calendar import monthrange
from datetime import datetime

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from core.models import (
    AICreditLedger,
    AICreditPackage,
    MembershipPlan,
    SaaSAICreditPool,
    UserAICreditBalance,
    UserSubscription,
)


UNLIMITED_THRESHOLD = 9999


@dataclass(frozen=True)
class EntitlementResult:
    allowed: bool
    reason: str = ""
    limit: int | None = None
    used: int | None = None


FEATURE_FIELD_MAP = {
    "advanced_reporting": "has_advanced_reporting",
    "opportunity_finder": "has_opportunity_finder",
    "api_access": "has_api_access",
    "white_label": "has_white_label",
    "team_members": "has_team_members",
    "crisis_alert": "has_crisis_alert",
    "strategy_webinar": "has_strategy_webinar",
    "dedicated_manager": "has_dedicated_manager",
    "ai_content_generation": "has_ai_content_generation",
    "campaign_calendar": "has_campaign_calendar",
    "content_calendar": "has_content_calendar",
    "competitor_auto_discovery": "competitor_auto_discovery",
}


LIMIT_FIELD_MAP = {
    "instagram_accounts": "max_instagram_accounts",
    "competitors": "max_competitors",
    "ai_analysis": "ai_analysis_per_month",
    "ai_recommendation": "ai_recommendation_per_month",
    "ai_analysis_weekly": "ai_analysis_per_week",
    "ai_recommendation_weekly": "ai_recommendation_per_week",
    "ai_credits": "ai_credits_per_month",
    "marketplace_product_research": "marketplace_product_research_per_month",
    "marketplace_price_check": "marketplace_price_check_per_month",
    "campaign_templates": "max_campaign_templates",
    "team_members": "max_team_members",
    "included_seats": "included_seats",
    "client_accounts": "max_client_accounts",
}


def model_table_has_column(model, column_name):
    table_name = model._meta.db_table
    existing_tables = set(connection.introspection.table_names())
    if table_name not in existing_tables:
        return False
    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }
    return column_name in columns


def migration_safe_membership_queryset():
    """Return a MembershipPlan queryset that also works before new plan migrations run."""
    table_name = MembershipPlan._meta.db_table
    existing_tables = set(connection.introspection.table_names())
    if table_name not in existing_tables:
        return MembershipPlan.objects.none()
    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }
    missing_model_fields = [
        field.name
        for field in MembershipPlan._meta.concrete_fields
        if field.column not in columns
    ]
    qs = MembershipPlan.objects.all()
    if missing_model_fields:
        qs = qs.defer(*missing_model_fields)
    return qs


def get_active_subscription(user, organization=None):
    """Return an active subscription in one exact billing scope.

    ``organization=None`` intentionally means a personal subscription.  Access
    checks that may be granted by an agency membership must use
    :func:`get_access_subscription` instead.
    """
    if not user or not user.is_authenticated:
        return None

    qs = (
        UserSubscription.objects.select_related("plan", "organization")
        .filter(user=user, is_active=True, end_date__gte=timezone.now().date())
    )
    if organization is not None:
        qs = qs.filter(organization=organization)
    else:
        qs = qs.filter(organization__isnull=True)
    return qs.first()


def get_access_subscription(user):
    """Return the best active subscription that grants the user app access.

    This includes the user's personal subscription and subscriptions belonging
    to active organizations that the user owns or actively belongs to.
    """
    if not user or not user.is_authenticated:
        return None

    from core.models import Organization, OrganizationMember

    organization_ids = Organization.objects.filter(
        Q(owner=user) | Q(members__user=user, members__is_active=True),
        is_active=True,
    ).values_list("id", flat=True)

    return (
        UserSubscription.objects.select_related("plan", "organization")
        .filter(
            Q(user=user, organization__isnull=True) | Q(organization_id__in=organization_ids),
            is_active=True,
            end_date__gte=timezone.localdate(),
            plan__is_active=True,
        )
        .order_by("-plan__price", "-end_date", "-created_at")
        .first()
    )


def get_active_plan(user, organization=None):
    subscription = (
        get_access_subscription(user)
        if organization is None
        else get_active_subscription(user, organization=organization)
    )
    return subscription.plan if subscription and subscription.plan and subscription.plan.is_active else None


def can_use_feature(user, feature_key, organization=None):
    plan = get_active_plan(user, organization=organization)
    if not plan:
        return EntitlementResult(False, "Aktif abonelik bulunamadı.")

    field_name = FEATURE_FIELD_MAP.get(feature_key)
    if not field_name:
        return EntitlementResult(False, f"Bilinmeyen özellik: {feature_key}")

    if plan.name == "agency_10":
        return EntitlementResult(True)

    allowed = bool(getattr(plan, field_name, False))
    return EntitlementResult(allowed, "" if allowed else f"{plan.display_name} bu özelliği içermiyor.")


def get_limit(user, limit_key, organization=None):
    plan = get_active_plan(user, organization=organization)
    if not plan:
        return None

    field_name = LIMIT_FIELD_MAP.get(limit_key)
    if not field_name:
        return None
    return int(getattr(plan, field_name, 0) or 0)


def is_unlimited(limit):
    return limit is not None and limit >= UNLIMITED_THRESHOLD


def check_limit(user, limit_key, used, organization=None):
    limit = get_limit(user, limit_key, organization=organization)
    if limit is None:
        return EntitlementResult(False, f"Bilinmeyen limit: {limit_key}", limit=None, used=used)
    if is_unlimited(limit):
        return EntitlementResult(True, limit=limit, used=used)
    if used < limit:
        return EntitlementResult(True, limit=limit, used=used)
    return EntitlementResult(False, "Paket limiti doldu.", limit=limit, used=used)


def _add_months(value, months):
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def get_subscription_credit_cycle(subscription, today=None):
    if not subscription:
        today = today or timezone.localdate()
        return today.replace(day=1), _add_months(today.replace(day=1), 1)

    today = today or timezone.localdate()
    if subscription.plan and subscription.plan.name == "trial_14":
        return subscription.start_date, subscription.end_date + timezone.timedelta(days=1)

    # Paid plan and add-on credits reset on calendar month boundaries.
    return today.replace(day=1), _add_months(today.replace(day=1), 1)


def _legacy_subscription_credit_cycle(subscription, today=None):
    today = today or timezone.localdate()
    start = subscription.start_date
    if today < start:
        return start, _add_months(start, 1)

    cycle_start = start
    while True:
        cycle_end = _add_months(cycle_start, 1)
        if cycle_start <= today < cycle_end:
            return cycle_start, cycle_end
        cycle_start = cycle_end


def get_saas_ai_credit_cycle(today=None):
    today = today or timezone.localdate()
    raw_start = (getattr(settings, "OPENAI_USAGE_CYCLE_START_DATE", "") or "").strip()
    cycle_start = None

    if raw_start:
        try:
            cycle_start = datetime.strptime(raw_start, "%Y-%m-%d").date()
        except ValueError:
            cycle_start = None

    if cycle_start is None:
        try:
            first_pool = SaaSAICreditPool.objects.order_by("month").first()
        except Exception:
            first_pool = None
        cycle_start = first_pool.month if first_pool else today.replace(day=1)

    if today < cycle_start:
        return cycle_start, _add_months(cycle_start, 1)

    while True:
        cycle_end = _add_months(cycle_start, 1)
        if cycle_start <= today < cycle_end:
            return cycle_start, cycle_end
        cycle_start = cycle_end


def _ai_credit_cycle_queryset(user, organization=None):
    subscription = get_active_subscription(user, organization=organization)
    if organization is not None and not subscription:
        subscription = get_active_subscription(user)
    cycle_start, cycle_end = get_subscription_credit_cycle(subscription)
    if not subscription:
        return AICreditLedger.objects.none(), None, cycle_start, cycle_end
    qs = AICreditLedger.objects.filter(
        user=user,
        created_at__date__gte=cycle_start,
        created_at__date__lt=cycle_end,
    )
    if organization is not None:
        qs = qs.filter(organization=organization)
    else:
        qs = qs.filter(organization__isnull=True)
    return qs, subscription, cycle_start, cycle_end


def _ai_credit_components(user, organization=None):
    qs, subscription, cycle_start, cycle_end = _ai_credit_cycle_queryset(user, organization=organization)
    plan_limit = 0
    if subscription and subscription.plan and model_table_has_column(MembershipPlan, "ai_credits_per_month"):
        plan_limit = int(subscription.plan.ai_credits_per_month or 0)

    grants = sum(
        int(item.amount or 0)
        for item in qs.filter(action=AICreditLedger.ACTION_GRANT, amount__gt=0)
    )
    topups = sum(
        int(item.amount or 0)
        for item in qs.filter(
            action__in=[
                AICreditLedger.ACTION_PURCHASE,
                AICreditLedger.ACTION_REFUND,
                AICreditLedger.ACTION_ADJUSTMENT,
            ],
            amount__gt=0,
        )
    )
    used = abs(sum(int(item.amount or 0) for item in qs.filter(action=AICreditLedger.ACTION_CONSUME, amount__lt=0)))
    plan_credits = max(plan_limit, grants)
    return {
        "subscription": subscription,
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
        "plan_credits": plan_credits,
        "purchased_credits": topups,
        "used_credits": used,
        "current_balance": max(0, plan_credits + topups - used),
    }


def refresh_ai_credit_balance(user, organization=None):
    if not model_table_has_column(UserAICreditBalance, "current_balance"):
        return None
    components = _ai_credit_components(user, organization=organization)
    lookup = {"user": user, "organization": organization}
    balance, _ = UserAICreditBalance.objects.update_or_create(
        **lookup,
        defaults={
            "subscription": components["subscription"],
            "cycle_start": components["cycle_start"],
            "cycle_end": components["cycle_end"],
            "plan_credits": components["plan_credits"],
            "purchased_credits": components["purchased_credits"],
            "used_credits": components["used_credits"],
            "current_balance": components["current_balance"],
        },
    )
    return balance


def refresh_all_ai_credit_balances():
    if not model_table_has_column(UserAICreditBalance, "current_balance"):
        return 0
    from core.models import Organization, User

    pairs = set(AICreditLedger.objects.values_list("user_id", "organization_id"))
    pairs.update(UserSubscription.objects.filter(is_active=True).values_list("user_id", "organization_id"))
    pairs.update((user_id, None) for user_id in User.objects.values_list("id", flat=True))
    pairs.update(Organization.objects.values_list("owner_id", "id"))
    count = 0
    for user_id, organization_id in pairs:
        if not user_id:
            continue
        refresh_ai_credit_balance_id(user_id, organization_id)
        count += 1
    return count


def refresh_ai_credit_balance_id(user_id, organization_id=None):
    from core.models import Organization, User

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return None
    organization = None
    if organization_id:
        try:
            organization = Organization.objects.get(id=organization_id)
        except Organization.DoesNotExist:
            organization = None
    return refresh_ai_credit_balance(user, organization=organization)


def get_ai_credit_balance(user, organization=None):
    if not model_table_has_column(AICreditLedger, "balance_after"):
        return 0
    if model_table_has_column(UserAICreditBalance, "current_balance"):
        balance = refresh_ai_credit_balance(user, organization=organization)
        return int(balance.current_balance if balance else 0)
    return _ai_credit_components(user, organization=organization)["current_balance"]


def grant_plan_ai_credits(subscription):
    if not subscription or not subscription.plan:
        return None
    if not model_table_has_column(AICreditLedger, "balance_after"):
        return None
    if not model_table_has_column(MembershipPlan, "ai_credits_per_month"):
        return None
    credits = int(subscription.plan.ai_credits_per_month or 0)
    if credits <= 0:
        return None
    return add_ai_credits(
        user=subscription.user,
        amount=credits,
        action=AICreditLedger.ACTION_GRANT,
        subscription=subscription,
        organization=subscription.organization,
        reference=f"plan:{subscription.plan.name}:{subscription.start_date}",
        note=f"{subscription.plan.display_name} aylık AI kredi tanımı.",
    )


def add_ai_credits(user, amount, action=AICreditLedger.ACTION_ADJUSTMENT, organization=None, subscription=None, package=None, reference="", note=""):
    amount = int(amount)
    active_subscription = get_active_subscription(user, organization=organization)
    if organization is not None and not active_subscription:
        active_subscription = get_active_subscription(user)
    if action == AICreditLedger.ACTION_PURCHASE and not active_subscription:
        raise ValueError("Ek AI kredi paketi için aktif deneme veya abonelik gerekli.")
    if amount <= 0:
        raise ValueError("Eklenecek kredi pozitif olmalı.")
    current = get_ai_credit_balance(user, organization=organization)
    ledger = AICreditLedger.objects.create(
        user=user,
        organization=organization,
        subscription=subscription,
        package=package,
        action=action,
        amount=amount,
        balance_after=current + amount,
        reference=reference,
        note=note,
    )
    refresh_ai_credit_balance(user, organization=organization)
    return ledger


def consume_ai_credits(user, amount, reason, organization=None, reference=""):
    amount = int(amount)
    if amount <= 0:
        raise ValueError("Kullanılacak kredi pozitif olmalı.")
    with transaction.atomic():
        user.__class__.objects.select_for_update().get(pk=user.pk)
        current = get_ai_credit_balance(user, organization=organization)
        if current < amount:
            return EntitlementResult(False, "AI kredi bakiyesi yetersiz.", limit=current, used=amount)
        AICreditLedger.objects.create(
            user=user,
            organization=organization,
            action=AICreditLedger.ACTION_CONSUME,
            amount=-amount,
            balance_after=current - amount,
            reference=reference,
            note=reason,
        )
        refresh_ai_credit_balance(user, organization=organization)
        return EntitlementResult(True, limit=current, used=amount)


def record_saas_ai_credit_usage(amount, used_at=None):
    amount = int(amount or 0)
    if amount <= 0:
        return None
    if not model_table_has_column(SaaSAICreditPool, "used_credits"):
        return None
    used_at = used_at or timezone.localdate()
    month, _ = get_saas_ai_credit_cycle(used_at)
    pool, _ = SaaSAICreditPool.objects.get_or_create(
        month=month,
        defaults={"purchased_credits": 1_000_000},
    )
    pool.used_credits = int(pool.used_credits or 0) + amount
    pool.save(update_fields=["used_credits", "updated_at"])
    return pool


def visible_business_plans():
    if not model_table_has_column(MembershipPlan, "plan_type"):
        return (
            migration_safe_membership_queryset().filter(is_active=True)
            .exclude(name__in=["bronze", "bronz"])
            .order_by("order", "price")
        )
    return MembershipPlan.objects.filter(
        is_active=True,
        plan_type=MembershipPlan.PLAN_TYPE_BUSINESS,
    ).order_by("order", "price")


def visible_agency_plans():
    if not model_table_has_column(MembershipPlan, "plan_type"):
        return MembershipPlan.objects.none()
    return MembershipPlan.objects.filter(
        is_active=True,
        plan_type=MembershipPlan.PLAN_TYPE_AGENCY,
    ).order_by("order", "price")


def visible_ai_credit_packages():
    table_name = AICreditPackage._meta.db_table
    if table_name not in set(connection.introspection.table_names()):
        return AICreditPackage.objects.none()
    return AICreditPackage.objects.filter(is_active=True).order_by("order", "price")
