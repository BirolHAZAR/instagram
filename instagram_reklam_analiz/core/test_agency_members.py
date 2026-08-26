from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase
from django.urls import reverse
from allauth.account.models import EmailAddress

from core.models import AgencyRoleGroup, MembershipPlan, Organization, OrganizationMember
from core.services.agency_permission_matrix import user_has_agency_menu_permission
from core.services.agency_roles import ensure_default_agency_role_groups
from core.context_processors import agency_client_scope


class AgencyMemberManagementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            username="agency-owner",
            email="owner@agency.test",
            password="OwnerPass123!",
        )
        self.plan = MembershipPlan.objects.create(
            name="agency_member_test",
            display_name="Ajans Üye Testi",
            price=100,
            price_with_kdv=120,
            features="Test",
            has_team_members=True,
            included_seats=10,
            max_team_members=10,
        )
        self.organization = Organization.objects.create(
            name="Test Ajansı",
            owner=self.owner,
            active_plan=self.plan,
        )
        self.groups = ensure_default_agency_role_groups(self.organization)
        self.client.force_login(self.owner)

    def invite_url(self):
        return reverse("agency_member_invite", args=[self.organization.id])

    def test_new_sub_user_is_created_with_usable_password_and_group(self):
        response = self.client.post(self.invite_url(), {
            "first_name": "Alt",
            "last_name": "Kullanıcı",
            "username": "alt-kullanici",
            "email": "alt@agency.test",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
            "role_group": self.groups["viewer"].id,
        })

        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(email="alt@agency.test")
        self.assertTrue(user.check_password("StrongPass123!"))
        member = OrganizationMember.objects.get(organization=self.organization, user=user)
        self.assertEqual(member.role_group, self.groups["viewer"])
        self.assertTrue(member.is_managed_subaccount)
        self.assertTrue(EmailAddress.objects.filter(user=user, email=user.email, verified=False).exists())

    def test_new_sub_user_without_password_is_rejected(self):
        response = self.client.post(self.invite_url(), {
            "first_name": "Eksik",
            "last_name": "Parola",
            "username": "missing-password",
            "email": "missing-password@agency.test",
            "role_group": self.groups["viewer"].id,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Yeni alt kullanıcı için parola zorunludur.")
        self.assertFalse(get_user_model().objects.filter(email="missing-password@agency.test").exists())

    def test_existing_user_password_is_not_changed(self):
        user = get_user_model().objects.create_user(
            username="existing-member",
            email="existing@agency.test",
            password="ExistingPass123!",
        )
        response = self.client.post(self.invite_url(), {
            "first_name": "Mevcut",
            "last_name": "Kullanıcı",
            "username": user.username,
            "email": user.email,
            "password1": "",
            "password2": "",
            "role_group": self.groups["editor"].id,
        })

        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.check_password("ExistingPass123!"))
        self.assertEqual(
            OrganizationMember.objects.get(organization=self.organization, user=user).role_group,
            self.groups["editor"],
        )

    def test_email_is_required_for_new_sub_user(self):
        response = self.client.post(self.invite_url(), {
            "first_name": "Epostasız",
            "last_name": "Kullanıcı",
            "username": "no-email-member",
            "email": "",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
            "role_group": self.groups["viewer"].id,
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["invite_form"].errors)
        self.assertFalse(get_user_model().objects.filter(username="no-email-member").exists())

    def test_managed_subaccount_can_be_deleted(self):
        user = get_user_model().objects.create_user(
            username="managed-child",
            email="managed-child@agency.test",
            password="MemberPass123!",
        )
        member = OrganizationMember.objects.create(
            organization=self.organization,
            user=user,
            role=OrganizationMember.ROLE_VIEWER,
            role_group=self.groups["viewer"],
            is_managed_subaccount=True,
        )

        response = self.client.post(
            reverse("agency_subaccount_delete", args=[self.organization.id, member.id]),
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(get_user_model().objects.filter(pk=user.pk).exists())

    def test_existing_linked_user_is_removed_from_agency_without_deleting_account(self):
        user = get_user_model().objects.create_user(
            username="linked-user",
            email="linked@agency.test",
            password="MemberPass123!",
        )
        member = OrganizationMember.objects.create(
            organization=self.organization,
            user=user,
            role=OrganizationMember.ROLE_VIEWER,
            role_group=self.groups["viewer"],
            is_managed_subaccount=False,
        )

        response = self.client.post(
            reverse("agency_subaccount_delete", args=[self.organization.id, member.id]),
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(get_user_model().objects.filter(pk=user.pk).exists())
        self.assertFalse(OrganizationMember.objects.filter(pk=member.pk).exists())

    def test_group_is_the_single_dynamic_permission_source(self):
        user = get_user_model().objects.create_user("group-member", password="MemberPass123!")
        group = AgencyRoleGroup.objects.create(
            organization=self.organization,
            name="Rapor Ekibi",
            can_view_reports=True,
            menu_permissions=["reports_center"],
        )
        member = OrganizationMember.objects.create(
            organization=self.organization,
            user=user,
            role=OrganizationMember.ROLE_ADMIN,
            role_group=group,
            can_manage_members=True,
            menu_permissions=["creative_studio"],
        )

        self.assertTrue(member.has_permission("view_reports"))
        self.assertFalse(member.has_permission("manage_members"))
        self.assertTrue(user_has_agency_menu_permission(user, "reports_center"))
        self.assertFalse(user_has_agency_menu_permission(user, "creative_studio"))

        group.menu_permissions = ["creative_studio"]
        group.save(update_fields=["menu_permissions"])
        if hasattr(user, "_agency_menu_permission_cache"):
            delattr(user, "_agency_menu_permission_cache")
        self.assertFalse(user_has_agency_menu_permission(user, "reports_center"))
        self.assertTrue(user_has_agency_menu_permission(user, "creative_studio"))

    def test_sub_user_cannot_be_member_of_second_agency(self):
        user = get_user_model().objects.create_user(
            username="single-agency-member",
            email="single-agency@agency.test",
            password="MemberPass123!",
        )
        OrganizationMember.objects.create(
            organization=self.organization,
            user=user,
            role=OrganizationMember.ROLE_VIEWER,
            role_group=self.groups["viewer"],
        )
        other_owner = get_user_model().objects.create_user(
            username="other-owner",
            email="other-owner@agency.test",
            password="OwnerPass123!",
        )
        other_organization = Organization.objects.create(name="Diğer Ajans", owner=other_owner)
        other_group = ensure_default_agency_role_groups(other_organization)["viewer"]

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OrganizationMember.objects.create(
                    organization=other_organization,
                    user=user,
                    role=OrganizationMember.ROLE_VIEWER,
                    role_group=other_group,
                )

    def test_header_identity_uses_only_membership_agency_and_group(self):
        user = get_user_model().objects.create_user(
            username="header-member",
            email="header@agency.test",
            password="MemberPass123!",
        )
        membership = OrganizationMember.objects.create(
            organization=self.organization,
            user=user,
            role=OrganizationMember.ROLE_VIEWER,
            role_group=self.groups["viewer"],
        )
        request = RequestFactory().get("/")
        request.user = user
        request.session = {}

        context = agency_client_scope(request)

        self.assertEqual(context["agency_member_identity"], membership)
        self.assertEqual(context["agency_member_identity"].role_group, self.groups["viewer"])

    def test_owner_can_have_multiple_agencies_with_owner_memberships(self):
        second_organization = Organization.objects.create(
            name="İkinci Ajans",
            owner=self.owner,
            active_plan=self.plan,
        )
        OrganizationMember.objects.create(
            organization=self.organization,
            user=self.owner,
            role=OrganizationMember.ROLE_OWNER,
        )
        OrganizationMember.objects.create(
            organization=second_organization,
            user=self.owner,
            role=OrganizationMember.ROLE_OWNER,
        )

        self.assertEqual(
            OrganizationMember.objects.filter(user=self.owner, role=OrganizationMember.ROLE_OWNER).count(),
            2,
        )

    def test_admin_additional_seats_extend_only_organization_limit(self):
        self.organization.additional_seats = 3
        self.organization.save(update_fields=["additional_seats"])

        self.assertEqual(self.organization.seat_limit, self.plan.included_seats + 3)
