from __future__ import annotations

import math
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import (
    Ad,
    AdGroup,
    AdGroupMetricHistory,
    AdMetricHistory,
    AnalyticsDailyMetric,
    AnalyticsLandingPageMetric,
    AnalyticsProperty,
    Campaign,
    CampaignMetricHistory,
    CreativeMetricHistory,
    Influencer,
    InfluencerMetricHistory,
    MarketplaceListing,
    MarketplaceListingMetricHistory,
    SocialPost,
    SocialPostMetricHistory,
)


class Command(BaseCommand):
    help = (
        "Mevcut demo verileri icin yeni gunluk performans "
        "metrikleri uretir. Demo kullanicisini veya ana "
        "demo varliklarini silmez/olusturmaz."
    )

    DEMO_USERNAME = "demo"

    def handle(self, *args, **options):
        now = timezone.now()
        today = now.date()

        User = get_user_model()

        user = User.objects.filter(
            username=self.DEMO_USERNAME
        ).first()

        if not user:
            raise CommandError(
                "demo kullanicisi bulunamadi. "
                "Once python manage.py seed_demo_data "
                "calistirilmalidir."
            )

        random.seed(
            f"reklamanaliz-demo-{today.isoformat()}"
        )

        self.stdout.write(
            f"Demo gunluk veri guncellemesi: {today}"
        )

        with transaction.atomic():
            summary = {
                "ads": 0,
                "creatives": 0,
                "campaigns": 0,
                "ad_groups": 0,
                "ga": 0,
                "landing_pages": 0,
                "social_posts": 0,
                "influencers": 0,
                "marketplace": 0,
            }

            summary["ads"] = self._update_ads(
                user,
                today,
            )

            summary["creatives"] = self._update_creatives(
                user,
                today,
            )

            summary["campaigns"] = self._update_campaigns(
                user,
                today,
            )

            summary["ad_groups"] = self._update_ad_groups(
                user,
                today,
            )

            summary["ga"] = self._update_ga4(
                user,
                today,
            )

            summary["landing_pages"] = (
                self._update_landing_pages(
                    user,
                    today,
                )
            )

            summary["social_posts"] = (
                self._update_social_posts(
                    user,
                    today,
                )
            )

            summary["influencers"] = (
                self._update_influencers(
                    user,
                    today,
                )
            )

            summary["marketplace"] = (
                self._update_marketplace(
                    user,
                    today,
                )
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Demo gunluk veri basariyla guncellendi."
            )
        )

        self.stdout.write(
            f"Reklam metrikleri: {summary['ads']}"
        )

        self.stdout.write(
            f"Kreatif metrikleri: {summary['creatives']}"
        )

        self.stdout.write(
            f"Kampanya metrikleri: {summary['campaigns']}"
        )

        self.stdout.write(
            f"Reklam grubu metrikleri: "
            f"{summary['ad_groups']}"
        )

        self.stdout.write(
            f"GA4 gunleri: {summary['ga']}"
        )

        self.stdout.write(
            f"Landing page gunleri: "
            f"{summary['landing_pages']}"
        )

        self.stdout.write(
            f"Organik post gunleri: "
            f"{summary['social_posts']}"
        )

        self.stdout.write(
            f"Influencer gunleri: "
            f"{summary['influencers']}"
        )

        self.stdout.write(
            f"Pazaryeri gunleri: "
            f"{summary['marketplace']}"
        )

        self.stdout.write("")
        self.stdout.write(
            "Demo kullanicisi korunmustur: demo"
        )

    # ============================================================
    # ADS
    # ============================================================

    def _update_ads(
        self,
        user,
        today,
    ):
        count = 0

        ads = (
            Ad.objects.filter(
                user=user,
            )
            .select_related(
                "campaign",
                "ad_group",
                "creative",
            )
            .order_by("id")
        )

        for ad in ads:
            if AdMetricHistory.objects.filter(
                ad=ad,
                date=today,
            ).exists():
                continue

            previous = (
                AdMetricHistory.objects.filter(
                    ad=ad,
                    date__lt=today,
                )
                .order_by("-date")
                .first()
            )

            if not previous:
                continue

            metrics = self._next_ad_metrics(
                previous,
            )

            AdMetricHistory.objects.create(
                ad=ad,
                date=today,
                **metrics,
            )

            count += 1

        return count

    def _next_ad_metrics(
        self,
        previous,
    ):
        previous_impressions = max(
            int(previous.impressions),
            100,
        )

        previous_ctr = max(
            float(previous.ctr or 0),
            0.1,
        )

        previous_spend = max(
            float(previous.spend or 0),
            1,
        )

        previous_conversion_rate = (
            float(previous.conversions or 0)
            / max(
                int(previous.clicks or 0),
                1,
            )
        )

        previous_aov = (
            float(previous.conversion_value or 0)
            / max(
                float(previous.conversions or 0),
                1,
            )
        )

        # --------------------------------------------------------
        # DOGAL GUNLUK DALGALANMA
        # --------------------------------------------------------

        day_wave = random.uniform(
            0.94,
            1.07,
        )

        impressions = max(
            100,
            int(
                previous_impressions
                * day_wave
            ),
        )

        ctr = max(
            0.20,
            previous_ctr
            * random.uniform(
                0.94,
                1.06,
            ),
        )

        clicks = max(
            1,
            int(
                impressions
                * ctr
                / 100
            ),
        )

        cpc = max(
            0.10,
            (
                previous_spend
                / max(
                    int(previous.clicks),
                    1,
                )
            )
            * random.uniform(
                0.94,
                1.07,
            ),
        )

        spend = max(
            10,
            clicks * cpc,
        )

        conversion_rate = max(
            0.005,
            previous_conversion_rate
            * random.uniform(
                0.92,
                1.08,
            ),
        )

        conversions = max(
            0,
            round(
                clicks
                * conversion_rate,
                2,
            ),
        )

        if previous_aov <= 0:
            previous_aov = 900

        average_order_value = (
            previous_aov
            * random.uniform(
                0.96,
                1.05,
            )
        )

        conversion_value = max(
            0,
            round(
                conversions
                * average_order_value,
                2,
            ),
        )

        reach_ratio = random.uniform(
            0.62,
            0.88,
        )

        reach = max(
            1,
            int(
                impressions
                * reach_ratio
            ),
        )

        frequency = (
            impressions
            / max(reach, 1)
        )

        link_clicks = max(
            1,
            int(
                clicks
                * random.uniform(
                    0.72,
                    0.94,
                )
            ),
        )

        unique_clicks = max(
            1,
            int(
                clicks
                * random.uniform(
                    0.64,
                    0.88,
                )
            ),
        )

        landing_page_views = max(
            1,
            int(
                clicks
                * random.uniform(
                    0.58,
                    0.86,
                )
            ),
        )

        outbound_clicks = max(
            1,
            int(
                clicks
                * random.uniform(
                    0.45,
                    0.78,
                )
            ),
        )

        engagement = max(
            1,
            int(
                impressions
                * random.uniform(
                    0.018,
                    0.082,
                )
            ),
        )

        likes = max(
            0,
            int(
                engagement
                * random.uniform(
                    0.42,
                    0.68,
                )
            ),
        )

        comments = max(
            0,
            int(
                engagement
                * random.uniform(
                    0.04,
                    0.14,
                )
            ),
        )

        shares = max(
            0,
            int(
                engagement
                * random.uniform(
                    0.05,
                    0.18,
                )
            ),
        )

        saves = max(
            0,
            int(
                engagement
                * random.uniform(
                    0.08,
                    0.24,
                )
            ),
        )

        video_views = max(
            0,
            int(
                impressions
                * random.uniform(
                    0.12,
                    0.52,
                )
            ),
        )

        cpm = (
            spend
            / max(impressions, 1)
            * 1000
        )

        cost_per_conversion = (
            spend
            / max(
                conversions,
                1,
            )
        )

        roas = (
            conversion_value
            / max(
                spend,
                1,
            )
        )

        engagement_rate = (
            engagement
            / max(
                impressions,
                1,
            )
            * 100
        )

        add_to_cart = max(
            0,
            round(
                conversions
                * random.uniform(
                    1.8,
                    4.2,
                ),
                2,
            ),
        )

        initiate_checkout = max(
            0,
            round(
                conversions
                * random.uniform(
                    1.2,
                    2.4,
                ),
                2,
            ),
        )

        leads = max(
            0,
            round(
                clicks
                * random.uniform(
                    0.02,
                    0.10,
                ),
                2,
            ),
        )

        return {
            "impressions": impressions,
            "reach": reach,
            "frequency": self._decimal(
                frequency,
                4,
            ),
            "clicks": clicks,
            "link_clicks": link_clicks,
            "unique_clicks": unique_clicks,
            "spend": self._decimal(
                spend,
                2,
            ),
            "currency": "TRY",
            "ctr": self._decimal(
                ctr,
                4,
            ),
            "cpc": self._decimal(
                cpc,
                4,
            ),
            "cpm": self._decimal(
                cpm,
                4,
            ),
            "conversions": self._decimal(
                conversions,
                2,
            ),
            "conversion_value": self._decimal(
                conversion_value,
                2,
            ),
            "cost_per_conversion": self._decimal(
                cost_per_conversion,
                4,
            ),
            "purchases": self._decimal(
                conversions,
                2,
            ),
            "add_to_cart": self._decimal(
                add_to_cart,
                2,
            ),
            "initiate_checkout": self._decimal(
                initiate_checkout,
                2,
            ),
            "leads": self._decimal(
                leads,
                2,
            ),
            "landing_page_views": (
                landing_page_views
            ),
            "outbound_clicks": (
                outbound_clicks
            ),
            "roas": self._decimal(
                roas,
                4,
            ),
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "saves": saves,
            "video_views": video_views,
            "engagement": engagement,
            "engagement_rate": self._decimal(
                engagement_rate,
                4,
            ),
            "raw_metrics": {
                "demo": True,
                "generated_by": (
                    "update_demo_daily"
                ),
            },
        }

    # ============================================================
    # CREATIVE
    # ============================================================

    def _update_creatives(
        self,
        user,
        today,
    ):
        count = 0

        creatives = CreativeMetricHistory.objects.filter(
            creative__user=user,
        ).values_list(
            "creative_id",
            flat=True,
        ).distinct()

        for creative_id in creatives:
            if CreativeMetricHistory.objects.filter(
                creative_id=creative_id,
                date=today,
            ).exists():
                continue

            previous = (
                CreativeMetricHistory.objects.filter(
                    creative_id=creative_id,
                    date__lt=today,
                )
                .order_by("-date")
                .first()
            )

            if not previous:
                continue

            thumbstop = self._bounded_random(
                float(previous.thumbstop_rate or 0.35),
                0.15,
                0.75,
            )

            hook = self._bounded_random(
                float(previous.hook_rate or 0.30),
                0.10,
                0.65,
            )

            hold = self._bounded_random(
                float(previous.hold_rate or 0.22),
                0.06,
                0.55,
            )

            kwargs = {
                "creative_id": creative_id,
                "date": today,
                "thumbstop_rate": self._decimal(
                    thumbstop,
                    4,
                ),
                "hook_rate": self._decimal(
                    hook,
                    4,
                ),
                "hold_rate": self._decimal(
                    hold,
                    4,
                ),
                "raw_metrics": {
                    "demo": True,
                    "generated_by": (
                        "update_demo_daily"
                    ),
                },
            }

            for field in (
                "impressions",
                "reach",
                "clicks",
                "link_clicks",
                "unique_clicks",
                "spend",
                "conversions",
                "conversion_value",
                "cost_per_conversion",
                "roas",
                "likes",
                "comments",
                "shares",
                "saves",
                "video_views",
                "engagement",
                "ctr",
                "cpc",
                "cpm",
                "engagement_rate",
            ):
                if hasattr(previous, field):
                    value = getattr(previous, field)

                    if value is None:
                        continue

                    if isinstance(
                        value,
                        Decimal,
                    ):
                        value = value * Decimal(
                            str(
                                random.uniform(
                                    0.95,
                                    1.05,
                                )
                            )
                        )
                    elif isinstance(
                        value,
                        int,
                    ):
                        value = int(
                            value
                            * random.uniform(
                                0.95,
                                1.05,
                            )
                        )

                    kwargs[field] = value

            CreativeMetricHistory.objects.create(
                **kwargs
            )

            count += 1

        return count

    # ============================================================
    # CAMPAIGNS
    # ============================================================

    def _update_campaigns(
        self,
        user,
        today,
    ):
        count = 0

        campaigns = Campaign.objects.filter(
            user=user,
        ).prefetch_related(
            "ad_set",
        )

        for campaign in campaigns:
            if CampaignMetricHistory.objects.filter(
                campaign=campaign,
                date=today,
            ).exists():
                continue

            ads = Ad.objects.filter(
                user=user,
                campaign=campaign,
            )

            metric_rows = list(
                AdMetricHistory.objects.filter(
                    ad__in=ads,
                    date=today,
                )
            )

            if not metric_rows:
                continue

            rolled = self._rollup(
                metric_rows,
            )

            CampaignMetricHistory.objects.create(
                campaign=campaign,
                date=today,
                **rolled,
            )

            count += 1

        return count

    # ============================================================
    # AD GROUPS
    # ============================================================

    def _update_ad_groups(
        self,
        user,
        today,
    ):
        count = 0

        ad_groups = AdGroup.objects.filter(
            user=user,
        )

        for ad_group in ad_groups:
            if AdGroupMetricHistory.objects.filter(
                ad_group=ad_group,
                date=today,
            ).exists():
                continue

            ads = Ad.objects.filter(
                user=user,
                ad_group=ad_group,
            )

            metric_rows = list(
                AdMetricHistory.objects.filter(
                    ad__in=ads,
                    date=today,
                )
            )

            if not metric_rows:
                continue

            rolled = self._rollup(
                metric_rows,
            )

            AdGroupMetricHistory.objects.create(
                ad_group=ad_group,
                date=today,
                **rolled,
            )

            count += 1

        return count

    # ============================================================
    # ROLLUP
    # ============================================================

    def _rollup(
        self,
        rows,
    ):
        integer_fields = [
            "impressions",
            "reach",
            "clicks",
            "link_clicks",
            "unique_clicks",
            "landing_page_views",
            "outbound_clicks",
            "likes",
            "comments",
            "shares",
            "saves",
            "video_views",
            "engagement",
        ]

        decimal_fields = [
            "spend",
            "conversions",
            "conversion_value",
            "purchases",
            "add_to_cart",
            "initiate_checkout",
            "leads",
        ]

        data = {}

        for field in integer_fields:
            data[field] = sum(
                int(
                    getattr(
                        row,
                        field,
                    ) or 0
                )
                for row in rows
            )

        for field in decimal_fields:
            data[field] = sum(
                (
                    getattr(
                        row,
                        field,
                    )
                    or Decimal("0")
                )
                for row in rows
            )

        data["currency"] = "TRY"

        total_impressions = max(
            data["impressions"],
            1,
        )

        total_clicks = max(
            data["clicks"],
            1,
        )

        total_spend = max(
            float(data["spend"]),
            1,
        )

        total_conversions = max(
            float(data["conversions"]),
            1,
        )

        data["frequency"] = self._decimal(
            sum(
                float(
                    row.frequency or 0
                )
                for row in rows
            )
            / max(len(rows), 1),
            4,
        )

        data["ctr"] = self._decimal(
            data["clicks"]
            / total_impressions
            * 100,
            4,
        )

        data["cpc"] = self._decimal(
            float(data["spend"])
            / total_clicks,
            4,
        )

        data["cpm"] = self._decimal(
            float(data["spend"])
            / total_impressions
            * 1000,
            4,
        )

        data["cost_per_conversion"] = (
            self._decimal(
                float(data["spend"])
                / total_conversions,
                4,
            )
        )

        data["roas"] = self._decimal(
            float(
                data["conversion_value"]
            )
            / total_spend,
            4,
        )

        data["engagement_rate"] = (
            self._decimal(
                data["engagement"]
                / total_impressions
                * 100,
                4,
            )
        )

        data["raw_metrics"] = {
            "demo": True,
            "rolled_up": True,
            "generated_by": (
                "update_demo_daily"
            ),
        }

        return data

    # ============================================================
    # GA4
    # ============================================================

    def _update_ga4(
        self,
        user,
        today,
    ):
        count = 0

        properties = AnalyticsProperty.objects.filter(
            user=user,
        )

        for prop in properties:
            if AnalyticsDailyMetric.objects.filter(
                property=prop,
                date=today,
            ).exists():
                continue

            previous = (
                AnalyticsDailyMetric.objects.filter(
                    property=prop,
                    date__lt=today,
                )
                .order_by("-date")
                .first()
            )

            if not previous:
                continue

            sessions = self._random_int(
                previous.sessions,
                0.93,
                1.09,
            )

            users = self._random_int(
                previous.users,
                0.94,
                1.08,
            )

            new_users = self._random_int(
                previous.new_users,
                0.93,
                1.10,
            )

            engaged_sessions = self._random_int(
                previous.engaged_sessions,
                0.93,
                1.08,
            )

            conversions = self._random_decimal(
                previous.conversions,
                0.90,
                1.12,
            )

            revenue = self._random_decimal(
                previous.total_revenue,
                0.90,
                1.14,
            )

            AnalyticsDailyMetric.objects.create(
                property=prop,
                date=today,
                sessions=sessions,
                users=users,
                new_users=new_users,
                engaged_sessions=engaged_sessions,
                engagement_rate=self._random_decimal(
                    previous.engagement_rate,
                    0.96,
                    1.04,
                ),
                bounce_rate=self._random_decimal(
                    previous.bounce_rate,
                    0.94,
                    1.06,
                ),
                average_session_duration=(
                    self._random_decimal(
                        previous.average_session_duration,
                        0.93,
                        1.08,
                    )
                ),
                screen_page_views=self._random_int(
                    previous.screen_page_views,
                    0.93,
                    1.09,
                ),
                event_count=self._random_int(
                    previous.event_count,
                    0.94,
                    1.10,
                ),
                key_events=conversions,
                conversions=conversions,
                total_revenue=revenue,
                purchase_revenue=revenue,
                transactions=conversions,
                average_purchase_revenue=(
                    self._decimal(
                        float(revenue)
                        / max(
                            float(conversions),
                            1,
                        ),
                        2,
                    )
                ),
                raw_metrics={
                    "demo": True,
                    "generated_by": (
                        "update_demo_daily"
                    ),
                },
            )

            count += 1

        return count

    # ============================================================
    # LANDING PAGES
    # ============================================================

    def _update_landing_pages(
        self,
        user,
        today,
    ):
        count = 0

        previous_rows = (
            AnalyticsLandingPageMetric.objects.filter(
                property__user=user,
                date__lt=today,
            )
            .order_by(
                "property_id",
                "landing_page",
                "-date",
            )
        )

        seen = set()

        for previous in previous_rows:
            key = (
                previous.property_id,
                previous.landing_page,
            )

            if key in seen:
                continue

            seen.add(key)

            if AnalyticsLandingPageMetric.objects.filter(
                property=previous.property,
                landing_page=previous.landing_page,
                date=today,
            ).exists():
                continue

            sessions = self._random_int(
                previous.sessions,
                0.92,
                1.10,
            )

            conversions = self._random_decimal(
                previous.conversions,
                0.88,
                1.14,
            )

            revenue = self._random_decimal(
                previous.total_revenue,
                0.90,
                1.15,
            )

            AnalyticsLandingPageMetric.objects.create(
                property=previous.property,
                date=today,
                landing_page=previous.landing_page,
                landing_page_title=(
                    previous.landing_page_title
                ),
                sessions=sessions,
                users=self._random_int(
                    previous.users,
                    0.92,
                    1.09,
                ),
                new_users=self._random_int(
                    previous.new_users,
                    0.90,
                    1.10,
                ),
                engaged_sessions=self._random_int(
                    previous.engaged_sessions,
                    0.92,
                    1.08,
                ),
                engagement_rate=self._random_decimal(
                    previous.engagement_rate,
                    0.95,
                    1.05,
                ),
                bounce_rate=self._random_decimal(
                    previous.bounce_rate,
                    0.94,
                    1.06,
                ),
                conversions=conversions,
                total_revenue=revenue,
                raw_metrics={
                    "demo": True,
                    "generated_by": (
                        "update_demo_daily"
                    ),
                },
            )

            count += 1

        return count

    # ============================================================
    # SOCIAL POSTS
    # ============================================================

    def _update_social_posts(
        self,
        user,
        today,
    ):
        count = 0

        posts = SocialPost.objects.filter(
            user=user,
        )

        for post in posts:
            if SocialPostMetricHistory.objects.filter(
                social_post=post,
                date=today,
            ).exists():
                continue

            previous = (
                SocialPostMetricHistory.objects.filter(
                    social_post=post,
                    date__lt=today,
                )
                .order_by("-date")
                .first()
            )

            if not previous:
                continue

            impressions = self._random_int(
                previous.impressions,
                0.92,
                1.10,
            )

            engagement = self._random_int(
                previous.engagement,
                0.90,
                1.12,
            )

            SocialPostMetricHistory.objects.create(
                social_post=post,
                date=today,
                impressions=impressions,
                reach=self._random_int(
                    previous.reach,
                    0.92,
                    1.09,
                ),
                likes=self._random_int(
                    previous.likes,
                    0.90,
                    1.12,
                ),
                comments=self._random_int(
                    previous.comments,
                    0.88,
                    1.15,
                ),
                shares=self._random_int(
                    previous.shares,
                    0.88,
                    1.16,
                ),
                saves=self._random_int(
                    previous.saves,
                    0.88,
                    1.16,
                ),
                video_views=self._random_int(
                    previous.video_views,
                    0.90,
                    1.12,
                ),
                profile_visits=self._random_int(
                    previous.profile_visits,
                    0.90,
                    1.12,
                ),
                website_clicks=self._random_int(
                    previous.website_clicks,
                    0.90,
                    1.14,
                ),
                engagement=engagement,
                engagement_rate=self._decimal(
                    engagement
                    / max(impressions, 1)
                    * 100,
                    4,
                ),
                raw_metrics={
                    "demo": True,
                    "generated_by": (
                        "update_demo_daily"
                    ),
                },
            )

            count += 1

        return count

    # ============================================================
    # INFLUENCERS
    # ============================================================

    def _update_influencers(
        self,
        user,
        today,
    ):
        count = 0

        influencers = Influencer.objects.filter(
            created_by=user,
        )

        for influencer in influencers:
            if InfluencerMetricHistory.objects.filter(
                influencer=influencer,
                date=today,
            ).exists():
                continue

            previous = (
                InfluencerMetricHistory.objects.filter(
                    influencer=influencer,
                    date__lt=today,
                )
                .order_by("-date")
                .first()
            )

            if not previous:
                continue

            follower_count = self._random_int(
                previous.follower_count,
                0.998,
                1.006,
            )

            InfluencerMetricHistory.objects.create(
                influencer=influencer,
                date=today,
                follower_count=follower_count,
                following_count=(
                    previous.following_count
                ),
                post_count=(
                    previous.post_count
                    + (
                        1
                        if random.random() < 0.20
                        else 0
                    )
                ),
                avg_likes=self._random_int(
                    previous.avg_likes,
                    0.94,
                    1.08,
                ),
                avg_comments=self._random_int(
                    previous.avg_comments,
                    0.92,
                    1.10,
                ),
                avg_views=self._random_int(
                    previous.avg_views,
                    0.92,
                    1.10,
                ),
                engagement_rate=self._random_decimal(
                    previous.engagement_rate,
                    0.94,
                    1.07,
                ),
                estimated_reach=self._random_int(
                    previous.estimated_reach,
                    0.93,
                    1.08,
                ),
                raw_metrics={
                    "demo": True,
                    "generated_by": (
                        "update_demo_daily"
                    ),
                },
            )

            count += 1

        return count

    # ============================================================
    # MARKETPLACE
    # ============================================================

    def _update_marketplace(
        self,
        user,
        today,
    ):
        count = 0

        listings = MarketplaceListing.objects.filter(
            marketplace_account__user=user,
        ).select_related(
            "marketplace_account",
            "marketplace",
            "product",
            "variant",
        )

        for listing in listings:
            if MarketplaceListingMetricHistory.objects.filter(
                listing=listing,
                date=today,
            ).exists():
                continue

            previous = (
                MarketplaceListingMetricHistory.objects.filter(
                    listing=listing,
                    date__lt=today,
                )
                .order_by("-date")
                .first()
            )

            if not previous:
                continue

            discounted_price = (
                float(previous.discounted_price)
                * random.uniform(
                    0.97,
                    1.03,
                )
            )

            sale_price = (
                float(previous.sale_price)
                * random.uniform(
                    0.98,
                    1.02,
                )
            )

            purchase_price = float(
                previous.purchase_price
            )

            orders = max(
                0,
                int(
                    previous.orders
                    * random.uniform(
                        0.80,
                        1.25,
                    )
                )
                + (
                    1
                    if random.random() < 0.25
                    else 0
                ),
            )

            units_sold = max(
                orders,
                int(
                    previous.units_sold
                    * random.uniform(
                        0.85,
                        1.20,
                    )
                ),
            )

            revenue = (
                discounted_price
                * units_sold
            )

            gross_profit = (
                discounted_price
                - purchase_price
            )

            margin = (
                gross_profit
                / max(
                    discounted_price,
                    1,
                )
                * 100
            )

            current_stock = max(
                0,
                int(
                    previous.stock
                    - units_sold
                    + random.randint(
                        -3,
                        8,
                    )
                ),
            )

            MarketplaceListingMetricHistory.objects.create(
                listing=listing,
                marketplace_account=(
                    listing.marketplace_account
                ),
                marketplace=listing.marketplace,
                product=listing.product,
                variant=listing.variant,
                date=today,
                sale_price=self._decimal(
                    sale_price,
                    2,
                ),
                discounted_price=self._decimal(
                    discounted_price,
                    2,
                ),
                purchase_price=self._decimal(
                    purchase_price,
                    2,
                ),
                commission_rate=(
                    previous.commission_rate
                ),
                stock=current_stock,
                status=(
                    MarketplaceListing.STATUS_ACTIVE
                ),
                gross_profit=self._decimal(
                    gross_profit,
                    2,
                ),
                gross_margin_rate=self._decimal(
                    margin,
                    4,
                ),
                orders=orders,
                units_sold=units_sold,
                revenue=self._decimal(
                    revenue,
                    2,
                ),
                view_count=self._random_int(
                    previous.view_count,
                    0.90,
                    1.15,
                ),
                favorite_count=self._random_int(
                    previous.favorite_count,
                    0.90,
                    1.15,
                ),
                review_count=max(
                    previous.review_count,
                    previous.review_count
                    + (
                        1
                        if random.random() < 0.15
                        else 0
                    ),
                ),
                return_count=self._random_int(
                    previous.return_count,
                    0.85,
                    1.20,
                ),
                buybox_rank=max(
                    1,
                    min(
                        5,
                        previous.buybox_rank
                        + random.choice(
                            [-1, 0, 0, 0, 1]
                        ),
                    ),
                ),
                raw_metrics={
                    "demo": True,
                    "generated_by": (
                        "update_demo_daily"
                    ),
                },
            )

            count += 1

        return count

    # ============================================================
    # HELPERS
    # ============================================================

    @staticmethod
    def _decimal(
        value,
        places=2,
    ):
        return Decimal(
            str(
                round(
                    float(value),
                    places,
                )
            )
        )

    @staticmethod
    def _random_int(
        value,
        minimum,
        maximum,
    ):
        base = int(
            value or 0
        )

        if base <= 0:
            return 0

        return max(
            0,
            int(
                base
                * random.uniform(
                    minimum,
                    maximum,
                )
            ),
        )

    @classmethod
    def _random_decimal(
        cls,
        value,
        minimum,
        maximum,
    ):
        base = float(
            value or 0
        )

        if base <= 0:
            return Decimal("0")

        return cls._decimal(
            base
            * random.uniform(
                minimum,
                maximum,
            ),
            4,
        )

    @staticmethod
    def _bounded_random(
        value,
        minimum,
        maximum,
    ):
        return max(
            minimum,
            min(
                maximum,
                value
                * random.uniform(
                    0.94,
                    1.06,
                ),
            ),
        )