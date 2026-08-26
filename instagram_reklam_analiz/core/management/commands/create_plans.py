from django.core.management.base import BaseCommand

from core.models.membership import AICreditPackage, MembershipPlan, ProductResearchPackage


BUSINESS_PLANS = [
    {
        "name": "silver",
        "display_name": "Silver",
        "plan_type": MembershipPlan.PLAN_TYPE_BUSINESS,
        "price": 750,
        "price_with_kdv": 900,
        "features": "\n".join([
            "3 platform hesabı",
            "90 günlük veri görünümü",
            "Haftalık veri takibi",
            "Ayda 30 AI analiz",
            "Ayda 15 AI öneri",
            "3 rakip takibi",
            "PDF rapor",
        ]),
        "max_instagram_accounts": 3,
        "max_competitors": 3,
        "ai_analysis_per_month": 30,
        "ai_recommendation_per_month": 15,
        "marketplace_product_research_per_month": 0,
        "marketplace_price_check_per_month": 0,
        "ai_credits_per_month": 300,
        "max_campaign_templates": 5,
        "max_content_fetch_count": 0,
        "content_fetch_period_days": 90,
        "auto_fetch_enabled": True,
        "auto_fetch_frequency": "weekly",
        "competitor_fetch_enabled": True,
        "competitor_fetch_frequency": "manual",
        "has_advanced_reporting": True,
        "priority_support": True,
        "order": 1,
        "badge": "Başlangıç",
        "badge_color": "#4A90D9",
        "is_most_popular": False,
    },
    {
        "name": "gold",
        "display_name": "Gold",
        "plan_type": MembershipPlan.PLAN_TYPE_BUSINESS,
        "price": 1500,
        "price_with_kdv": 1800,
        "features": "\n".join([
            "10 platform hesabı",
            "12 ay veri görünümü",
            "Günlük veri takibi",
            "Ayda 150 AI analiz",
            "Ayda 75 AI öneri",
            "10 rakip takibi",
            "PDF rapor",
        ]),
        "max_instagram_accounts": 10,
        "max_competitors": 10,
        "ai_analysis_per_month": 150,
        "ai_recommendation_per_month": 75,
        "marketplace_product_research_per_month": 40,
        "marketplace_price_check_per_month": 750,
        "ai_credits_per_month": 800,
        "max_campaign_templates": 20,
        "max_content_fetch_count": 0,
        "content_fetch_period_days": 365,
        "auto_fetch_enabled": True,
        "auto_fetch_frequency": "daily",
        "competitor_fetch_enabled": True,
        "competitor_fetch_frequency": "daily",
        "has_advanced_reporting": True,
        "has_opportunity_finder": True,
        "has_ab_test_campaigns": False,
        "has_content_calendar": True,
        "content_calendar_days": 15,
        "priority_support": True,
        "order": 2,
        "badge": "Ekonomik Seçim",
        "badge_color": "#FFD166",
        "is_most_popular": True,
    },
    {
        "name": "platinum",
        "display_name": "Platin",
        "plan_type": MembershipPlan.PLAN_TYPE_BUSINESS,
        "price": 5000,
        "price_with_kdv": 6000,
        "features": "\n".join([
            "30 platform hesabı",
            "12 ay veri görünümü",
            "Anlık veri takibi",
            "Ayda 1000 AI analiz",
            "Ayda 750 AI öneri",
            "30 rakip takibi",
            "PDF rapor",
        ]),
        "max_instagram_accounts": 30,
        "max_competitors": 30,
        "ai_analysis_per_month": 1000,
        "ai_recommendation_per_month": 750,
        "marketplace_product_research_per_month": 150,
        "marketplace_price_check_per_month": 3000,
        "ai_credits_per_month": 3000,
        "max_campaign_templates": 9999,
        "max_content_fetch_count": 0,
        "content_fetch_period_days": 365,
        "auto_fetch_enabled": True,
        "auto_fetch_frequency": "realtime",
        "competitor_fetch_enabled": True,
        "competitor_fetch_frequency": "realtime",
        "competitor_auto_discovery": True,
        "has_advanced_reporting": True,
        "has_opportunity_finder": True,
        "has_api_access": False,
        "has_white_label": False,
        "has_crisis_alert": False,
        "has_strategy_webinar": True,
        "has_dedicated_manager": True,
        "has_ai_content_generation": True,
        "ai_content_generation": True,
        "has_content_calendar": True,
        "content_calendar_days": 365,
        "priority_support": True,
        "order": 3,
        "badge": "Kurumsal",
        "badge_color": "#6A0DAD",
        "is_most_popular": False,
    },
]


