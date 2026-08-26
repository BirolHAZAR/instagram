from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Ad, AdMetricHistory, Competitor, Creative, Platform, PlatformAccount
from core.services.cache_service import CacheService


class Command(BaseCommand):
    help = "Create presentation-only demo competitors on live-supported platforms."

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(username="demo").first()
        if not user:
            self.stdout.write(self.style.ERROR("demo kullanicisi bulunamadi."))
            return

        now = timezone.now()
        today = now.date()
        created_ads = 0
        specs = [
            ("instagram", "ModaVitrin Instagram", "@modavitrin", "Yeni sezon sosyal kanit kampanyasi"),
            ("instagram", "PazarLideri Instagram", "@pazarlideri", "Kargo bedava teklif kampanyasi"),
            ("facebook", "FirsatSepeti Facebook", "firsatsepeti", "Sepette indirim kampanyasi"),
            ("facebook", "TrendMarka Facebook", "trendmarka", "Guven odakli yeniden pazarlama"),
        ]

        for index, (platform_code, name, identifier, theme) in enumerate(specs, start=1):
            platform, _ = Platform.objects.get_or_create(
                code=platform_code,
                defaults={"name": platform_code.title(), "is_active": True},
            )
            account, _ = PlatformAccount.objects.get_or_create(
                user=user,
                platform=platform,
                account_id=f"demo-supported-{platform_code}",
                defaults={
                    "account_name": f"Demo {platform.name} Hesabi",
                    "access_token": "demo-presentation-token",
                    "is_active": True,
                },
            )
            competitor, _ = Competitor.objects.update_or_create(
                user=user,
                platform=platform,
                platform_account=account,
                platform_identifier=identifier,
                defaults={
                    "name": name,
                    "category": "direct",
                    "description": "Sunum icin destekli platform demo rakibi.",
                    "is_active": True,
                    "last_seen_at": now - timedelta(hours=index),
                    "raw_data": {"presentation_demo": True, "provider": "meta_ad_library_demo"},
                },
            )
            for ad_no in range(1, 3):
                ad_key = f"presentation-{platform_code}-{index}-{ad_no}"
                creative, _ = Creative.objects.update_or_create(
                    user=user,
                    platform_account=account,
                    platform_creative_id=f"{ad_key}-creative",
                    defaults={
                        "creative_type": "IMAGE",
                        "name": f"{name} Kreatif {ad_no}",
                        "title": theme,
                        "body_text": "Sunum demo reklami: canli destekli platform akisini gostermek icin olusturuldu.",
                        "image_url": f"https://picsum.photos/seed/{ad_key}/900/900",
                        "landing_url": f"https://demo.reklamanaliz.net/rakip/{platform_code}/{ad_no}",
                        "raw_data": {"presentation_demo": True},
                        "first_seen_at": now - timedelta(days=30),
                        "last_seen_at": now,
                    },
                )
                ad, ad_created = Ad.objects.update_or_create(
                    user=user,
                    source_type="COMPETITOR",
                    competitor=competitor,
                    platform_ad_id=ad_key,
                    defaults={
                        "platform_account": account,
                        "creative": creative,
                        "ad_library_id": ad_key,
                        "name": f"{name} Reklam {ad_no}",
                        "status": "ACTIVE",
                        "ad_format": "IMAGE",
                        "objective": "AWARENESS",
                        "headline": theme,
                        "primary_text": creative.body_text,
                        "landing_url": creative.landing_url,
                        "preview_image_url": creative.image_url,
                        "first_seen_at": now - timedelta(days=30),
                        "last_seen_at": now,
                        "raw_data": {
                            "presentation_demo": True,
                            "provider": "meta_ad_library_demo",
                            "budget": 25000 + index * 1500 + ad_no * 500,
                            "media_type": "image",
                        },
                        "last_synced_at": now,
                        "is_active": True,
                    },
                )
                if ad_created:
                    created_ads += 1
                for offset in range(29, -1, -1):
                    impressions = 1800 + index * 240 + ad_no * 130 + (29 - offset) * 38
                    clicks = int(impressions * Decimal("0.024"))
                    engagement = int(impressions * Decimal("0.041"))
                    spend = Decimal("220.00") + Decimal(index * 35 + ad_no * 18 + (29 - offset) * 6)
                    AdMetricHistory.objects.update_or_create(
                        ad=ad,
                        date=today - timedelta(days=offset),
                        defaults={
                            "impressions": impressions,
                            "reach": int(impressions * Decimal("0.78")),
                            "clicks": clicks,
                            "spend": spend,
                            "currency": "TRY",
                            "ctr": Decimal(str(round(clicks / impressions * 100, 4))),
                            "cpc": Decimal(str(round(float(spend) / max(clicks, 1), 4))),
                            "cpm": Decimal(str(round(float(spend) / impressions * 1000, 4))),
                            "engagement": engagement,
                            "engagement_rate": Decimal(str(round(engagement / impressions * 100, 4))),
                            "estimated_engagement": engagement,
                            "estimated_reach_min": int(impressions * Decimal("0.62")),
                            "estimated_reach_max": int(impressions * Decimal("0.90")),
                            "is_competitor_snapshot": True,
                            "raw_metrics": {"presentation_demo": True},
                        },
                    )
            competitor.total_ads_seen = Ad.objects.filter(user=user, source_type="COMPETITOR", competitor=competitor).count()
            competitor.save(update_fields=["total_ads_seen", "updated_at"])

        CacheService.bump_version("competitors", user.id)
        CacheService.bump_version("competitor_movements", user.id)
        CacheService.bump_version("competitor_movements_page", user.id)
        CacheService.bump_version("competitor_intelligence", user.id)
        self.stdout.write(self.style.SUCCESS(f"Sunum demo rakipleri hazir. Yeni reklam: {created_ads}"))
