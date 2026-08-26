from __future__ import annotations

import math
import random
from datetime import timedelta
from decimal import Decimal

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import (
    Ad,
    AdGroup,
    AdGroupMetricHistory,
    AdMetricHistory,
    AgencyClient,
    AnalyticsDailyMetric,
    AnalyticsLandingPageMetric,
    AnalyticsProperty,
    AnomalyAlert,
    BudgetOptimizationLog,
    BudgetOptimizationRule,
    Campaign,
    CampaignMetricHistory,
    Creative,
    CreativeMetricHistory,
    Competitor,
    ControlTowerActionItem,
    ControlTowerCardSnapshot,
    ControlTowerDecision,
    ControlTowerSnapshot,
    Marketplace,
    MarketplaceAccount,
    MarketplaceListing,
    MarketplaceListingMetricHistory,
    MarketplaceSyncRun,
    MembershipPlan,
    OpportunityWindow,
    OctoTaskActionLog,
    OctoTaskInstance,
    OctoTaskRule,
    Organization,
    OrganizationMember,
    Platform,
    PlatformAccount,
    PlatformConnection,
    Product,
    ProductVariant,
    RawDataSnapshot,
    SocialPost,
    SocialPostMetricHistory,
    Influencer,
    InfluencerMetricHistory,
    Notification,
    UserAICreditBalance,
    UserProductResearchBalance,
    UserSubscription,
)
from core.services.agency_permission_matrix import all_agency_menu_permission_keys


