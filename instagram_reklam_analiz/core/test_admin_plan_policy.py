from django.test import TestCase
from django.urls import reverse

from core.models import MembershipPlan, User


class PlanAuthorizationPolicyAdminTests(TestCase):
    def test_changelist_renders_plan_type_badges(self):
        admin_user = User.objects.create_superuser(
            username="policy-admin",
            email="policy-admin@example.com",
            password="test-password",
        )
        MembershipPlan.objects.create(
            name="agency_admin_badge_test",
            display_name="Ajans Rozet Testi",
            plan_type=MembershipPlan.PLAN_TYPE_AGENCY,
            price=0,
            price_with_kdv=0,
            features="Test",
        )
        self.client.force_login(admin_user)

        response = self.client.get(reverse("admin:core_planauthorizationpolicy_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AJANS")
        self.assertContains(response, "Ajans Rozet Testi")