AGENCY_PLANS = [
    {
        "name": "agency_3",
        "display_name": "Ajans Silver",
        "price": 3500,
        "price_with_kdv": 4200,
        "included_seats": 3,
        "max_team_members": 3,
        "max_client_accounts": 5,
        "max_instagram_accounts": 15,
        "ai_credits_per_month": 3000,
        "marketplace_product_research_per_month": 150,
        "marketplace_price_check_per_month": 5000,
        "order": 10,
    },
    {
        "name": "agency_5",
        "display_name": "Ajans Gold",
        "price": 6500,
        "price_with_kdv": 7800,
        "included_seats": 5,
        "max_team_members": 5,
        "max_client_accounts": 12,
        "max_instagram_accounts": 40,
        "ai_credits_per_month": 4000,
        "marketplace_product_research_per_month": 250,
        "marketplace_price_check_per_month": 12000,
        "order": 11,
    },
    {
        "name": "agency_10",
        "display_name": "Ajans Platin",
        "price": 12000,
        "price_with_kdv": 14400,
        "included_seats": 10,
        "max_team_members": 10,
        "max_client_accounts": 30,
        "max_instagram_accounts": 100,
        "ai_credits_per_month": 8000,
        "marketplace_product_research_per_month": 500,
        "marketplace_price_check_per_month": 30000,
        "order": 12,
    },
]


AI_CREDIT_PACKAGES = [
    {"name": "ai_credit_250", "display_name": "250 AI Kredi", "credits": 250, "price": 500, "price_with_kdv": 600, "order": 1},
    {"name": "ai_credit_1000", "display_name": "1.000 AI Kredi", "credits": 1000, "price": 1500, "price_with_kdv": 1800, "order": 2},
    {"name": "ai_credit_5000", "display_name": "5.000 AI Kredi", "credits": 5000, "price": 5000, "price_with_kdv": 6000, "order": 3},
]

PRODUCT_RESEARCH_PACKAGES = [
    {"name": "product_research_100", "display_name": "100 Ürün Araştırma", "units": 100, "price": 499, "price_with_kdv": 599, "order": 1},
    {"name": "product_research_500", "display_name": "500 Ürün Araştırma", "units": 500, "price": 1999, "price_with_kdv": 2399, "order": 2},
    {"name": "product_research_2000", "display_name": "2.000 Ürün Araştırma", "units": 2000, "price": 5999, "price_with_kdv": 7199, "order": 3},
]


