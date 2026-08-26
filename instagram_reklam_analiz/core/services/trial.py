from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from core.models import AICreditLedger, MembershipPlan, UserSubscription
from core.services.entitlements import add_ai_credits, model_table_has_column


TRIAL_PLAN_NAME = "trial_14"


def get_or_create_trial_plan():
    days = int(getattr(settings, "TRIAL_DAYS", 14) or 14)
    credits = int(getattr(settings, "TRIAL_AI_CREDITS", 50) or 50)
    plan, _ = MembershipPlan.objects.update_or_create(
        name=TRIAL_PLAN_NAME,
        defaults={
            "display_name": f"{days} Gun Ucretsiz Deneme",
            "plan_type": MembershipPlan.PLAN_TYPE_LEGACY,
            "price": 0,
            "price_with_kdv": 0,
            "features": "\n".join([
                f"{days} gun ucretsiz kullanim",
                f"{credits} AI kredi",
                "1 platform hesabi",
                "1 rakip takibi",
                "Temel raporlama",
            ]),
            "order": 98,
            "is_active": True,
            "badge": "Deneme",
            "badge_color": "#22C55E",
            "is_most_popular": False,
            "max_instagram_accounts": 1,
            "max_competitors": 1,
            "ai_analysis_per_month": 10,
            "ai_recommendation_per_month": 10,
            "marketplace_product_research_per_month": 3,
            "marketplace_price_check_per_month": 30,
            "ai_credits_per_month": credits,
            "allow_ai_credit_topup": True,
            "has_advanced_reporting": False,
            "has_ai_content_generation": True,
            "ai_content_generation": True,
            "priority_support": False,
        },
    )
    return plan


def ensure_trial_subscription(user):
    if not getattr(settings, "TRIAL_ENABLED", True):
        return None
    if not user or not getattr(user, "is_authenticated", False):
        return None
    if UserSubscription.objects.filter(user=user).exists():
        return None

    days = int(getattr(settings, "TRIAL_DAYS", 14) or 14)
    credits = int(getattr(settings, "TRIAL_AI_CREDITS", 50) or 50)
    today = timezone.now().date()
    plan = get_or_create_trial_plan()
    subscription = UserSubscription.objects.create(
        user=user,
        plan=plan,
        start_date=today,
        end_date=today + timedelta(days=days - 1),
        is_active=True,
        auto_renew=False,
    )
    if credits > 0 and model_table_has_column(AICreditLedger, "balance_after"):
        add_ai_credits(
            user=user,
            amount=credits,
            action=AICreditLedger.ACTION_GRANT,
            subscription=subscription,
            reference=f"trial:{user.pk}:{today.isoformat()}",
            note=f"{days} gunluk deneme kredisi.",
        )
    return subscription
