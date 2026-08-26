from datetime import timedelta

from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.utils import timezone
from types import SimpleNamespace
from unittest.mock import patch

from core.decorators import get_user_active_subscription
from core.middleware.subscription_access import SubscriptionAccessMiddleware
from core.models import MembershipPlan, Organization, OrganizationMember, User, UserSubscription
from core.services.entitlements import get_access_subscription, get_active_subscription, get_active_plan


class OrganizationSubscriptionAccessTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="access-owner", password="test")
        self.member = User.objects.create_user(username="access-member", password="test")
        self.outsider = User.objects.create_user(username="access-outsider", password="test")
        # User creation grants a trial automatically. Disable those personal
        # subscriptions so these tests isolate organization-based access.
        UserSubscription.objects.filter(
            user__in=[self.owner, self.member, self.outsider],
            organization__isnull=True,
        ).update(is_active=False)
        self.plan = MembershipPlan.objects.create(
            name="access_agency",
            display_name="Access Agency",
            price=100,
            price_with_kdv=120,
            features="Test",
            is_active=True,
        )
        self.organization = Organization.objects.create(
            name="Access Organization",
            owner=self.owner,
            active_plan=self.plan,
            is_active=True,
        )
        OrganizationMember.objects.create(
            organization=self.organization,
            user=self.member,
            role=OrganizationMember.ROLE_VIEWER,
            is_active=True,
        )
        self.subscription = UserSubscription.objects.create(
            user=self.owner,
            organization=self.organization,
            plan=self.plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )
        self.middleware = SubscriptionAccessMiddleware(lambda request: HttpResponse("ok"))
        self.factory = RequestFactory()

    def test_exact_personal_lookup_does_not_mix_billing_scopes(self):
        self.assertIsNone(get_active_subscription(self.owner))

    def test_owner_gets_access_from_organization_subscription(self):
        self.assertEqual(get_access_subscription(self.owner), self.subscription)
        self.assertEqual(get_active_plan(self.owner), self.plan)
        self.assertEqual(get_user_active_subscription(self.owner), self.subscription)

    def test_active_member_gets_access_from_organization_subscription(self):
        self.assertEqual(get_access_subscription(self.member), self.subscription)

    def test_outsider_cannot_use_foreign_organization_subscription(self):
        self.assertIsNone(get_access_subscription(self.outsider))

    def test_middleware_allows_owner_and_member_without_pricing_redirect(self):
        for user in (self.owner, self.member):
            request = self.factory.get("/dashboard/")
            request.user = user
            self.assertIsNone(self.middleware.process_view(request, lambda request: None, (), {}))

    def test_inactive_membership_does_not_grant_access(self):
        OrganizationMember.objects.filter(user=self.member).update(is_active=False)
        self.assertIsNone(get_access_subscription(self.member))

    def test_expired_or_inactive_organization_subscription_does_not_grant_access(self):
        self.subscription.end_date = timezone.localdate() - timedelta(days=1)
        self.subscription.save(update_fields=["end_date"])
        self.assertIsNone(get_access_subscription(self.owner))

    def test_inactive_organization_does_not_grant_access(self):
        self.organization.is_active = False
        self.organization.save(update_fields=["is_active"])
        self.assertIsNone(get_access_subscription(self.owner))

    def test_control_tower_deep_ai_context_keeps_complete_page_rows(self):
        from core.views.control_tower import _control_tower_deep_ai_context

        page_context = {
            "campaign_health": [{"id": i} for i in range(35)],
            "creative_wall": [{"id": i} for i in range(84)],
            "competitor_rows": [{"id": i} for i in range(12)],
            "competitor_ad_groups": [{"id": i} for i in range(8)],
            "critical_alerts": [{"id": i} for i in range(27)],
            "octo_task_center_tasks": [{"id": i} for i in range(31)],
            "platform_strip_cards": [{"id": i} for i in range(6)],
            "summary": {"octo_score": 77},
        }
        payload = _control_tower_deep_ai_context(page_context)

        self.assertEqual(payload["campaigns"]["count"], 35)
        self.assertEqual(payload["creatives"]["count"], 84)
        self.assertEqual(payload["alerts"]["count"], 27)
        self.assertEqual(payload["data_coverage"]["campaigns"], 35)
        self.assertEqual(payload["data_coverage"]["creatives"], 84)
        self.assertEqual(payload["data_coverage"]["alerts"], 27)
        self.assertTrue(payload["data_coverage"]["source_digest"])
        self.assertTrue(payload["data_coverage"]["complete_page_dataset"])

    def test_deep_ai_ecosystem_record_accepts_sixteen_agents(self):
        from core.models import ControlTowerSnapshot
        from core.services.control_tower_context import _safe_create_ai_analysis

        snapshot = ControlTowerSnapshot.objects.create(
            user=self.owner,
            period="monthly",
            date_from=timezone.localdate() - timedelta(days=29),
            date_to=timezone.localdate(),
        )
        agents = [
            {"name": f"Agent {i}", "finding": "Bulgu", "recommendation": "Aksiyon", "confidence": 0.8, "risk": ""}
            for i in range(16)
        ]
        record = _safe_create_ai_analysis(
            snapshot=snapshot,
            card_key="deep_ai_ecosystem",
            analysis_type="deep_ai_ecosystem",
            title_tr="16 Ajanli Octo Derin Analiz",
            title_en="16-Agent Octo Deep Analysis",
            analysis_tr="Bulgu",
            recommendation_tr="Aksiyon",
            what_happened="Bulgu",
            root_cause="Risk",
            action_plan="Aksiyon",
            expected_impact="Etki",
            severity="info",
            priority="high",
            status="active",
            confidence=80,
            payload={"agents": agents, "complete_page_dataset": True},
        )

        self.assertIsNotNone(record)
        self.assertEqual(len(record.payload["agents"]), 16)

    @patch("core.views.control_tower.get_agency_scope")
    @patch("core.views.control_tower.consume_openai_operation")
    @patch("core.views.control_tower.check_rate_limit")
    def test_control_tower_ai_guard_uses_agency_subscription_and_organization(self, rate_limit, consume, agency_scope):
        from core.views.control_tower import _control_tower_ai_guard

        rate_limit.return_value = SimpleNamespace(allowed=True, retry_after=0)
        consume.return_value = SimpleNamespace(allowed=True)
        agency_scope.return_value = SimpleNamespace(selected_client=None)
        request = self.factory.get("/control-tower/?ai_refresh=1")
        request.user = self.owner

        self.assertIsNone(_control_tower_ai_guard(request))
        self.assertEqual(consume.call_args.kwargs["organization"], self.organization)