class Command(BaseCommand):
    help = "Canlı paket yapısını oluşturur: Silver, Gold, Platin ve Ajans Silver/Gold/Platin."

    def handle(self, *args, **options):
        self._deactivate_bronze()
        self._rename_legacy_platinum()
        created_count = 0
        updated_count = 0

        for plan_data in BUSINESS_PLANS:
            created = self._upsert_plan(plan_data)
            created_count += int(created)
            updated_count += int(not created)

        for agency_data in AGENCY_PLANS:
            is_agency_platinum = agency_data["name"] == "agency_10"
            client_limit = agency_data["max_client_accounts"]
            platform_limit = agency_data["max_instagram_accounts"]
            credit_limit = agency_data["ai_credits_per_month"]
            defaults = {
                "plan_type": MembershipPlan.PLAN_TYPE_AGENCY,
                "features": "\n".join([
                    f"{agency_data['included_seats']} kullanıcı/koltuk",
                    f"{agency_data['max_client_accounts']} müşteri/marka çalışma alanı",
                    f"{platform_limit} toplam platform hesabı",
                    f"{client_limit} rakip takibi",
                    "Ekip rol yönetimi",
                    "Ajans raporlama altyapısı",
                    "Öncelikli destek",
                ]),
                "max_instagram_accounts": platform_limit,
                "max_competitors": client_limit,
                "ai_analysis_per_month": credit_limit,
                "ai_recommendation_per_month": credit_limit,
                "marketplace_product_research_per_month": agency_data["marketplace_product_research_per_month"],
                "marketplace_price_check_per_month": agency_data["marketplace_price_check_per_month"],
                "max_campaign_templates": client_limit,
                "has_advanced_reporting": True,
                "has_opportunity_finder": True,
                "has_team_members": True,
                "max_content_fetch_count": 5000 if is_agency_platinum else (2500 if agency_data["name"] == "agency_5" else 1000),
                "content_fetch_period_days": 3650 if is_agency_platinum else 365,
                "competitor_auto_discovery": is_agency_platinum,
                "ai_analysis_per_week": 0,
                "ai_recommendation_per_week": 0,
                "ai_content_generation": True,
                "has_campaign_calendar": True,
                "has_ab_test_campaigns": True,
                "has_content_calendar": True,
                "content_calendar_days": 3650 if is_agency_platinum else 365,
                "has_ai_content_generation": True,
                "has_analytics": True,
                "has_api_access": is_agency_platinum,
                "has_white_label": is_agency_platinum,
                "has_crisis_alert": True,
                "has_strategy_webinar": is_agency_platinum,
                "priority_support": True,
                "has_dedicated_manager": is_agency_platinum,
                "max_products": 5000 if is_agency_platinum else (2500 if agency_data["name"] == "agency_5" else 1000),
                "max_campaigns": client_limit,
                "badge": "Ajans",
                "badge_color": "#21D4FD",
                "is_most_popular": agency_data["name"] == "agency_5",
            }
            defaults.update(agency_data)
            created = self._upsert_plan(defaults)
            created_count += int(created)
            updated_count += int(not created)

        credit_created = 0
        credit_updated = 0
        for package_data in AI_CREDIT_PACKAGES:
            package, created = AICreditPackage.objects.update_or_create(
                name=package_data["name"],
                defaults={**package_data, "is_active": True},
            )
            credit_created += int(created)
            credit_updated += int(not created)
            label = "oluşturuldu" if created else "güncellendi"
            self.stdout.write(f"- {package.display_name} {label}")

        research_created = 0
        research_updated = 0
        for package_data in PRODUCT_RESEARCH_PACKAGES:
            package, created = ProductResearchPackage.objects.update_or_create(
                name=package_data["name"],
                defaults={**package_data, "is_active": True},
            )
            research_created += int(created)
            research_updated += int(not created)
            label = "oluşturuldu" if created else "güncellendi"
            self.stdout.write(f"- {package.display_name} {label}")

        self.stdout.write(self.style.SUCCESS("Paketler güncellendi."))
        self.stdout.write(f"- Yeni: {created_count}")
        self.stdout.write(f"- Güncellenen: {updated_count}")
        self.stdout.write(f"- AI kredi paketi yeni/güncel: {credit_created}/{credit_updated}")
        self.stdout.write(f"- Ürün araştırma paketi yeni/güncel: {research_created}/{research_updated}")
        self.stdout.write("- Bronze pasif/legacy olarak işaretlendi.")

    def _upsert_plan(self, plan_data):
        sync_minutes = {
            "silver": 10080, "gold": 1440, "platinum": 120,
            "agency_3": 1440, "agency_5": 360, "agency_10": 120,
        }.get(plan_data.get("name"), 1440)
        plan_data = {
            "is_active": True,
            "auto_fetch_enabled": plan_data.get("auto_fetch_enabled", True),
            "auto_fetch_frequency": plan_data.get("auto_fetch_frequency", "daily"),
            "competitor_fetch_enabled": plan_data.get("competitor_fetch_enabled", True),
            "competitor_fetch_frequency": plan_data.get("competitor_fetch_frequency", "daily"),
            "included_seats": plan_data.get("included_seats", 1),
            "max_client_accounts": plan_data.get("max_client_accounts", 0),
            "allow_ai_credit_topup": plan_data.get("allow_ai_credit_topup", True),
            "ad_sync_interval_minutes": plan_data.get("ad_sync_interval_minutes", sync_minutes),
            "competitor_sync_interval_minutes": plan_data.get("competitor_sync_interval_minutes", sync_minutes),
            "organic_sync_interval_minutes": plan_data.get("organic_sync_interval_minutes", sync_minutes),
            "marketplace_sync_interval_minutes": plan_data.get("marketplace_sync_interval_minutes", sync_minutes),
            "max_sync_records": plan_data.get("max_sync_records", 5000),
            **plan_data,
        }
        plan, created = MembershipPlan.objects.update_or_create(
            name=plan_data["name"],
            defaults=plan_data,
        )
        label = "oluşturuldu" if created else "güncellendi"
        self.stdout.write(f"- {plan.display_name} {label}")
        return created

    def _deactivate_bronze(self):
        MembershipPlan.objects.filter(name__in=["bronze", "bronz"]).update(
            is_active=False,
            plan_type=MembershipPlan.PLAN_TYPE_LEGACY,
            order=99,
            is_most_popular=False,
        )

    def _rename_legacy_platinum(self):
        legacy = MembershipPlan.objects.filter(name="platinyum").first()
        target_exists = MembershipPlan.objects.filter(name="platinum").exists()
        if legacy and not target_exists:
            legacy.name = "platinum"
            legacy.display_name = "Platin"
            legacy.save(update_fields=["name", "display_name", "updated_at"])
