from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from types import SimpleNamespace
from unittest.mock import patch

from core.models import Ad, AdGroup, AdMetricHistory, AgencyClient, Campaign, Competitor, Creative, FeatureUsageLedger, OctoTaskInstance, OctoTaskRule, Organization, OrganizationMember, Platform, PlatformAccount, ReklamAIAnaliz
from core.services.agency_branding import get_report_branding
from core.services.agency_scope import get_agency_scope, platform_accounts_for_request, scope_queryset


User = get_user_model()


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class AgencyScopeTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="agency-owner", password="test")
        self.member = User.objects.create_user(username="agency-member", password="test")
        self.outsider = User.objects.create_user(username="normal-user", password="test")
        self.organization = Organization.objects.create(name="Test Ajansı", owner=self.owner)
        OrganizationMember.objects.create(
            organization=self.organization,
            user=self.member,
            role=OrganizationMember.ROLE_VIEWER,
            is_active=True,
        )
        self.client_a = AgencyClient.objects.create(organization=self.organization, name="Firma A")
        self.client_b = AgencyClient.objects.create(organization=self.organization, name="Firma B")
        self.platform = Platform.objects.create(name="Instagram", code="instagram")
        self.account_a = PlatformAccount.objects.create(
            user=self.owner,
            platform=self.platform,
            agency_client=self.client_a,
            account_id="a",
            access_token="token-a",
        )
        self.account_b = PlatformAccount.objects.create(
            user=self.owner,
            platform=self.platform,
            agency_client=self.client_b,
            account_id="b",
            access_token="token-b",
        )

    def request(self, user, data=None):
        request = RequestFactory().get("/dashboard/", data or {})
        request.user = user
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        return request

    def test_owner_can_select_client_and_scope_accounts(self):
        request = self.request(self.owner, {"agency_client": str(self.client_a.id)})
        scope = get_agency_scope(request)

        self.assertTrue(scope.is_agency)
        self.assertEqual(scope.selected_client, self.client_a)
        self.assertEqual(list(platform_accounts_for_request(request)), [self.account_a])

    def test_agency_member_can_read_organization_accounts(self):
        request = self.request(self.member, {"agency_client": str(self.client_b.id)})

        self.assertEqual(list(platform_accounts_for_request(request)), [self.account_b])

    def test_non_agency_user_cannot_select_foreign_client(self):
        request = self.request(self.outsider, {"agency_client": str(self.client_a.id)})
        scope = get_agency_scope(request)

        self.assertFalse(scope.is_agency)
        self.assertIsNone(scope.selected_client)
        self.assertFalse(platform_accounts_for_request(request).exists())

    def test_campaign_scope_follows_selected_client(self):
        campaign_a = Campaign.objects.create(
            user=self.owner,
            platform_account=self.account_a,
            platform_campaign_id="campaign-a",
            name="Campaign A",
        )
        Campaign.objects.create(
            user=self.owner,
            platform_account=self.account_b,
            platform_campaign_id="campaign-b",
            name="Campaign B",
        )
        request = self.request(self.member, {"agency_client": str(self.client_a.id)})

        self.assertEqual(list(scope_queryset(request, Campaign.objects.all())), [campaign_a])

    def test_client_logo_has_priority_and_missing_logo_uses_product_brand(self):
        self.client_a.logo = "agency/client-logos/firma-a.png"
        self.client_a.save(update_fields=["logo"])

        branded = get_report_branding(self.owner, agency_client=self.client_a)
        fallback = get_report_branding(self.owner, agency_client=self.client_b)

        self.assertEqual(branded.brand_name, "Firma A")
        self.assertTrue(branded.logo_path.endswith("firma-a.png"))
        self.assertEqual(fallback.brand_name, "ReklamAnaliz.net")

    def test_agency_selector_is_visible_only_to_agency_users(self):
        self.client.force_login(self.owner)
        agency_response = self.client.get(
            reverse("performance_center"),
            {"agency_client": str(self.client_a.id)},
        )
        self.assertEqual(agency_response.status_code, 200)
        self.assertContains(agency_response, 'class="agency-client-scope-form"')
        self.assertEqual(agency_response.context["agency_scope"].selected_client, self.client_a)

        self.client.force_login(self.outsider)
        personal_response = self.client.get(reverse("performance_center"))
        self.assertEqual(personal_response.status_code, 200)
        self.assertNotContains(personal_response, 'class="agency-client-scope-form"')

    def test_ad_movements_filter_is_agency_only_and_scopes_ajax_rows(self):
        campaign_a = Campaign.objects.create(
            user=self.owner,
            platform_account=self.account_a,
            platform_campaign_id="movements-campaign-a",
            name="Firma A Hareket Kampanyası",
        )
        campaign_b = Campaign.objects.create(
            user=self.owner,
            platform_account=self.account_b,
            platform_campaign_id="movements-campaign-b",
            name="Firma B Hareket Kampanyası",
        )
        ad_a = Ad.objects.create(
            user=self.owner,
            source_type="OWN",
            platform_account=self.account_a,
            campaign=campaign_a,
            platform_ad_id="movements-ad-a",
            name="Firma A Hareket Reklamı",
        )
        Ad.objects.create(
            user=self.owner,
            source_type="OWN",
            platform_account=self.account_b,
            campaign=campaign_b,
            platform_ad_id="movements-ad-b",
            name="Firma B Hareket Reklamı",
        )

        self.client.force_login(self.owner)
        page = self.client.get(
            reverse("reklam_hareketleri"),
            {"agency_client": str(self.client_a.id)},
        )
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'class="movement-agency-filter"')
        self.assertEqual(list(page.context["platform_accounts"]), [self.account_a])

        ajax = self.client.get(
            reverse("reklam_hareketleri"),
            {"agency_client": str(self.client_a.id)},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(ajax.status_code, 200)
        self.assertEqual([row["id"] for row in ajax.json()["reklamlar"]], [ad_a.id])

        self.client.force_login(self.outsider)
        personal_page = self.client.get(reverse("reklam_hareketleri"))
        self.assertEqual(personal_page.status_code, 200)
        self.assertNotContains(personal_page, 'class="movement-agency-filter"')

    def test_health_report_card_scopes_agency_and_reads_database_rules(self):
        campaign_a = Campaign.objects.create(
            user=self.owner, platform_account=self.account_a,
            platform_campaign_id="health-card-a", name="Firma A Sağlık Kampanyası",
        )
        campaign_b = Campaign.objects.create(
            user=self.owner, platform_account=self.account_b,
            platform_campaign_id="health-card-b", name="Firma B Sağlık Kampanyası",
        )
        ad_a = Ad.objects.create(
            user=self.owner, source_type="OWN", platform_account=self.account_a,
            campaign=campaign_a, platform_ad_id="health-card-ad-a", name="Firma A Sağlık Reklamı",
        )
        Ad.objects.create(
            user=self.owner, source_type="OWN", platform_account=self.account_b,
            campaign=campaign_b, platform_ad_id="health-card-ad-b", name="Firma B Sağlık Reklamı",
        )
        AdMetricHistory.objects.create(
            ad=ad_a, date="2026-07-13", impressions=1000, clicks=50,
            spend="100.00", conversions="5", conversion_value="400.00",
        )
        rule = OctoTaskRule.objects.create(
            code="health-card-rule", module="performance", severity="warning",
            title_tr="Sağlık kural tespiti", message_tr="CTR izlenmelidir. Maliyet kontrol edilmelidir.",
            action_text_tr="Kreatif varyasyonu test edilmelidir.", condition_key="health_card_rule",
        )
        OctoTaskInstance.objects.create(
            rule=rule, user=self.owner, ad=ad_a, module="performance", severity="warning",
            title_tr=rule.title_tr, message_tr=rule.message_tr, action_text_tr=rule.action_text_tr,
            unique_key="health-card-task-a",
        )

        self.client.force_login(self.owner)
        with patch("core.views.ad_health_report_card.generate_octo_tasks.apply_async") as enqueue:
            enqueue.return_value.id = "health-scan-1"
            response = self.client.get(
                reverse("ad_health_report_card"),
                {"agency_client": str(self.client_a.id), "ad": str(ad_a.id), "gun": "30"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="rc-agency-filter"')
        self.assertEqual(list(response.context["ads"]), [ad_a])
        self.assertEqual(response.context["matched_rule_count"], 1)
        self.assertEqual(response.context["metrics"]["Gösterim"], "1.000")
        self.assertIn("Kreatif varyasyonu test edilmelidir.", response.context["note_points"]["action"])
        enqueue.assert_called_once()

        self.client.force_login(self.outsider)
        personal_response = self.client.get(reverse("ad_health_report_card"))
        self.assertEqual(personal_response.status_code, 200)
        self.assertNotContains(personal_response, 'class="rc-agency-filter"')

    def test_health_center_scopes_agency_and_attaches_persisted_rule_findings(self):
        campaign_a = Campaign.objects.create(
            user=self.owner, platform_account=self.account_a,
            platform_campaign_id="health-center-a", name="Firma A Merkez Kampanyası",
        )
        campaign_b = Campaign.objects.create(
            user=self.owner, platform_account=self.account_b,
            platform_campaign_id="health-center-b", name="Firma B Merkez Kampanyası",
        )
        ad_a = Ad.objects.create(
            user=self.owner, source_type="OWN", platform_account=self.account_a,
            campaign=campaign_a, platform_ad_id="health-center-ad-a",
            name="Firma A Merkez Reklamı", status="ACTIVE", is_active=True,
        )
        Ad.objects.create(
            user=self.owner, source_type="OWN", platform_account=self.account_b,
            campaign=campaign_b, platform_ad_id="health-center-ad-b",
            name="Firma B Merkez Reklamı", status="ACTIVE", is_active=True,
        )
        AdMetricHistory.objects.create(
            ad=ad_a, date="2026-07-13", impressions=2000, clicks=80,
            spend="240.00", conversions="8", conversion_value="960.00",
        )
        rule = OctoTaskRule.objects.create(
            code="health-center-rule", module="performance", severity="warning",
            title_tr="Maliyet riski", message_tr="CPA yakından izlenmelidir. Bütçe kontrollü tutulmalıdır.",
            action_text_tr="Düşük verimli kırılımlar azaltılmalıdır.", condition_key="health_center_rule",
        )
        OctoTaskInstance.objects.create(
            rule=rule, user=self.owner, ad=ad_a, platform_account=self.account_a,
            campaign=campaign_a, module="performance", severity="warning",
            title_tr=rule.title_tr, message_tr=rule.message_tr,
            action_text_tr=rule.action_text_tr, unique_key="health-center-task-a",
        )

        self.client.force_login(self.owner)
        with patch("core.views.health_center.generate_octo_tasks.apply_async") as enqueue:
            enqueue.return_value.id = "health-center-scan-1"
            response = self.client.get(
                reverse("health_center"),
                {"agency_client": str(self.client_a.id), "gun": "30"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="hc-field hc-agency-field"')
        self.assertEqual([row["id"] for row in response.context["all_ads"]], [ad_a.id])
        self.assertEqual(response.context["totals"]["impressions"], 2000)
        self.assertEqual(response.context["matched_rule_count"], 1)
        self.assertIn("CPA yakından izlenmelidir.", response.context["all_ads"][0]["risk_points"])
        self.assertIn("Düşük verimli kırılımlar azaltılmalıdır.", response.context["all_ads"][0]["action_points"])
        enqueue.assert_called_once()

        self.client.force_login(self.outsider)
        personal_response = self.client.get(reverse("health_center"))
        self.assertEqual(personal_response.status_code, 200)
        self.assertNotContains(personal_response, 'class="hc-field hc-agency-field"')

    def test_creative_center_filter_is_agency_only_and_client_scoped(self):
        creative_a = Creative.objects.create(
            user=self.owner, platform_account=self.account_a,
            platform_creative_id="creative-client-a", creative_type="IMAGE",
            name="Firma A Kreatifi",
        )
        Creative.objects.create(
            user=self.owner, platform_account=self.account_b,
            platform_creative_id="creative-client-b", creative_type="VIDEO",
            name="Firma B Kreatifi",
        )

        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("creative_center"),
            {"agency_client": str(self.client_a.id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="agency-filter"')
        self.assertEqual([row["id"] for row in response.context["creatives"]], [creative_a.id])
        self.assertEqual(response.context["totals"]["image"], 1)
        self.assertEqual(response.context["totals"]["video"], 0)

        self.client.force_login(self.outsider)
        personal_response = self.client.get(reverse("creative_center"))
        self.assertEqual(personal_response.status_code, 200)
        self.assertNotContains(personal_response, 'class="agency-filter"')

    def test_reports_center_uses_selected_client_accounts(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("reports_center"),
            {"agency_client": str(self.client_b.id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["platform_accounts"], [self.account_b])
        self.assertContains(response, 'class="agency-report-filter"')
        self.assertContains(response, 'name="agency_client"')

        self.client.force_login(self.outsider)
        personal_response = self.client.get(reverse("reports_center"))
        self.assertEqual(personal_response.status_code, 200)
        self.assertNotContains(personal_response, 'class="agency-report-filter"')

    def test_competitor_api_and_detail_endpoints_are_client_isolated(self):
        competitor_a = Competitor.objects.create(
            user=self.owner,
            platform=self.platform,
            platform_account=self.account_a,
            agency_client=self.client_a,
            platform_identifier="firma-a-rakip",
            name="Firma A Rakibi",
        )
        competitor_b = Competitor.objects.create(
            user=self.owner,
            platform=self.platform,
            platform_account=self.account_b,
            agency_client=self.client_b,
            platform_identifier="firma-b-rakip",
            name="Firma B Rakibi",
        )
        competitor_ad_b = Ad.objects.create(
            user=self.owner,
            source_type="COMPETITOR",
            platform_account=self.account_b,
            competitor=competitor_b,
            platform_ad_id="competitor-b-ad",
            name="Firma B Rakip Reklamı",
        )
        own_ad_b = Ad.objects.create(
            user=self.owner,
            source_type="OWN",
            platform_account=self.account_b,
            platform_ad_id="own-b-ad",
            name="Firma B Reklamı",
        )

        self.client.force_login(self.owner)
        list_response = self.client.get(
            reverse("api_rakipler"),
            {"agency_client": str(self.client_a.id)},
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual([row["id"] for row in list_response.json()["rakipler"]], [competitor_a.id])
        self.assertEqual(
            self.client.get(reverse("api_reklam_detay", args=[own_ad_b.id])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("competitor_intelligence_ad_detail_api", args=[competitor_ad_b.id])
            ).status_code,
            404,
        )

    def test_selected_client_campaigns_never_include_sibling_client(self):
        campaign_a = Campaign.objects.create(
            user=self.owner,
            platform_account=self.account_a,
            platform_campaign_id="isolated-a",
            name="Firma A Kampanyası",
        )
        Campaign.objects.create(
            user=self.owner,
            platform_account=self.account_b,
            platform_campaign_id="isolated-b",
            name="Firma B Kampanyası",
        )
        request = self.request(self.owner, {"agency_client": str(self.client_a.id)})

        self.assertEqual(list(scope_queryset(request, Campaign.objects.all())), [campaign_a])

    def test_campaign_center_supports_selected_client_and_all_clients(self):
        campaign_a = Campaign.objects.create(
            user=self.owner,
            platform_account=self.account_a,
            platform_campaign_id="center-a",
            name="Firma A Merkez Kampanyasi",
        )
        campaign_b = Campaign.objects.create(
            user=self.owner,
            platform_account=self.account_b,
            platform_campaign_id="center-b",
            name="Firma B Merkez Kampanyasi",
        )
        self.client.force_login(self.owner)

        selected_response = self.client.get(
            reverse("campaign_center"),
            {"agency_client": str(self.client_a.id)},
        )
        self.assertEqual(selected_response.status_code, 200)
        self.assertContains(selected_response, 'id="campaignCenterAgencyClient"')
        self.assertEqual([row["id"] for row in selected_response.context["campaigns"]], [campaign_a.id])

        all_response = self.client.get(reverse("campaign_center"), {"agency_client": ""})
        self.assertEqual(all_response.status_code, 200)
        self.assertCountEqual(
            [row["id"] for row in all_response.context["campaigns"]],
            [campaign_a.id, campaign_b.id],
        )

    def test_campaign_panel_filter_and_account_api_are_agency_only(self):
        self.client.force_login(self.owner)
        panel_response = self.client.get(
            reverse("campaign_panel"),
            {"agency_client": str(self.client_b.id)},
        )
        self.assertEqual(panel_response.status_code, 200)
        self.assertContains(panel_response, 'id="campaignPanelAgencyClient"')

        selected_accounts = self.client.get(reverse("api_campaign_panel_accounts"))
        selected_ids = [
            account["id"]
            for platform in selected_accounts.json()["platforms"]
            for account in platform["accounts"]
        ]
        self.assertEqual(selected_ids, [self.account_b.id])

        self.client.force_login(self.outsider)
        personal_response = self.client.get(reverse("campaign_panel"))
        self.assertEqual(personal_response.status_code, 200)
        self.assertNotContains(personal_response, 'id="campaignPanelAgencyClient"')

    def test_adgroup_center_scopes_rows_totals_and_filter_visibility(self):
        campaign_a = Campaign.objects.create(
            user=self.owner,
            platform_account=self.account_a,
            platform_campaign_id="adgroup-center-a",
            name="Firma A Kampanyasi",
        )
        campaign_b = Campaign.objects.create(
            user=self.owner,
            platform_account=self.account_b,
            platform_campaign_id="adgroup-center-b",
            name="Firma B Kampanyasi",
        )
        group_a = AdGroup.objects.create(
            user=self.owner,
            campaign=campaign_a,
            platform_adgroup_id="group-a",
            name="Firma A Reklam Grubu",
            status="ACTIVE",
            optimization_goal="CONVERSIONS",
        )
        group_b = AdGroup.objects.create(
            user=self.owner,
            campaign=campaign_b,
            platform_adgroup_id="group-b",
            name="Firma B Reklam Grubu",
            status="PAUSED",
        )
        Ad.objects.create(
            user=self.owner,
            source_type="OWN",
            platform_account=self.account_a,
            campaign=campaign_a,
            ad_group=group_a,
            platform_ad_id="adgroup-center-ad-a",
            name="Firma A Reklami",
        )
        Ad.objects.create(
            user=self.owner,
            source_type="OWN",
            platform_account=self.account_b,
            campaign=campaign_b,
            ad_group=group_b,
            platform_ad_id="adgroup-center-ad-b",
            name="Firma B Reklami",
        )

        self.client.force_login(self.owner)
        selected = self.client.get(
            reverse("adgroup_center"),
            {"agency_client": str(self.client_a.id)},
        )
        self.assertEqual(selected.status_code, 200)
        self.assertContains(selected, 'id="adgroupAgencyClient"')
        self.assertEqual([row["id"] for row in selected.context["adgroups"]], [group_a.id])
        self.assertEqual(selected.context["total_campaigns"], 1)
        self.assertEqual(selected.context["total_ads"], 1)
        self.assertContains(selected, "Aktif")
        self.assertContains(selected, "Dönüşümler")

        all_clients = self.client.get(reverse("adgroup_center"), {"agency_client": ""})
        self.assertCountEqual(
            [row["id"] for row in all_clients.context["adgroups"]],
            [group_a.id, group_b.id],
        )

        self.client.force_login(self.outsider)
        personal = self.client.get(reverse("adgroup_center"))
        self.assertNotContains(personal, 'id="adgroupAgencyClient"')
        self.assertEqual(personal.context["total_adgroups"], 0)

    def test_ads_panel_filter_and_accounts_follow_agency_client(self):
        self.client.force_login(self.owner)
        selected_page = self.client.get(
            reverse("reklam_panel"),
            {"agency_client": str(self.client_a.id)},
        )
        self.assertEqual(selected_page.status_code, 200)
        self.assertContains(selected_page, 'id="adsPanelAgencyClient"')

        selected_api = self.client.get(reverse("api_platform_accounts"))
        selected_ids = [
            account["id"]
            for platform in selected_api.json()["platforms"]
            for account in platform["accounts"]
        ]
        self.assertEqual(selected_ids, [self.account_a.id])

        all_api = self.client.get(reverse("api_platform_accounts"), {"agency_client": ""})
        all_ids = [
            account["id"]
            for platform in all_api.json()["platforms"]
            for account in platform["accounts"]
        ]
        self.assertCountEqual(all_ids, [self.account_a.id, self.account_b.id])

        self.client.force_login(self.outsider)
        personal_page = self.client.get(reverse("reklam_panel"))
        self.assertEqual(personal_page.status_code, 200)
        self.assertNotContains(personal_page, 'id="adsPanelAgencyClient"')

    @override_settings(OPENAI_API_KEY="")
    def test_ad_detail_and_separate_ai_reports_are_persisted_and_scoped(self):
        campaign_a = Campaign.objects.create(
            user=self.owner, platform_account=self.account_a,
            platform_campaign_id="ad-ai-campaign-a", name="AI Kampanyasi A",
        )
        group_a = AdGroup.objects.create(
            user=self.owner, campaign=campaign_a,
            platform_adgroup_id="ad-ai-group-a", name="AI Grubu A",
        )
        creative_a = Creative.objects.create(
            user=self.owner, platform_account=self.account_a,
            platform_creative_id="creative-ai-a", name="AI Kreatifi",
            image_url="https://example.com/creative.jpg", title="Güçlü başlık",
            body_text="Kreatif açıklaması", call_to_action="SHOP_NOW",
        )
        ad_a = Ad.objects.create(
            user=self.owner, source_type="OWN", platform_account=self.account_a,
            campaign=campaign_a, ad_group=group_a, creative=creative_a,
            platform_ad_id="ad-ai-a", name="AI Reklamı A", status="ACTIVE",
        )
        campaign_b = Campaign.objects.create(
            user=self.owner, platform_account=self.account_b,
            platform_campaign_id="ad-ai-campaign-b", name="AI Kampanyasi B",
        )
        ad_b = Ad.objects.create(
            user=self.owner, source_type="OWN", platform_account=self.account_b,
            campaign=campaign_b, platform_ad_id="ad-ai-b", name="AI Reklamı B",
        )
        AdMetricHistory.objects.create(
            ad=ad_a, date="2026-07-13", impressions=1000, clicks=50,
            spend="100.00", conversions="5", conversion_value="400.00",
        )
        rule = OctoTaskRule.objects.create(
            code="ad-ai-rule", module="performance", severity="warning",
            title_tr="Performans kuralı", message_tr="Metrik kontrolü",
            condition_key="ad_ai_rule", priority_score=80,
        )
        OctoTaskInstance.objects.create(
            rule=rule, user=self.owner, ad=ad_a, module="performance",
            severity="warning", title_tr="Reklam performansı",
            message_tr="Mevcut değer: 100.1234", priority_score=80,
        )

        self.client.force_login(self.owner)
        detail = self.client.get(
            reverse("api_ad_detail", args=[ad_a.id]),
            {"agency_client": str(self.client_a.id)},
        )
        self.assertEqual(detail.status_code, 200)
        payload = detail.json()["ad"]
        self.assertEqual(payload["metrics"]["row_count"], 1)
        self.assertEqual(payload["creative"]["headline"], "Güçlü başlık")
        self.assertEqual(payload["matched_rule_count"], 1)
        with patch("core.views.ads_panel.generate_octo_tasks.apply_async") as rule_scan:
            rule_scan.return_value.id = "rule-scan-task-1"
            scan = self.client.post(
                reverse("api_ad_rule_scan", args=[ad_a.id]) + f"?agency_client={self.client_a.id}"
            )
        self.assertEqual(scan.status_code, 200)
        self.assertEqual(scan.json()["status"], "queued")
        scan_kwargs = rule_scan.call_args.kwargs["kwargs"]
        self.assertEqual(scan_kwargs["user_id"], self.owner.id)
        self.assertEqual(scan_kwargs["account_id"], self.account_a.id)
        self.assertEqual(
            self.client.post(
                reverse("api_ad_rule_scan", args=[ad_b.id]) + f"?agency_client={self.client_a.id}"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("api_ad_detail", args=[ad_b.id])).status_code,
            404,
        )

        usage_result = SimpleNamespace(allowed=True, reason="", code="", limit=10, used=0, remaining=10)
        def fake_report(ad, user, report_type, organization=None):
            return ReklamAIAnaliz.objects.create(
                reklam=ad,
                created_by=user,
                report_type=report_type,
                reklam_adi=ad.name,
                Ins_reklam_id=ad.platform_ad_id or str(ad.id),
                overall_score=75,
                analysis_summary="AI analiz sonucu" if report_type == "analysis" else "",
                recommendation_summary="AI öneri sonucu" if report_type == "recommendation" else "",
                agents_results=[],
            )

        with (
            patch("core.views.ads_panel.consume_openai_operation", return_value=usage_result) as consume_mock,
            patch("core.views.ads_panel.generate_ad_report", side_effect=fake_report),
        ):
            analysis = self.client.post(reverse("api_ad_ai_report", args=[ad_a.id, "analysis"]))
            recommendation = self.client.post(reverse("api_ad_ai_report", args=[ad_a.id, "recommendation"]))

        self.assertEqual(analysis.status_code, 200)
        self.assertEqual(recommendation.status_code, 200)
        self.assertEqual(ReklamAIAnaliz.objects.filter(reklam=ad_a, report_type="analysis").count(), 1)
        self.assertEqual(ReklamAIAnaliz.objects.filter(reklam=ad_a, report_type="recommendation").count(), 1)
        reopened = self.client.get(
            reverse("api_ad_detail", args=[ad_a.id]),
            {"agency_client": str(self.client_a.id)},
        )
        self.assertEqual(reopened.status_code, 200)
        saved_reports = reopened.json()["ad"]["latest_reports"]
        self.assertEqual(saved_reports["analysis"]["report_type"], "analysis")
        self.assertEqual(saved_reports["recommendation"]["report_type"], "recommendation")
        self.assertEqual(
            [call.kwargs["operation"] for call in consume_mock.call_args_list],
            [FeatureUsageLedger.OP_OPENAI_ANALYSIS, FeatureUsageLedger.OP_OPENAI_RECOMMENDATION],
        )