class Command(BaseCommand):
    help = "Create a complete sales demo user with ad, analytics, agency, anomaly and marketplace data."

    def handle(self, *args, **options):
        random.seed(20260703)
        now = timezone.now()
        today = now.date()

        call_command("seed_platforms", verbosity=0)
        self._ensure_marketplaces()

        with transaction.atomic():
            User = get_user_model()
            Influencer.objects.filter(normalized_handle__startswith="demo_influencer_").delete()
            User.objects.filter(username="demo").delete()
            user = User.objects.create_user(
                username="demo",
                email="demo@reklamanaliz.net",
                password="Demo12345!",
                first_name="Demo",
                last_name="Kullanici",
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )
            EmailAddress.objects.create(
                user=user,
                email=user.email,
                verified=True,
                primary=True,
            )

            plan = self._agency_plan()
            organization = Organization.objects.create(
                name="Demo Ajans",
                owner=user,
                active_plan=plan,
                report_brand_name="Demo Ajans Performans Merkezi",
                report_footer_note="Satış sunumu için oluşturulmuş demo veridir.",
                is_active=True,
            )
            OrganizationMember.objects.create(
                organization=organization,
                user=user,
                role=OrganizationMember.ROLE_OWNER,
                can_manage_clients=True,
                can_manage_accounts=True,
                can_manage_competitors=True,
                can_view_reports=True,
                can_manage_members=True,
                can_manage_billing=True,
                menu_permissions=all_agency_menu_permission_keys(),
                is_active=True,
                invited_email=user.email,
            )
            client = AgencyClient.objects.create(
                organization=organization,
                name="Demo Marka",
                legal_name="Demo Marka Ticaret A.S.",
                website="https://demo.reklamanaliz.net",
                contact_name="Demo Marka Ekibi",
                contact_email="marka@demo.reklamanaliz.net",
                notes="Sunum verileri bu marka altında toplanır.",
                is_active=True,
            )
            subscription = UserSubscription.objects.create(
                user=user,
                organization=organization,
                plan=plan,
                start_date=today - timedelta(days=15),
                end_date=today + timedelta(days=365),
                is_active=True,
                billing_period=UserSubscription.BILLING_MONTHLY,
                next_renewal_date=today + timedelta(days=30),
            )
            UserAICreditBalance.objects.create(
                user=user,
                organization=organization,
                subscription=subscription,
                cycle_start=today.replace(day=1),
                cycle_end=today + timedelta(days=30),
                plan_credits=100000,
                purchased_credits=50000,
                used_credits=12250,
                current_balance=137750,
            )
            UserProductResearchBalance.objects.create(
                user=user,
                organization=organization,
                cycle_start=today.replace(day=1),
                cycle_end=today + timedelta(days=30),
                purchased_units=2500,
                used_units=320,
                current_balance=2180,
            )

            ad_summary = self._create_platform_demo(user, organization, client, now, today)
            marketplace_summary = self._create_marketplace_demo(user, organization, client, subscription, now, today)
            supplemental_summary = self._create_supplemental_demo(user, client, ad_summary, now, today)
            anomaly_count = self._create_anomalies(user, ad_summary["ads"], now)
            opportunity_count = self._create_opportunities(user, now)
            final_summary = self._finalize_demo_presentation(user, subscription)

        self.stdout.write(self.style.SUCCESS("Demo veri olusturuldu."))
        self.stdout.write("Kullanici: demo")
        self.stdout.write("Sifre: Demo12345!")
        self.stdout.write(f"Platform hesabi: {ad_summary['accounts']}")
        self.stdout.write(f"Kampanya: {ad_summary['campaigns']}")
        self.stdout.write(f"Reklam grubu: {ad_summary['ad_groups']}")
        self.stdout.write(f"Reklam: {len(ad_summary['ads'])}")
        self.stdout.write(f"GA4 property/metrik gunu: {ad_summary['ga_properties']}/{ad_summary['ga_days']}")
        self.stdout.write(f"Anomali/Firsat: {anomaly_count}/{opportunity_count}")
        self.stdout.write(f"Pazaryeri hesabi: {marketplace_summary['accounts']}")
        self.stdout.write(f"Pazaryeri urunu: {marketplace_summary['products']}")
        self.stdout.write(f"Pazaryeri metrik gecmisi: {marketplace_summary['history']}")
        self.stdout.write(
            "Ek moduller: "
            f"rakip={supplemental_summary['competitors']}, "
            f"organik={supplemental_summary['social_posts']}, "
            f"influencer={supplemental_summary['influencers']}, "
            f"octo={supplemental_summary['octo_tasks']}, "
            f"control_tower={supplemental_summary['control_tower_items']}, "
            f"bildirim={final_summary['notifications']}, "
            f"raw={supplemental_summary['raw_snapshots']}"
        )

    def _agency_plan(self):
        plan = (
            MembershipPlan.objects.filter(plan_type=MembershipPlan.PLAN_TYPE_AGENCY, is_active=True)
            .order_by("-price")
            .first()
        )
        if plan:
            return plan
        return MembershipPlan.objects.create(
            name="demo_agency",
            display_name="Demo Ajans",
            plan_type=MembershipPlan.PLAN_TYPE_AGENCY,
            price=Decimal("0"),
            price_with_kdv=Decimal("0"),
            features="Demo ajans yetkileri\nSinirsiz sunum verisi",
            order=0,
            is_active=True,
            max_instagram_accounts=9999,
            max_competitors=9999,
            has_analytics=True,
            has_advanced_reporting=True,
            has_team_members=True,
            included_seats=9999,
            max_client_accounts=9999,
            ai_credits_per_month=100000,
            marketplace_product_research_per_month=5000,
            marketplace_price_check_per_month=5000,
        )

    def _create_platform_demo(self, user, organization, client, now, today):
        platform_configs = [
            ("instagram", "Instagram"),
            ("facebook", "Facebook"),
            ("google_ads", "Google Ads"),
            ("tiktok", "TikTok"),
            ("linkedin", "LinkedIn"),
            ("x", "X"),
            ("youtube", "YouTube"),
        ]
        ga_platform = Platform.objects.get(code="google_analytics")

        accounts = 0
        campaigns_count = 0
        ad_groups_count = 0
        ads = []
        ga_days = 0

        ga_connection = self._connection(user, ga_platform, "Demo GA4 Baglantisi", now)
        ga_account = PlatformAccount.objects.create(
            user=user,
            platform=ga_platform,
            connection=ga_connection,
            agency_client=client,
            account_id="demo-ga4-001",
            account_name="Demo GA4 - E-Ticaret",
            access_token="demo-token",
            token_expiry=now + timedelta(days=365),
            is_active=True,
            last_sync=now,
            extra_data={"demo": True, "organization_id": organization.id},
        )
        prop = AnalyticsProperty.objects.create(
            user=user,
            platform_connection=ga_connection,
            platform_account=ga_account,
            property_id="properties/demo-1001",
            property_name="Demo Marka GA4",
            currency="TRY",
            timezone="Europe/Istanbul",
            last_synced_at=now,
            raw_data={"demo": True},
        )
        for offset in range(89, -1, -1):
            date = today - timedelta(days=offset)
            sessions = self._trend_value(4200, offset, 0.18, 650)
            conversions = Decimal(str(round(sessions * random.uniform(0.018, 0.045), 2)))
            revenue = Decimal(str(round(float(conversions) * random.uniform(720, 1680), 2)))
            AnalyticsDailyMetric.objects.create(
                property=prop,
                date=date,
                sessions=sessions,
                users=int(sessions * random.uniform(0.68, 0.82)),
                new_users=int(sessions * random.uniform(0.32, 0.46)),
                engaged_sessions=int(sessions * random.uniform(0.58, 0.74)),
                engagement_rate=Decimal(str(round(random.uniform(0.58, 0.74), 4))),
                bounce_rate=Decimal(str(round(random.uniform(0.26, 0.42), 4))),
                average_session_duration=Decimal(str(round(random.uniform(72, 184), 2))),
                screen_page_views=int(sessions * random.uniform(2.2, 4.6)),
                event_count=int(sessions * random.uniform(6.5, 12.2)),
                key_events=conversions,
                conversions=conversions,
                total_revenue=revenue,
                purchase_revenue=revenue,
                transactions=conversions,
                average_purchase_revenue=Decimal(str(round(float(revenue) / max(float(conversions), 1), 2))),
                raw_metrics={"demo": True},
            )
            for landing in ["/", "/urunler/demo-canta", "/kampanya/yaz-firsatlari"]:
                lp_sessions = int(sessions * random.uniform(0.12, 0.32))
                AnalyticsLandingPageMetric.objects.create(
                    property=prop,
                    date=date,
                    landing_page=landing,
                    landing_page_title=f"Demo {landing}",
                    sessions=lp_sessions,
                    users=int(lp_sessions * random.uniform(0.7, 0.9)),
                    new_users=int(lp_sessions * random.uniform(0.3, 0.55)),
                    engaged_sessions=int(lp_sessions * random.uniform(0.52, 0.76)),
                    engagement_rate=Decimal(str(round(random.uniform(0.52, 0.76), 4))),
                    bounce_rate=Decimal(str(round(random.uniform(0.24, 0.48), 4))),
                    conversions=Decimal(str(round(lp_sessions * random.uniform(0.012, 0.04), 2))),
                    total_revenue=Decimal(str(round(lp_sessions * random.uniform(18, 62), 2))),
                    raw_metrics={"demo": True},
                )
            ga_days += 1

        for code, label in platform_configs:
            platform = Platform.objects.get(code=code)
            connection = self._connection(user, platform, f"Demo {label} Baglantisi", now)
            rule = BudgetOptimizationRule.objects.create(
                user=user,
                platform=platform,
                name=f"{label} ROAS Koruma",
                min_budget=Decimal("250.00"),
                max_budget=Decimal("7500.00"),
                adjustment_step=Decimal("12.50"),
                roas_target=2.6,
                lookback_hours=72,
                is_active=True,
            )
            for account_no in range(1, 3):
                account = PlatformAccount.objects.create(
                    user=user,
                    platform=platform,
                    connection=connection,
                    agency_client=client,
                    account_id=f"demo-{code}-{account_no:02d}",
                    account_name=f"{label} Demo Hesap {account_no}",
                    access_token="demo-token",
                    token_expiry=now + timedelta(days=365),
                    is_active=True,
                    last_sync=now,
                    extra_data={"demo": True, "spend_tier": account_no},
                )
                accounts += 1
                for campaign_no in range(1, 3):
                    campaign = Campaign.objects.create(
                        user=user,
                        platform_connection=connection,
                        platform_account=account,
                        platform_campaign_id=f"{account.account_id}-cmp-{campaign_no}",
                        name=f"{label} {account_no}. Hesap Kampanya {campaign_no}",
                        objective=random.choice(["SALES", "TRAFFIC", "LEADS", "ENGAGEMENT"]),
                        status="ACTIVE",
                        daily_budget=Decimal(str(650 + account_no * 180 + campaign_no * 95)),
                        currency="TRY",
                        start_time=now - timedelta(days=92),
                        last_synced_at=now,
                        raw_data={"demo": True},
                    )
                    campaigns_count += 1
                    ad_group = AdGroup.objects.create(
                        user=user,
                        campaign=campaign,
                        platform_adgroup_id=f"{campaign.platform_campaign_id}-grp-1",
                        name="Grup 1",
                        status="ACTIVE",
                        optimization_goal="CONVERSIONS",
                        billing_event="IMPRESSIONS",
                        daily_budget=campaign.daily_budget,
                        targeting={"age": "24-44", "locations": ["TR"], "interests": ["e-ticaret", "moda", "teknoloji"]},
                        placements={"feed": True, "story": True, "search": code in {"google_ads", "youtube"}},
                        start_time=campaign.start_time,
                        last_synced_at=now,
                    )
                    ad_groups_count += 1
                    campaign_daily = []
                    ad_group_daily = []
                    for ad_no in range(1, 3):
                        creative = Creative.objects.create(
                            user=user,
                            platform_connection=connection,
                            platform_account=account,
                            platform_creative_id=f"{campaign.platform_campaign_id}-crt-{ad_no}",
                            creative_type=random.choice(["IMAGE", "VIDEO", "CAROUSEL", "REELS"]),
                            name=f"{label} Kreatif {account_no}-{campaign_no}-{ad_no}",
                            title=random.choice(["Yeni sezon firsatlari", "Bugune ozel indirim", "Premium koleksiyon", "Hizli teslimat"]),
                            body_text="Demo kampanya kreatifi: net teklif, guclu gorsel ve satis odakli mesaj.",
                            call_to_action=random.choice(["SHOP_NOW", "LEARN_MORE", "SIGN_UP", "CONTACT_US"]),
                            image_url=f"https://picsum.photos/seed/{code}-{account_no}-{campaign_no}-{ad_no}/900/900",
                            landing_url="https://demo.reklamanaliz.net/kampanya",
                            media_hash=f"demo-{code}-{account_no}-{campaign_no}-{ad_no}",
                            raw_data={"demo": True},
                            first_seen_at=now - timedelta(days=90),
                            last_seen_at=now,
                        )
                        ad = Ad.objects.create(
                            user=user,
                            source_type="OWN",
                            platform_connection=connection,
                            platform_account=account,
                            campaign=campaign,
                            ad_group=ad_group,
                            creative=creative,
                            platform_ad_id=f"{campaign.platform_campaign_id}-ad-{ad_no}",
                            name=f"{label} Reklam {account_no}-{campaign_no}-{ad_no}",
                            status="ACTIVE",
                            ad_format=creative.creative_type,
                            objective=campaign.objective,
                            headline=creative.title,
                            primary_text=creative.body_text,
                            call_to_action=creative.call_to_action,
                            landing_url=creative.landing_url,
                            preview_image_url=creative.image_url,
                            first_seen_at=now - timedelta(days=90),
                            last_seen_at=now,
                            started_at=now - timedelta(days=90),
                            raw_data={"demo": True},
                            last_synced_at=now,
                        )
                        ads.append(ad)
                        ad_daily = []
                        for offset in range(89, -1, -1):
                            date = today - timedelta(days=offset)
                            metrics = self._ad_metrics(offset, ad_no, campaign_no, account_no)
                            AdMetricHistory.objects.create(ad=ad, date=date, **metrics)
                            CreativeMetricHistory.objects.create(
                                creative=creative,
                                date=date,
                                thumbstop_rate=Decimal(str(round(random.uniform(0.22, 0.58), 4))),
                                hook_rate=Decimal(str(round(random.uniform(0.18, 0.46), 4))),
                                hold_rate=Decimal(str(round(random.uniform(0.12, 0.38), 4))),
                                **metrics,
                            )
                            ad_daily.append(metrics)
                        for day_idx in range(90):
                            campaign_daily.append((day_idx, ad_daily[day_idx]))
                            ad_group_daily.append((day_idx, ad_daily[day_idx]))
                        BudgetOptimizationLog.objects.create(
                            user=user,
                            reklam=ad,
                            platform_code=platform.code,
                            rule=rule,
                            old_budget=Decimal(str(500 + random.randint(20, 180))),
                            new_budget=Decimal(str(650 + random.randint(80, 260))),
                            reason="ROAS hedefe yaklastigi icin demo otomatik butce artisi.",
                            ai_confidence=0.0,
                            success=True,
                            performance_data={"demo": True, "roas": float(random.uniform(2.2, 4.8))},
                        )
                    self._rollup_history(campaign, ad_group, campaign_daily, ad_group_daily, today)

        return {
            "accounts": accounts + 1,
            "campaigns": campaigns_count,
            "ad_groups": ad_groups_count,
            "ads": ads,
            "ga_properties": 1,
            "ga_days": ga_days,
        }

    def _connection(self, user, platform, name, now):
        return PlatformConnection.objects.create(
            user=user,
            platform=platform,
            name=name,
            access_token="demo-token",
            refresh_token="demo-refresh",
            token_expiry=now + timedelta(days=365),
            scopes=["read", "ads_read", "analytics"],
            status="active",
            last_sync=now,
            extra_data={"demo": True},
            is_active=True,
        )

    def _ad_metrics(self, offset, ad_no, campaign_no, account_no):
        wave = 1 + math.sin(offset / 8.0 + ad_no) * 0.13
        anomaly_boost = 1.45 if offset in {18, 43, 71} and ad_no == 1 else 1
        impressions = max(120, int((1600 + account_no * 420 + campaign_no * 260 + random.randint(-180, 220)) * wave * anomaly_boost))
        ctr_float = max(0.004, random.uniform(0.009, 0.043) * (0.55 if offset in {30, 61} and ad_no == 2 else 1))
        clicks = max(1, int(impressions * ctr_float))
        spend = Decimal(str(round((impressions / 1000) * random.uniform(28, 86), 2)))
        conversions = Decimal(str(round(clicks * random.uniform(0.018, 0.082), 2)))
        conv_value = Decimal(str(round(float(conversions) * random.uniform(520, 1750), 2)))
        cpc = Decimal(str(round(float(spend) / max(clicks, 1), 4)))
        cpm = Decimal(str(round(float(spend) / max(impressions, 1) * 1000, 4)))
        roas = Decimal(str(round(float(conv_value) / max(float(spend), 1), 4)))
        engagement = int(impressions * random.uniform(0.018, 0.075))
        return {
            "impressions": impressions,
            "reach": int(impressions * random.uniform(0.62, 0.86)),
            "frequency": Decimal(str(round(random.uniform(1.05, 2.75), 4))),
            "clicks": clicks,
            "link_clicks": int(clicks * random.uniform(0.72, 0.92)),
            "unique_clicks": int(clicks * random.uniform(0.64, 0.86)),
            "spend": spend,
            "currency": "TRY",
            "ctr": Decimal(str(round(ctr_float * 100, 4))),
            "cpc": cpc,
            "cpm": cpm,
            "conversions": conversions,
            "conversion_value": conv_value,
            "cost_per_conversion": Decimal(str(round(float(spend) / max(float(conversions), 1), 4))),
            "purchases": conversions,
            "add_to_cart": Decimal(str(round(float(conversions) * random.uniform(1.8, 4.2), 2))),
            "initiate_checkout": Decimal(str(round(float(conversions) * random.uniform(1.2, 2.3), 2))),
            "leads": Decimal(str(round(clicks * random.uniform(0.02, 0.11), 2))),
            "landing_page_views": int(clicks * random.uniform(0.55, 0.82)),
            "outbound_clicks": int(clicks * random.uniform(0.42, 0.77)),
            "roas": roas,
            "likes": int(engagement * random.uniform(0.42, 0.68)),
            "comments": int(engagement * random.uniform(0.04, 0.14)),
            "shares": int(engagement * random.uniform(0.05, 0.18)),
            "saves": int(engagement * random.uniform(0.08, 0.22)),
            "video_views": int(impressions * random.uniform(0.12, 0.48)),
            "engagement": engagement,
            "engagement_rate": Decimal(str(round(engagement / max(impressions, 1) * 100, 4))),
            "raw_metrics": {"demo": True},
        }

    def _rollup_history(self, campaign, ad_group, campaign_daily, ad_group_daily, today):
        for day_idx in range(90):
            date = today - timedelta(days=89 - day_idx)
            metrics = [item for idx, item in campaign_daily if idx == day_idx]
            rolled = self._sum_metrics(metrics)
            CampaignMetricHistory.objects.create(campaign=campaign, date=date, **rolled)
            AdGroupMetricHistory.objects.create(ad_group=ad_group, date=date, **rolled)

    def _sum_metrics(self, metrics):
        integer_fields = [
            "impressions", "reach", "clicks", "link_clicks", "unique_clicks", "landing_page_views",
            "outbound_clicks", "likes", "comments", "shares", "saves", "video_views", "engagement",
        ]
        decimal_fields = [
            "spend", "conversions", "conversion_value", "purchases", "add_to_cart", "initiate_checkout", "leads",
        ]
        data = {field: sum(int(m[field]) for m in metrics) for field in integer_fields}
        data.update({field: sum((m[field] for m in metrics), Decimal("0")) for field in decimal_fields})
        data["currency"] = "TRY"
        data["frequency"] = Decimal(str(round(sum(float(m["frequency"]) for m in metrics) / len(metrics), 4)))
        data["ctr"] = Decimal(str(round(data["clicks"] / max(data["impressions"], 1) * 100, 4)))
        data["cpc"] = Decimal(str(round(float(data["spend"]) / max(data["clicks"], 1), 4)))
        data["cpm"] = Decimal(str(round(float(data["spend"]) / max(data["impressions"], 1) * 1000, 4)))
        data["cost_per_conversion"] = Decimal(str(round(float(data["spend"]) / max(float(data["conversions"]), 1), 4)))
        data["roas"] = Decimal(str(round(float(data["conversion_value"]) / max(float(data["spend"]), 1), 4)))
        data["engagement_rate"] = Decimal(str(round(data["engagement"] / max(data["impressions"], 1) * 100, 4)))
        data["raw_metrics"] = {"demo": True, "rolled_up": True}
        return data

    def _ensure_marketplaces(self):
        rows = [
            ("trendyol", "Trendyol", 1),
            ("hepsiburada", "Hepsiburada", 2),
            ("n11", "n11", 3),
        ]
        Marketplace.objects.exclude(code__in=[code for code, _, _ in rows]).update(is_active=False)
        for code, name, order in rows:
            Marketplace.objects.update_or_create(
                code=code,
                defaults={"name": name, "order": order, "is_active": True},
            )

    def _create_marketplace_demo(self, user, organization, client, subscription, now, today):
        product_names = [
            "Akilli Saat", "Kablosuz Kulaklik", "Sirt Cantasi", "Termos", "Spor Ayakkabi",
            "Yoga Mati", "Kahve Seti", "LED Masa Lambasi", "Telefon Kilifi", "Bluetooth Hoparlor",
            "Cilt Bakim Serumu", "Organik T-Shirt", "Laptop Standi", "Oyuncu Mouse", "Mini Projektor",
            "Mutfak Tartisi", "Seyahat Valizi", "Gunes Gozlugu", "Bebek Bakim Seti", "Kedi Mamasi",
        ]
        accounts = 0
        products = 0
        history = 0
        for marketplace in Marketplace.objects.filter(is_active=True).order_by("order", "name"):
            account = MarketplaceAccount.objects.create(
                marketplace=marketplace,
                user=user,
                organization=organization,
                subscription=subscription,
                agency_client=client,
                store_name=f"Demo {marketplace.name} Magazasi",
                seller_id=f"demo-{marketplace.code}-seller",
                api_key_encrypted="demo-key",
                api_secret_encrypted="demo-secret",
                extra_credentials={"demo": True},
                sync_mode=MarketplaceAccount.SYNC_MODE_SALES_READY,
                sync_product_limit=250,
                is_active=True,
                last_sync_at=now,
            )
            accounts += 1
            sync_run = MarketplaceSyncRun.objects.create(
                marketplace_account=account,
                sync_type=MarketplaceSyncRun.SYNC_TYPE_CATALOG,
                status=MarketplaceSyncRun.STATUS_SUCCESS,
                requested_by=user,
                product_limit=250,
                fetched_count=20,
                created_count=20,
                started_at=now - timedelta(minutes=12),
                finished_at=now - timedelta(minutes=2),
            )
            for idx, base_name in enumerate(product_names, start=1):
                sku = f"{marketplace.code.upper()}-DEMO-{idx:03d}"
                purchase = Decimal(str(round(random.uniform(120, 920), 2)))
                sale = Decimal(str(round(float(purchase) * random.uniform(1.45, 2.35), 2)))
                product = Product.objects.create(
                    user=user,
                    organization=organization,
                    subscription=subscription,
                    agency_client=client,
                    sku=sku,
                    barcode=f"869{random.randint(1000000000, 9999999999)}",
                    name=f"{base_name} - {marketplace.name}",
                    description="Demo satis sunumu icin olusturulmus urun.",
                    brand=random.choice(["DemoMax", "OctoBrand", "Nexus", "PazarPlus"]),
                    category_name=random.choice(["Elektronik", "Moda", "Ev Yasam", "Kozmetik", "Spor"]),
                    image_url=f"https://picsum.photos/seed/{marketplace.code}-{idx}/800/800",
                    purchase_price=purchase,
                    default_sale_price=sale,
                    weight_kg=Decimal(str(round(random.uniform(0.2, 4.5), 3))),
                    width_cm=Decimal(str(round(random.uniform(8, 40), 2))),
                    height_cm=Decimal(str(round(random.uniform(4, 30), 2))),
                    length_cm=Decimal(str(round(random.uniform(10, 55), 2))),
                )
                variant = ProductVariant.objects.create(
                    product=product,
                    sku=f"{sku}-STD",
                    barcode=product.barcode,
                    color=random.choice(["Siyah", "Beyaz", "Mavi", "Yesil", "Gri"]),
                    size=random.choice(["STD", "M", "L", "XL"]),
                    purchase_price=purchase,
                )
                listing = MarketplaceListing.objects.create(
                    marketplace_account=account,
                    marketplace=marketplace,
                    product=product,
                    variant=variant,
                    platform_product_id=f"{marketplace.code}-{idx:04d}",
                    platform_sku=sku,
                    platform_barcode=product.barcode,
                    platform_category_name=product.category_name,
                    platform_url=f"https://demo.reklamanaliz.net/{marketplace.code}/urun/{idx}",
                    platform_brand=product.brand,
                    platform_image_url=product.image_url,
                    platform_description=product.description,
                    sale_price=sale,
                    discounted_price=Decimal(str(round(float(sale) * random.uniform(0.86, 0.97), 2))),
                    stock=random.randint(18, 240),
                    commission_rate=Decimal(str(round(random.uniform(8, 18), 2))),
                    cargo_company=random.choice(["Yurtici", "Aras", "MNG", "Sendeo"]),
                    estimated_delivery_days=random.randint(1, 4),
                    rating_average=Decimal(str(round(random.uniform(4.1, 4.9), 2))),
                    rating_count=random.randint(20, 900),
                    review_count=random.randint(8, 240),
                    favorite_count=random.randint(40, 2600),
                    view_count=random.randint(500, 45000),
                    buybox_rank=random.randint(1, 4),
                    last_synced_at=now,
                    raw_payload={"demo": True},
                )
                products += 1
                previous_price = listing.discounted_price
                for offset in range(89, -1, -1):
                    date = today - timedelta(days=offset)
                    price_shift = Decimal(str(round(math.sin(offset / 9.0) * 7 + random.uniform(-5, 9), 2)))
                    discounted = max(Decimal("10.00"), listing.discounted_price + price_shift)
                    orders = random.randint(0, 18) + (5 if offset in {12, 38, 66} else 0)
                    units = orders + random.randint(0, 5)
                    revenue = Decimal(str(round(float(discounted) * units, 2)))
                    gross_profit = discounted - purchase
                    margin = Decimal(str(round(float(gross_profit) / max(float(discounted), 1) * 100, 4)))
                    MarketplaceListingMetricHistory.objects.create(
                        listing=listing,
                        marketplace_account=account,
                        marketplace=marketplace,
                        product=product,
                        variant=variant,
                        date=date,
                        sale_price=listing.sale_price,
                        discounted_price=discounted,
                        purchase_price=purchase,
                        commission_rate=listing.commission_rate,
                        stock=max(0, listing.stock - (89 - offset) // 3 + random.randint(-3, 4)),
                        status=MarketplaceListing.STATUS_ACTIVE,
                        gross_profit=gross_profit,
                        gross_margin_rate=margin,
                        orders=orders,
                        units_sold=units,
                        revenue=revenue,
                        view_count=random.randint(80, 2400),
                        favorite_count=random.randint(3, 110),
                        review_count=random.randint(0, 8),
                        return_count=random.randint(0, max(1, orders // 8)),
                        buybox_rank=random.randint(1, 5),
                        raw_metrics={"demo": True, "previous_price": str(previous_price)},
                        sync_run=sync_run,
                    )
                    history += 1
        return {"accounts": accounts, "products": products, "history": history}

    def _create_supplemental_demo(self, user, client, ad_summary, now, today):
        ads = ad_summary["ads"]
        accounts = list(PlatformAccount.objects.filter(user=user).select_related("platform", "connection"))
        platform_priority = {
            "instagram": 0,
            "facebook": 1,
            "google_ads": 2,
            "tiktok": 3,
            "linkedin": 4,
            "x": 5,
            "youtube": 6,
        }
        ad_accounts = sorted(
            [account for account in accounts if account.platform.code != "google_analytics"],
            key=lambda account: (
                platform_priority.get(account.platform.code, 99),
                account.account_name or account.account_id or "",
            ),
        )
        competitors = 0
        social_posts = 0
        influencers = 0
        octo_tasks = 0
        control_tower_items = 0
        notifications = 0
        raw_snapshots = 0

        # Canlıda rakip reklam verisi yalnız gerçek sağlayıcıdan yazılır.
        # Demo/sentetik rakip reklam üretmek kullanıcıyı yanıltacağı için kapalı tutulur.
        competitor_ads = []

        for idx, account in enumerate(ad_accounts[:10], start=1):
            for post_no in range(1, 4):
                post = SocialPost.objects.create(
                    user=user,
                    platform_connection=account.connection,
                    platform_account=account,
                    competitor=random.choice(competitor_ads) if competitor_ads else None,
                    platform_post_id=f"demo-post-{account.account_id}-{post_no}",
                    post_type=random.choice(["IMAGE", "VIDEO", "CAROUSEL", "REELS", "SHORTS"]),
                    caption=f"{account.platform.name} organik demo paylasim {post_no}: kampanya ve topluluk etkilesimi.",
                    permalink=f"https://demo.reklamanaliz.net/social/{account.account_id}/{post_no}",
                    image_url=f"https://picsum.photos/seed/social-{idx}-{post_no}/900/900",
                    posted_at=now - timedelta(days=random.randint(3, 80)),
                    raw_data={"demo": True},
                    last_synced_at=now,
                    is_active=True,
                )
                social_posts += 1
                for offset in range(89, -1, -1):
                    date = today - timedelta(days=offset)
                    impressions = self._trend_value(1200 + idx * 80, offset, 0.12, 180)
                    engagement = int(impressions * random.uniform(0.025, 0.095))
                    SocialPostMetricHistory.objects.create(
                        social_post=post,
                        date=date,
                        impressions=impressions,
                        reach=int(impressions * random.uniform(0.65, 0.9)),
                        likes=int(engagement * random.uniform(0.55, 0.75)),
                        comments=int(engagement * random.uniform(0.05, 0.16)),
                        shares=int(engagement * random.uniform(0.04, 0.15)),
                        saves=int(engagement * random.uniform(0.08, 0.22)),
                        video_views=int(impressions * random.uniform(0.1, 0.5)),
                        profile_visits=int(impressions * random.uniform(0.006, 0.028)),
                        website_clicks=int(impressions * random.uniform(0.004, 0.02)),
                        engagement=engagement,
                        engagement_rate=Decimal(str(round(engagement / max(impressions, 1) * 100, 4))),
                        raw_metrics={"demo": True},
                    )

        categories = ["fashion", "beauty", "food", "travel", "technology", "fitness", "business", "lifestyle"]
        influencer_platforms = [account.platform for account in ad_accounts[:4]]
        for idx in range(1, 17):
            platform = influencer_platforms[idx % len(influencer_platforms)]
            follower_count = random.randint(18000, 650000)
            influencer = Influencer.objects.create(
                platform=platform,
                handle=f"@demo_influencer_{idx}",
                normalized_handle=f"demo_influencer_{idx}",
                display_name=f"Demo Influencer {idx}",
                profile_url=f"https://demo.reklamanaliz.net/influencer/{idx}",
                category=random.choice(categories),
                country="TR",
                city=random.choice(["Istanbul", "Ankara", "Izmir", "Bursa", "Antalya"]),
                language="tr",
                follower_count=follower_count,
                following_count=random.randint(250, 2200),
                post_count=random.randint(80, 1600),
                avg_likes=int(follower_count * random.uniform(0.012, 0.055)),
                avg_comments=int(follower_count * random.uniform(0.0008, 0.006)),
                avg_views=int(follower_count * random.uniform(0.12, 0.58)),
                engagement_rate=Decimal(str(round(random.uniform(1.4, 7.8), 4))),
                estimated_reach=int(follower_count * random.uniform(0.18, 0.62)),
                estimated_price_min=Decimal(str(round(follower_count * random.uniform(0.012, 0.028), 2))),
                estimated_price_max=Decimal(str(round(follower_count * random.uniform(0.035, 0.07), 2))),
                is_verified=idx % 5 == 0,
                source="manual",
                notes="Demo influencer havuzu kaydi.",
                contact_email=f"influencer{idx}@demo.reklamanaliz.net",
                created_by=user,
            )
            influencers += 1
            for offset in range(89, -1, -1):
                date = today - timedelta(days=offset)
                growth = int(follower_count * (1 - offset / 8000) + random.randint(-80, 140))
                InfluencerMetricHistory.objects.create(
                    influencer=influencer,
                    date=date,
                    follower_count=max(1000, growth),
                    following_count=influencer.following_count,
                    post_count=influencer.post_count + (89 - offset) // 7,
                    avg_likes=max(1, int(influencer.avg_likes * random.uniform(0.85, 1.18))),
                    avg_comments=max(1, int(influencer.avg_comments * random.uniform(0.82, 1.22))),
                    avg_views=max(1, int(influencer.avg_views * random.uniform(0.8, 1.25))),
                    engagement_rate=Decimal(str(round(float(influencer.engagement_rate) * random.uniform(0.85, 1.16), 4))),
                    estimated_reach=max(1, int(influencer.estimated_reach * random.uniform(0.86, 1.2))),
                    raw_metrics={"demo": True},
                )

        task_specs = [
            ("demo_ctr_drop", "performance", "critical", "CTR dususu kontrol edilmeli"),
            ("demo_budget_scale", "budget", "opportunity", "ROAS iyi, butce artisi denenebilir"),
            ("demo_creative_fatigue", "creative", "warning", "Kreatif yorgunlugu sinyali var"),
            ("demo_conversion_gap", "conversion", "info", "Checkout adiminda kayip izlenmeli"),
        ]
        for idx, (code, module, severity, title) in enumerate(task_specs):
            rule, _ = OctoTaskRule.objects.update_or_create(
                code=code,
                defaults={
                    "module": module,
                    "severity": severity,
                    "title_tr": title,
                    "message_tr": "Demo gorev kuralindan uretildi.",
                    "action_text_tr": "Incele",
                    "condition_key": code,
                    "priority_score": 95 - idx * 8,
                    "is_active": True,
                },
            )
            ad = ads[idx % len(ads)]
            task = OctoTaskInstance.objects.create(
                rule=rule,
                user=user,
                platform_connection=ad.platform_connection,
                platform_account=ad.platform_account,
                campaign=ad.campaign,
                ad_group=ad.ad_group,
                ad=ad,
                creative=ad.creative,
                module=module,
                severity=severity,
                title_tr=title,
                message_tr="Demo kullanici icin gercek metriklerden uretilmis gorev senaryosu.",
                action_text_tr="Aksiyona git",
                status=random.choice(["open", "viewed", "open", "snoozed"]),
                priority_score=95 - idx * 8,
                detected_value=Decimal(str(round(random.uniform(1.2, 6.8), 4))),
                previous_value=Decimal(str(round(random.uniform(1.5, 5.2), 4))),
                change_percent=Decimal(str(round(random.uniform(-48, 82), 2))),
                source_period_start=today - timedelta(days=7),
                source_period_end=today,
                unique_key=f"demo-{code}-{user.id}",
            )
            OctoTaskActionLog.objects.create(task=task, user=user, action="viewed", note="Demo gorev incelendi.")
            octo_tasks += 1

        snapshot = ControlTowerSnapshot.objects.create(
            user=user,
            period=ControlTowerSnapshot.PERIOD_QUARTERLY,
            date_from=today - timedelta(days=89),
            date_to=today,
            snapshot_date=now,
            octo_score=82,
            summary={"demo": True, "spend": 420000, "revenue": 1380000, "roas": 3.29},
            decision_center={"open": 4, "applied": 2, "expected_gain": 186000},
            source_version="demo_seed_v1",
        )
        card_specs = [
            (ControlTowerCardSnapshot.CARD_KPI, "KPI Ozeti", 84, "success"),
            (ControlTowerCardSnapshot.CARD_DECISION, "Karar Merkezi", 81, "warning"),
            (ControlTowerCardSnapshot.CARD_TASK, "Octo Gorevleri", 78, "warning"),
            (ControlTowerCardSnapshot.CARD_ALERT, "Kritik Uyarilar", 72, "critical"),
            (ControlTowerCardSnapshot.CARD_CAMPAIGN_HEALTH, "Kampanya Sagligi", 86, "stable"),
            (ControlTowerCardSnapshot.CARD_CREATIVE, "Kreatif Performans", 76, "warning"),
            (ControlTowerCardSnapshot.CARD_PLATFORM, "Platform Durumu", 92, "success"),
        ]
        for key, title, score, status in card_specs:
            ControlTowerCardSnapshot.objects.create(
                snapshot=snapshot,
                card_key=key,
                title_tr=title,
                title_en=title,
                status=status,
                score=score,
                payload={"demo": True, "score": score},
            )
            control_tower_items += 1
        for idx in range(1, 6):
            ControlTowerActionItem.objects.create(
                snapshot=snapshot,
                user=user,
                card_key=random.choice([item[0] for item in card_specs]),
                title_tr=f"Demo aksiyon {idx}",
                title_en=f"Demo action {idx}",
                description_tr="Satış sunumunda uygulanabilir aksiyon kartı.",
                expected_impact=Decimal(str(18000 + idx * 9500)),
                priority=random.choice(["medium", "high", "critical"]),
                status=ControlTowerActionItem.STATUS_PENDING,
                action_payload={"demo": True},
            )
            ControlTowerDecision.objects.create(
                snapshot=snapshot,
                user=user,
                title_tr=f"Demo karar {idx}",
                title_en=f"Demo decision {idx}",
                reason_tr="Metrik sinyalleri karar merkezinde aksiyona donusturuldu.",
                expected_gain=Decimal(str(22000 + idx * 12000)),
                priority=random.choice(["medium", "high", "critical"]),
                status=ControlTowerDecision.STATUS_OPEN,
                payload={"demo": True},
                analysis_type="demo_operational",
                what_happened="Performans sinyali anlamli fark yaratti.",
                root_cause="Butce dagilimi ve kreatif frekansi etkili oldu.",
                forecast="Aksiyon alinmazsa verimlilik azalabilir.",
                action_plan="Butceyi iyi ROAS ureten sete kaydir.",
                expected_impact="Gelir ve ROAS artisi beklenir.",
                expected_revenue_gain=Decimal(str(22000 + idx * 12000)),
                expected_roas_change=Decimal("0.24"),
                expected_ctr_change=Decimal("0.18"),
            )
            control_tower_items += 2

        for idx, (level, title) in enumerate([
            ("critical", "CTR kritik seviyeye indi"),
            ("warning", "Kreatif yorgunlugu algilandi"),
            ("info", "Pazaryeri fiyat takibi tamamlandi"),
            ("success", "Platform senkronizasyonu basarili"),
        ], start=1):
            Notification.objects.create(
                user=user,
                title=title,
                message="Demo satis sunumu icin olusturulmus bildirim.",
                level=level,
                icon="bell",
                link="/dashboard/",
                is_read=idx % 2 == 0,
            )
            notifications += 1

        snapshot_accounts = ad_accounts[:6]
        for account in snapshot_accounts:
            RawDataSnapshot.objects.create(
                user=user,
                platform=account.platform,
                platform_account=account,
                platform_connection=account.connection,
                source_type="ACCOUNT",
                status="SUCCESS",
                external_id=account.account_id,
                request_url=f"https://api.demo/{account.platform.code}/accounts/{account.account_id}",
                response_status_code=200,
                payload={"demo": True, "account": account.account_name},
                checksum=f"demo-{account.account_id}",
                fetched_at=now - timedelta(minutes=random.randint(5, 90)),
            )
            raw_snapshots += 1
        for ad in ads[:12]:
            RawDataSnapshot.objects.create(
                user=user,
                platform=ad.platform_account.platform if ad.platform_account else None,
                platform_account=ad.platform_account,
                platform_connection=ad.platform_connection,
                campaign=ad.campaign,
                ad_group=ad.ad_group,
                ad=ad,
                creative=ad.creative,
                source_type="AD",
                status="SUCCESS",
                external_id=ad.platform_ad_id,
                external_parent_id=ad.campaign.platform_campaign_id if ad.campaign else "",
                response_status_code=200,
                payload={"demo": True, "ad": ad.name},
                checksum=f"demo-{ad.platform_ad_id}",
                fetched_at=now - timedelta(minutes=random.randint(5, 90)),
            )
            raw_snapshots += 1

        return {
            "competitors": competitors,
            "social_posts": social_posts,
            "influencers": influencers,
            "octo_tasks": octo_tasks,
            "control_tower_items": control_tower_items,
            "notifications": notifications,
            "raw_snapshots": raw_snapshots,
        }

    def _create_anomalies(self, user, ads, now):
        scenarios = [
            ("spend_spike", "Ani harcama artisi", "Dun gece butce tuketimi normalin uzerine cikti.", 1200, 2450, 104),
            ("spend_drop", "Harcama dususu", "Aktif kampanyada harcama hizli dustu.", 1850, 620, -66),
            ("impression_spike", "Gosterim patlamasi", "Kreatif gosterimleri beklenen seviyenin uzerine cikti.", 22000, 51000, 132),
            ("ctr_change", "CTR kritik degisim", "CTR son 24 saatte belirgin sekilde geriledi.", 3.8, 1.2, -68),
            ("new_campaign", "Yeni kampanya yayinda", "Yeni demo kampanya veri toplamaya basladi.", 0, 1, 100),
            ("budget_increase", "Butce artisi", "ROAS iyi oldugu icin butce artisi firsati olustu.", 750, 1100, 46),
            ("opportunity", "Dusuk maliyet firsati", "CPC dusuk, hacim artisi icin uygun pencere var.", 4.2, 2.1, -50),
            ("gap_detected", "Hedef kitle boslugu", "25-34 yas segmentinde rakiplere gore dusuk kapsama goruldu.", 68, 41, -39),
        ]
        for idx, (kind, title, desc, old, new, change) in enumerate(scenarios):
            AnomalyAlert.objects.create(
                user=user,
                rakip=ads[idx % len(ads)],
                alert_type=kind,
                severity=random.choice(["medium", "high", "critical"]),
                title=title,
                description=desc,
                old_value=old,
                new_value=new,
                change_percent=change,
                suggested_action="Demo sunumunda bu kart uzerinden aksiyon onerisi anlatilabilir.",
                action_link="/dashboard/",
                is_read=False,
                is_dismissed=False,
            )
        return len(scenarios)

    def _create_opportunities(self, user, now):
        scenarios = [
            ("low_competition", "Dusuk rekabetli hedefleme"),
            ("high_demand", "Yuksek talep sinyali"),
            ("budget_gap", "Butce boslugu"),
            ("time_window", "Aksam saatleri firsati"),
            ("audience_gap", "Yeni hedef kitle boslugu"),
            ("location_gap", "Bolgesel buyume firsati"),
            ("hashtag_trend", "Trend etiket ivmesi"),
        ]
        for idx, (kind, title) in enumerate(scenarios):
            OpportunityWindow.objects.create(
                user=user,
                opportunity_type=kind,
                title=title,
                description="Demo veri setinde satis sunumu icin olusturulmus firsat senaryosu.",
                estimated_savings=Decimal(str(800 + idx * 275)),
                estimated_reach=25000 + idx * 8500,
                confidence_score=74 + idx * 3,
                expires_at=now + timedelta(days=7 + idx),
                suggested_action="Kampanya butcesini kontrollu artir ve kreatif varyant testini baslat.",
                action_link="/dashboard/",
            )
        return len(scenarios)

    def _finalize_demo_presentation(self, user, agency_subscription):
        UserSubscription.objects.filter(user=user).exclude(id=agency_subscription.id).update(is_active=False)
        Notification.objects.filter(user=user).delete()
        rows = [
            ("critical", "CTR kritik seviyeye indi", "Google Ads kampanyasinda CTR son 24 saatte belirgin geriledi.", "/anomaly/"),
            ("warning", "Kreatif yorgunlugu algilandi", "Ayni kreatiflerde frekans artarken etkileşim orani dusuyor.", "/creative-studio/"),
            ("info", "Pazaryeri fiyat takibi tamamlandi", "5 pazaryerinde 100 urun icin fiyat/stok takibi guncellendi.", "/marketplace/price-tracking/"),
            ("success", "Platform senkronizasyonu basarili", "15 platform hesabi ve GA4 property son veriyle senkronize edildi.", "/platforms/connections/"),
            ("info", "Influencer havuzu hazir", "16 influencer profili 3 aylik metrik gecmisiyle hazirlandi.", "/influencers/"),
            ("warning", "Butce optimizasyon firsati", "ROAS iyi olan kampanyalarda kontrollu butce artisi oneriliyor.", "/budget/apply/"),
            ("success", "Demo ajans yetkileri aktif", "Demo kullanicisi tum ajans ve rapor ekranlarina erisebilir.", "/agency/"),
        ]
        for level, title, message, link in rows:
            Notification.objects.create(
                user=user,
                level=level,
                title=title,
                message=message,
                icon="bell",
                link=link,
                is_read=False,
            )
        return {"notifications": len(rows)}

    def _trend_value(self, base, offset, growth, noise):
        factor = 1 + (89 - offset) / 89 * growth
        wave = 1 + math.sin(offset / 7.5) * 0.08
        return max(1, int(base * factor * wave + random.randint(-noise, noise)))
