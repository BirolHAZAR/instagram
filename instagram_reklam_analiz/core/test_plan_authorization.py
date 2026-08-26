from datetime import timedelta
from types import SimpleNamespace

from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.middleware.agency_permissions import AgencyMenuPermissionMiddleware
from core.models import MembershipPlan, User, UserSubscription
from core.services.agency_permission_matrix import user_has_agency_menu_permission


class PlanAuthorizationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="plan-user", email="plan@example.com", password="test")
        self.plan = MembershipPlan.objects.create(
            name="authorization_test",
            display_name="Yetki Test",
            price=100,
            price_with_kdv=120,
            features="Test",
            has_advanced_reporting=True,
            has_ai_content_generation=False,
            max_competitors=0,
        )
        UserSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )
        self.factory = RequestFactory()
        self.middleware = AgencyMenuPermissionMiddleware(lambda request: HttpResponse("ok"))

    def request(self, url_name, path="/module/"):
        request = self.factory.get(path)
        request.user = self.user
        request.resolver_match = SimpleNamespace(url_name=url_name)
        return request

    def test_plan_boolean_hides_and_blocks_unavailable_feature(self):
        self.assertFalse(user_has_agency_menu_permission(self.user, "creative_studio"))
        response = self.middleware.process_view(self.request("creative_studio"), None, (), {})
        self.assertEqual(response.status_code, 403)

    def test_plan_boolean_allows_included_feature(self):
        self.assertTrue(user_has_agency_menu_permission(self.user, "reports_center"))
        self.assertIsNone(self.middleware.process_view(self.request("reports_center"), None, (), {}))

    def test_plan_limit_blocks_zero_and_allows_positive(self):
        self.assertFalse(user_has_agency_menu_permission(self.user, "competitor_intelligence"))
        self.plan.max_competitors = 3
        self.plan.save(update_fields=["max_competitors"])
        delattr(self.user, "_agency_menu_permission_cache") if hasattr(self.user, "_agency_menu_permission_cache") else None
        self.assertTrue(user_has_agency_menu_permission(self.user, "competitor_intelligence"))

    def test_api_alias_is_protected_by_parent_feature(self):
        response = self.middleware.process_view(self.request("generate_content_api", "/api/creative/generate/"), None, (), {})
        self.assertEqual(response.status_code, 403)

    def test_unmapped_base_module_remains_available(self):
        self.assertTrue(user_has_agency_menu_permission(self.user, "campaign_center"))

    def test_staff_bypasses_plan_rules(self):
        self.user.is_staff = True
        self.assertTrue(user_has_agency_menu_permission(self.user, "creative_studio"))

    def test_marketplace_is_blocked_when_plan_allowance_is_zero(self):
        self.plan.marketplace_product_research_per_month = 0
        self.plan.marketplace_price_check_per_month = 0
        self.plan.save(update_fields=["marketplace_product_research_per_month", "marketplace_price_check_per_month"])
        self.assertFalse(user_has_agency_menu_permission(self.user, "marketplace_product_research"))
        self.assertFalse(user_has_agency_menu_permission(self.user, "marketplace_price_tracking"))

    def test_trial_plan_can_access_every_module(self):
        trial_plan = MembershipPlan.objects.get(name="trial_14")
        trial_plan.has_ai_content_generation = False
        trial_plan.has_white_label = False
        trial_plan.save(update_fields=["has_ai_content_generation", "has_white_label"])
        subscription = self.user.subscriptions.get(plan=self.plan)
        subscription.plan = trial_plan
        subscription.save(update_fields=["plan"])
        self.assertTrue(user_has_agency_menu_permission(self.user, "creative_studio"))
        self.assertTrue(user_has_agency_menu_permission(self.user, "agency_branding"))
