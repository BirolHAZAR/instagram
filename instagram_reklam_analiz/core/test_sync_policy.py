from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from core.models import MembershipPlan, User, UserSubscription
from core.services.sync_policy import acquire_sync_lock, is_sync_due, policy_for_user, release_sync_lock


class PlanSyncPolicyTests(TestCase):
    def make_user(self, plan_name, hours, history_days):
        user = User.objects.create_user(username=f"sync-{plan_name}", email=f"{plan_name}@example.com", password="test")
        user.subscriptions.all().delete()
        plan, _ = MembershipPlan.objects.update_or_create(
            name=plan_name,
            defaults={
                "display_name": plan_name,
                "price": 1000,
                "price_with_kdv": 1200,
                "features": "Sync",
                "content_fetch_period_days": history_days,
                "ad_sync_interval_minutes": hours * 60,
                "competitor_sync_interval_minutes": hours * 60,
                "organic_sync_interval_minutes": hours * 60,
                "marketplace_sync_interval_minutes": hours * 60,
                "is_active": True,
            },
        )
        UserSubscription.objects.create(
            user=user,
            plan=plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )
        return user

    def test_silver_is_weekly_and_limited_to_90_days(self):
        user = self.make_user("silver", 168, 90)
        policy = policy_for_user(user)
        self.assertEqual(policy.interval_hours, 168)
        self.assertEqual(policy.history_days, 90)
        self.assertFalse(is_sync_due(user, timezone.now() - timedelta(days=6)))
        self.assertTrue(is_sync_due(user, timezone.now() - timedelta(days=8)))

    def test_gold_and_platinum_frequencies(self):
        gold = self.make_user("gold", 24, 365)
        platinum = self.make_user("platinum", 2, 365)
        self.assertEqual(policy_for_user(gold).interval_hours, 24)
        self.assertEqual(policy_for_user(platinum).interval_hours, 2)

    def test_distributed_lock_prevents_duplicate_dispatch(self):
        cache.clear()
        key, first = acquire_sync_lock("platform", 99)
        _same_key, second = acquire_sync_lock("platform", 99)
        self.assertTrue(first)
        self.assertFalse(second)
        release_sync_lock(key)
        _key, third = acquire_sync_lock("platform", 99)
        self.assertTrue(third)

    def test_each_celery_source_reads_its_own_admin_table_value(self):
        user = self.make_user("gold", 24, 365)
        plan = user.subscriptions.get().plan
        plan.competitor_sync_interval_minutes = 180
        plan.organic_sync_interval_minutes = 360
        plan.marketplace_sync_interval_minutes = 720
        plan.save(update_fields=["competitor_sync_interval_minutes", "organic_sync_interval_minutes", "marketplace_sync_interval_minutes"])
        policy = policy_for_user(user)
        self.assertEqual(policy.interval_minutes_for("competitor"), 180)
        self.assertEqual(policy.interval_minutes_for("organic"), 360)
        self.assertEqual(policy.interval_minutes_for("marketplace"), 720)
