from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import (
    Ad,
    AdMetricHistory,
    AdGroupMetricHistory,
    CampaignMetricHistory,
)


class Command(BaseCommand):
    help = (
        "Demo reklam verilerindeki eksik günlük metrikleri oluşturur. "
        "Ad seviyesinde veri üretir; AdGroup ve Campaign metriklerini "
        "Ad verilerinden hesaplar."
    )

    # ==============================================================
    # AYARLAR
    # ==============================================================

    DEFAULT_DAYS = 90

    IMPRESSION_MIN = 300
    IMPRESSION_MAX = 25000

    # ============================================================== 
    # ARGUMENTS
    # ==============================================================

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=self.DEFAULT_DAYS,
            help=(
                "Bugünden geriye doğru kontrol edilecek gün sayısı. "
                "Mevcut kayıtlar silinmez veya tekrar oluşturulmaz."
            ),
        )

        parser.add_argument(
            "--user",
            type=str,
            default="demo",
            help="Demo kullanıcı adı.",
        )

    # ==============================================================
    # HANDLE
    # ==============================================================

    def handle(self, *args, **options):
        days = options["days"]
        username = options["user"]

        if days <= 0:
            self.stdout.write(
                self.style.ERROR(
                    "--days değeri 0'dan büyük olmalıdır."
                )
            )
            return

        today = timezone.localdate()

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "=============================================="
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                " DEMO GÜNLÜK VERİ ÜRETİCİ"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                "=============================================="
            )
        )
        self.stdout.write(
            f"Kullanıcı : {username}"
        )
        self.stdout.write(
            f"Bugün     : {today}"
        )
        self.stdout.write(
            f"Kontrol   : Son {days} gün"
        )
        self.stdout.write("")

        from django.contrib.auth import get_user_model

        User = get_user_model()

        user = User.objects.filter(
            username=username
        ).first()

        if user is None:
            self.stdout.write(
                self.style.ERROR(
                    f"Kullanıcı bulunamadı: {username}"
                )
            )
            return

        # ==========================================================
        # REKLAMLAR
        # ==========================================================

        ads = list(
            Ad.objects.filter(
                user=user,
            ).select_related(
                "ad_group",
                "ad_group__campaign",
                "creative",
            )
        )

        if not ads:
            self.stdout.write(
                self.style.WARNING(
                    "Bu kullanıcıya ait reklam bulunamadı."
                )
            )
            return

        hierarchical_ads = [
            ad
            for ad in ads
            if ad.ad_group_id
            and ad.ad_group
            and ad.ad_group.campaign_id
        ]

        orphan_ads = [
            ad
            for ad in ads
            if not (
                ad.ad_group_id
                and ad.ad_group
                and ad.ad_group.campaign_id
            )
        ]

        self.stdout.write(
            f"Toplam reklam : {len(ads)}"
        )

        self.stdout.write(
            f"Hiyerarşiye bağlı reklam : {len(hierarchical_ads)}"
        )

        self.stdout.write(
            f"Orphan reklam             : {len(orphan_ads)}"
        )

        self.stdout.write("")

        created_ad = 0
        skipped_ad = 0

        created_adgroup = 0
        skipped_adgroup = 0

        created_campaign = 0
        skipped_campaign = 0

        # ==========================================================
        # 1. AD METRİKLERİ
        # ==========================================================

        with transaction.atomic():

            for day_offset in range(days - 1, -1, -1):

                target_date = (
                    today - timedelta(days=day_offset)
                )

                for ad in ads:

                    # --------------------------------------------------
                    # Aynı reklam + aynı tarih varsa dokunma.
                    # 0072 constraint bunu DB seviyesinde de garanti eder.
                    # --------------------------------------------------

                    exists = AdMetricHistory.objects.filter(
                        ad=ad,
                        date=target_date,
                    ).exists()

                    if exists:
                        skipped_ad += 1
                        continue

                    metrics = self._generate_ad_metrics(
                        ad=ad,
                        target_date=target_date,
                    )

                    AdMetricHistory.objects.create(
                        ad=ad,
                        date=target_date,
                        **metrics,
                    )

                    created_ad += 1

            # ======================================================
            # 2. ADGROUP METRİKLERİ
            # ======================================================

            # Sadece gerçekten Campaign'e bağlı AdGroup'ları alıyoruz.
            ad_group_ids = {
                ad.ad_group_id
                for ad in hierarchical_ads
                if ad.ad_group_id
            }

            for ad_group_id in ad_group_ids:

                for day_offset in range(days - 1, -1, -1):

                    target_date = (
                        today - timedelta(days=day_offset)
                    )

                    exists = AdGroupMetricHistory.objects.filter(
                        ad_group_id=ad_group_id,
                        date=target_date,
                    ).exists()

                    if exists:
                        skipped_adgroup += 1
                        continue

                    # --------------------------------------------------
                    # ÖNEMLİ:
                    #
                    # AdMetricHistory içinde ad_group_id yoktur.
                    #
                    # Doğru ilişki:
                    # ad__ad_group_id
                    # --------------------------------------------------

                    rows = AdMetricHistory.objects.filter(
                        ad__ad_group_id=ad_group_id,
                        date=target_date,
                    )

                    if not rows.exists():
                        continue

                    metrics = self._aggregate_metrics(
                        rows
                    )

                    AdGroupMetricHistory.objects.create(
                        ad_group_id=ad_group_id,
                        date=target_date,
                        **metrics,
                    )

                    created_adgroup += 1

            # ======================================================
            # 3. CAMPAIGN METRİKLERİ
            # ======================================================

            campaign_ids = {
                ad.ad_group.campaign_id
                for ad in hierarchical_ads
                if ad.ad_group
                and ad.ad_group.campaign_id
            }

            for campaign_id in campaign_ids:

                for day_offset in range(days - 1, -1, -1):

                    target_date = (
                        today - timedelta(days=day_offset)
                    )

                    exists = CampaignMetricHistory.objects.filter(
                        campaign_id=campaign_id,
                        date=target_date,
                    ).exists()

                    if exists:
                        skipped_campaign += 1
                        continue

                    # --------------------------------------------------
                    # Campaign -> AdGroup -> Ad -> AdMetricHistory
                    # --------------------------------------------------

                    rows = AdMetricHistory.objects.filter(
                        ad__ad_group__campaign_id=campaign_id,
                        date=target_date,
                    )

                    if not rows.exists():
                        continue

                    metrics = self._aggregate_metrics(
                        rows
                    )

                    CampaignMetricHistory.objects.create(
                        campaign_id=campaign_id,
                        date=target_date,
                        **metrics,
                    )

                    created_campaign += 1

        # ==========================================================
        # SONUÇ
        # ==========================================================

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "=============================================="
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                " TAMAMLANDI"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                "=============================================="
            )
        )

        self.stdout.write(
            f"Yeni Ad metriği        : {created_ad}"
        )

        self.stdout.write(
            f"Mevcut Ad metriği      : {skipped_ad}"
        )

        self.stdout.write(
            f"Yeni AdGroup metriği   : {created_adgroup}"
        )

        self.stdout.write(
            f"Mevcut AdGroup metriği : {skipped_adgroup}"
        )

        self.stdout.write(
            f"Yeni Campaign metriği  : {created_campaign}"
        )

        self.stdout.write(
            f"Mevcut Campaign metriği: {skipped_campaign}"
        )

        self.stdout.write(
            f"Orphan reklam          : {len(orphan_ads)}"
        )

        self.stdout.write("")

    # ==============================================================
    # AD METRİKLERİ ÜRET
    # ==============================================================

    def _generate_ad_metrics(self, ad, target_date):
        """
        Ad seviyesinde deterministik demo verisi üretir.

        Aynı:
            ad + tarih

        her zaman aynı sonucu üretir.

        Competitor reklamlarında:
            is_competitor_snapshot = True

        Normal reklamlarda:
            is_competitor_snapshot = False
        """

        seed_value = (
            f"reklamanaliz-demo:"
            f"{ad.pk}:"
            f"{target_date.isoformat()}"
        )

        rng = random.Random(seed_value)

        # ==========================================================
        # IMPRESSIONS
        # ==========================================================

        impressions = rng.randint(
            self.IMPRESSION_MIN,
            self.IMPRESSION_MAX,
        )

        # ==========================================================
        # REACH
        # ==========================================================

        reach_ratio = rng.uniform(
            0.55,
            0.90,
        )

        reach = max(
            1,
            int(impressions * reach_ratio),
        )

        # ==========================================================
        # CLICKS / CTR
        # ==========================================================

        ctr_rate = rng.uniform(
            0.006,
            0.045,
        )

        clicks = max(
            0,
            int(impressions * ctr_rate),
        )

        link_click_ratio = rng.uniform(
            0.65,
            0.95,
        )

        link_clicks = int(
            clicks * link_click_ratio
        )

        outbound_clicks = int(
            link_clicks
            * rng.uniform(
                0.85,
                1.00,
            )
        )

        unique_clicks = min(
            clicks,
            max(
                0,
                int(
                    clicks
                    * rng.uniform(
                        0.70,
                        0.95,
                    )
                ),
            ),
        )

        # ==========================================================
        # SPEND
        # ==========================================================

        cpc_base = rng.uniform(
            0.80,
            8.50,
        )

        spend = (
            Decimal(clicks)
            * Decimal(str(cpc_base))
        )

        # ==========================================================
        # CONVERSIONS
        # ==========================================================

        conversion_rate = rng.uniform(
            0.015,
            0.12,
        )

        conversions = Decimal(
            str(
                round(
                    clicks * conversion_rate,
                    2,
                )
            )
        )

        purchases = Decimal(
            str(
                round(
                    float(conversions)
                    * rng.uniform(
                        0.45,
                        0.85,
                    ),
                    2,
                )
            )
        )

        leads = Decimal(
            str(
                round(
                    float(conversions)
                    * rng.uniform(
                        0.15,
                        0.45,
                    ),
                    2,
                )
            )
        )

        add_to_cart = Decimal(
            str(
                round(
                    clicks
                    * rng.uniform(
                        0.04,
                        0.18,
                    ),
                    2,
                )
            )
        )

        initiate_checkout = Decimal(
            str(
                round(
                    float(add_to_cart)
                    * rng.uniform(
                        0.35,
                        0.80,
                    ),
                    2,
                )
            )
        )

        landing_page_views = int(
            link_clicks
            * rng.uniform(
                0.70,
                0.95,
            )
        )

        # ==========================================================
        # CONVERSION VALUE
        # ==========================================================

        average_order_value = rng.uniform(
            250,
            1800,
        )

        conversion_value = (
            Decimal(str(average_order_value))
            * purchases
        )

        # ==========================================================
        # SOCIAL ENGAGEMENT
        # ==========================================================

        likes = int(
            impressions
            * rng.uniform(
                0.001,
                0.018,
            )
        )

        comments = int(
            likes
            * rng.uniform(
                0.01,
                0.08,
            )
        )

        shares = int(
            likes
            * rng.uniform(
                0.01,
                0.06,
            )
        )

        saves = int(
            likes
            * rng.uniform(
                0.02,
                0.12,
            )
        )

        # ==========================================================
        # VIDEO
        # ==========================================================

        video_views = int(
            impressions
            * rng.uniform(
                0.15,
                0.75,
            )
        )

        # ==========================================================
        # ENGAGEMENT
        # ==========================================================

        engagement = (
            likes
            + comments
            + shares
            + saves
        )

        # ==========================================================
        # CALCULATED METRICS
        # ==========================================================

        frequency = (
            Decimal(impressions)
            / Decimal(max(reach, 1))
        )

        ctr = (
            Decimal(clicks)
            / Decimal(max(impressions, 1))
            * Decimal("100")
        )

        cpc = (
            spend
            / Decimal(max(clicks, 1))
        )

        cpm = (
            spend
            / Decimal(max(impressions, 1))
            * Decimal("1000")
        )

        cost_per_conversion = (
            spend / conversions
            if conversions > 0
            else Decimal("0")
        )

        roas = (
            conversion_value / spend
            if spend > 0
            else Decimal("0")
        )

        engagement_rate = (
            Decimal(engagement)
            / Decimal(max(reach, 1))
            * Decimal("100")
        )

        # ==========================================================
        # ESTIMATED
        # ==========================================================

        estimated_engagement = engagement

        estimated_reach_min = int(
            reach
            * rng.uniform(
                0.90,
                0.98,
            )
        )

        estimated_reach_max = int(
            reach
            * rng.uniform(
                1.02,
                1.15,
            )
        )

        # ==========================================================
        # NORMALIZATION
        # ==========================================================

        def money(value):
            return Decimal(value).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

        def ratio(value):
            return Decimal(value).quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP,
            )

        # ==========================================================
        # COMPETITOR SNAPSHOT
        # ==========================================================

        is_competitor = (
            str(ad.source_type).upper()
            == "COMPETITOR"
        )

        # ==========================================================
        # RAW METRICS
        # ==========================================================

        raw_metrics = {
            "demo": True,
            "generated": True,
            "generator": "generate_demo_daily_data",
            "date": target_date.isoformat(),
            "source_type": ad.source_type,
            "is_competitor": is_competitor,
        }

        return {
            "impressions": impressions,
            "reach": reach,
            "frequency": ratio(frequency),
            "clicks": clicks,
            "link_clicks": link_clicks,
            "unique_clicks": unique_clicks,
            "spend": money(spend),
            "currency": "TRY",
            "ctr": ratio(ctr),
            "cpc": money(cpc),
            "cpm": money(cpm),
            "conversions": ratio(conversions),
            "conversion_value": money(conversion_value),
            "cost_per_conversion": money(
                cost_per_conversion
            ),
            "purchases": ratio(purchases),
            "add_to_cart": ratio(add_to_cart),
            "initiate_checkout": ratio(
                initiate_checkout
            ),
            "leads": ratio(leads),
            "landing_page_views": landing_page_views,
            "outbound_clicks": outbound_clicks,
            "roas": ratio(roas),
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "saves": saves,
            "video_views": video_views,
            "engagement": engagement,
            "engagement_rate": ratio(
                engagement_rate
            ),
            "raw_metrics": raw_metrics,
            "estimated_engagement": estimated_engagement,
            "estimated_reach_min": estimated_reach_min,
            "estimated_reach_max": estimated_reach_max,
            "is_competitor_snapshot": is_competitor,
        }

    # ==============================================================
    # AGGREGATION
    # ==============================================================

    def _aggregate_metrics(self, rows):
        """
        AdMetricHistory kayıtlarını toplar.

        Önemli:
        Bu metod yalnızca BaseMetricHistory alanlarını döndürür.

        Böylece:
            AdGroupMetricHistory
            CampaignMetricHistory

        modellerinde bulunmayan:

            estimated_engagement
            estimated_reach_min
            estimated_reach_max

        alanlarının yanlışlıkla create() içine gönderilmesi engellenir.
        """

        rows = list(rows)

        if not rows:
            return None

        # ==========================================================
        # TOPLANAN METRİKLER
        # ==========================================================

        impressions = sum(
            int(row.impressions or 0)
            for row in rows
        )

        reach = sum(
            int(row.reach or 0)
            for row in rows
        )

        clicks = sum(
            int(row.clicks or 0)
            for row in rows
        )

        link_clicks = sum(
            int(row.link_clicks or 0)
            for row in rows
        )

        unique_clicks = sum(
            int(row.unique_clicks or 0)
            for row in rows
        )

        spend = sum(
            (
                Decimal(row.spend or 0)
                for row in rows
            ),
            Decimal("0"),
        )

        conversions = sum(
            (
                Decimal(row.conversions or 0)
                for row in rows
            ),
            Decimal("0"),
        )

        conversion_value = sum(
            (
                Decimal(row.conversion_value or 0)
                for row in rows
            ),
            Decimal("0"),
        )

        purchases = sum(
            (
                Decimal(row.purchases or 0)
                for row in rows
            ),
            Decimal("0"),
        )

        add_to_cart = sum(
            (
                Decimal(row.add_to_cart or 0)
                for row in rows
            ),
            Decimal("0"),
        )

        initiate_checkout = sum(
            (
                Decimal(row.initiate_checkout or 0)
                for row in rows
            ),
            Decimal("0"),
        )

        leads = sum(
            (
                Decimal(row.leads or 0)
                for row in rows
            ),
            Decimal("0"),
        )

        landing_page_views = sum(
            int(row.landing_page_views or 0)
            for row in rows
        )

        outbound_clicks = sum(
            int(row.outbound_clicks or 0)
            for row in rows
        )

        likes = sum(
            int(row.likes or 0)
            for row in rows
        )

        comments = sum(
            int(row.comments or 0)
            for row in rows
        )

        shares = sum(
            int(row.shares or 0)
            for row in rows
        )

        saves = sum(
            int(row.saves or 0)
            for row in rows
        )

        video_views = sum(
            int(row.video_views or 0)
            for row in rows
        )

        engagement = (
            likes
            + comments
            + shares
            + saves
        )

        # ==========================================================
        # HESAPLANAN METRİKLER
        # ==========================================================

        frequency = (
            Decimal(impressions)
            / Decimal(max(reach, 1))
        )

        ctr = (
            Decimal(clicks)
            / Decimal(max(impressions, 1))
            * Decimal("100")
        )

        cpc = (
            spend
            / Decimal(max(clicks, 1))
        )

        cpm = (
            spend
            / Decimal(max(impressions, 1))
            * Decimal("1000")
        )

        cost_per_conversion = (
            spend / conversions
            if conversions > 0
            else Decimal("0")
        )

        roas = (
            conversion_value / spend
            if spend > 0
            else Decimal("0")
        )

        engagement_rate = (
            Decimal(engagement)
            / Decimal(max(reach, 1))
            * Decimal("100")
        )

        # ==========================================================
        # NORMALIZATION
        # ==========================================================

        def money(value):
            return Decimal(value).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

        def ratio(value):
            return Decimal(value).quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP,
            )

        # ==========================================================
        # RESULT
        # ==========================================================

        return {
            "impressions": impressions,
            "reach": reach,
            "frequency": ratio(frequency),
            "clicks": clicks,
            "link_clicks": link_clicks,
            "unique_clicks": unique_clicks,
            "spend": money(spend),
            "currency": "TRY",
            "ctr": ratio(ctr),
            "cpc": money(cpc),
            "cpm": money(cpm),
            "conversions": ratio(conversions),
            "conversion_value": money(
                conversion_value
            ),
            "cost_per_conversion": money(
                cost_per_conversion
            ),
            "purchases": ratio(purchases),
            "add_to_cart": ratio(add_to_cart),
            "initiate_checkout": ratio(
                initiate_checkout
            ),
            "leads": ratio(leads),
            "landing_page_views": landing_page_views,
            "outbound_clicks": outbound_clicks,
            "roas": ratio(roas),
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "saves": saves,
            "video_views": video_views,
            "engagement": engagement,
            "engagement_rate": ratio(
                engagement_rate
            ),
            "raw_metrics": {
                "demo": True,
                "generated": True,
                "generator": "generate_demo_daily_data",
                "aggregated": True,
            },
        }