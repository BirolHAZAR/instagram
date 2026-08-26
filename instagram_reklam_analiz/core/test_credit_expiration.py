from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import AICreditLedger, MembershipPlan, User, UserSubscription
from core.services.entitlements import add_ai_credits, get_ai_credit_balance
from core.services.product_research_credits import (
    add_product_research_units,
    consume_product_research_units,
    get_product_research_balance,
)


class CreditExpirationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="expiry-user", email="expiry@example.com", password="test")
        self.user.subscriptions.all().delete()
        self.plan = MembershipPlan.objects.create(
            name="expiry-plan",
            display_name="Expiry Plan",
            price=100,
            price_with_kdv=120,
            features="Test",
            ai_credits_per_month=100,
        )
        self.subscription = UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=60),
            is_active=True,
        )

    def test_previous_month_ai_topup_never_carries_forward(self):
        ledger = add_ai_credits(
            self.user,
            250,
            action=AICreditLedger.ACTION_PURCHASE,
            package=None,
        )
        previous_month = timezone.now() - timedelta(days=35)
        AICreditLedger.objects.filter(pk=ledger.pk).update(created_at=previous_month)
        self.assertEqual(get_ai_credit_balance(self.user), 100)

    def test_expired_subscription_makes_all_ai_credits_unavailable(self):
        add_ai_credits(self.user, 250, action=AICreditLedger.ACTION_PURCHASE)
        self.subscription.end_date = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["end_date"])
        self.assertEqual(get_ai_credit_balance(self.user), 0)

    def test_addon_purchase_is_rejected_without_active_trial_or_subscription(self):
        self.subscription.is_active = False
        self.subscription.save(update_fields=["is_active"])
        with self.assertRaises(ValueError):
            add_ai_credits(self.user, 250, action=AICreditLedger.ACTION_PURCHASE)
        with self.assertRaises(ValueError):
            add_product_research_units(user=self.user, amount=10)

    def test_product_research_units_reset_in_new_month(self):
        add_product_research_units(user=self.user, amount=10)
        next_month = (timezone.localdate().replace(day=28) + timedelta(days=8)).replace(day=1)
        balance = get_product_research_balance(self.user, today=next_month)
        self.assertEqual(balance.current_balance, 0)

    def test_product_research_cannot_be_used_after_subscription_expires(self):
        add_product_research_units(user=self.user, amount=10)
        self.subscription.end_date = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["end_date"])
        result = consume_product_research_units(user=self.user, amount=1)
        self.assertFalse(result.allowed)
