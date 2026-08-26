from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import MembershipPlan, Platform, PlatformAccount, User, UserSubscription
from core.services.plan_limits import ensure_platform_account_capacity


class TotalPlatformAccountLimitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="platform-limit", email="limit@example.com", password="test")
        self.user.subscriptions.all().delete()
        self.plan = MembershipPlan.objects.create(
            name="platform-limit-plan", display_name="Limit", price=100, price_with_kdv=120,
            features="Limit", max_instagram_accounts=3,
        )
        UserSubscription.objects.create(
            user=self.user, plan=self.plan, start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30), is_active=True,
        )
        self.instagram = Platform.objects.create(name="Instagram Limit", code="instagram-limit")
        self.facebook = Platform.objects.create(name="Facebook Limit", code="facebook-limit")

    def add_account(self, platform, account_id):
        return PlatformAccount.objects.create(
            user=self.user, platform=platform, account_id=account_id,
            account_name=account_id, access_token="token", is_active=True,
        )

    def test_limit_counts_all_platforms_together(self):
        self.add_account(self.instagram, "ig-1")
        self.add_account(self.facebook, "fb-1")
        self.add_account(self.facebook, "fb-2")
        with self.assertRaisesMessage(ValueError, "toplam 3 platform hesabına"):
            ensure_platform_account_capacity(self.user, [(self.instagram.code, "ig-2")])

    def test_existing_account_update_does_not_consume_another_slot(self):
        self.add_account(self.instagram, "ig-1")
        self.assertTrue(ensure_platform_account_capacity(self.user, [(self.instagram.code, "ig-1")]))
