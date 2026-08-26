from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import (
    Ad,
    AdMetricHistory,
    CampaignMetricHistory,
    AdGroupMetricHistory,
    CreativeMetricHistory,
)
from core.services.performance_metrics import normalize_metric_payload


METRIC_SUM_FIELDS = [
    "impressions",
    "reach",
    "clicks",
    "link_clicks",
    "unique_clicks",
    "spend",
    "conversions",
    "conversion_value",
    "likes",
    "comments",
    "shares",
    "saves",
    "video_views",
    "engagement",
]


def _d(value):
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _q(value, places="0.0001"):
    return _d(value).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _empty_bucket():
    return {
        "impressions": 0,
        "reach": 0,
        "clicks": 0,
        "link_clicks": 0,
        "unique_clicks": 0,
        "spend": Decimal("0"),
        "conversions": Decimal("0"),
        "conversion_value": Decimal("0"),
        "likes": 0,
        "comments": 0,
        "shares": 0,
        "saves": 0,
        "video_views": 0,
        "engagement": 0,
        "currency": "TRY",
    }


def _is_competitor_metric(metric):
    """
    Rakip reklamları kampanya/reklam grubu hiyerarşisine dahil edilmez.
    Bu kayıtlar competitor analizlerinde ayrı değerlendirilir.
    """
    ad = metric.ad
    return (
        getattr(metric, "is_competitor_snapshot", False)
        or getattr(ad, "source_type", None) == "COMPETITOR"
        or getattr(ad, "competitor_id", None) is not None
    )


def _add_metric(bucket, metric):
    for field in METRIC_SUM_FIELDS:
        current = bucket[field]
        value = getattr(metric, field, 0) or 0
        if isinstance(current, Decimal):
            bucket[field] = current + _d(value)
        else:
            bucket[field] = current + int(value)

    if getattr(metric, "currency", None):
        bucket["currency"] = metric.currency


def _calculated_values(bucket):
    payload = normalize_metric_payload({
        **bucket,
        "raw_metrics": {
            "source": "backfill_metric_histories_from_ads",
            "aggregation": "summed_from_own_ad_metric_history",
            "competitor_ads": "excluded",
        },
    })
    return payload


class Command(BaseCommand):
    help = (
        "Kendi reklamlarına ait AdMetricHistory verilerinden "
        "CampaignMetricHistory, AdGroupMetricHistory ve CreativeMetricHistory üretir/günceller. "
        "Rakip reklam metriklerini bilinçli olarak atlar."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--campaign-id",
            type=int,
            default=None,
            help="Sadece belirtilen kampanya ID için backfill yapar.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Veritabanına yazmadan kaç kayıt üretileceğini gösterir.",
        )

    def handle(self, *args, **options):
        campaign_id = options.get("campaign_id")
        dry_run = options.get("dry_run")

        ad_qs = Ad.objects.select_related("campaign", "ad_group", "creative", "competitor")
        if campaign_id:
            ad_qs = ad_qs.filter(campaign_id=campaign_id)

        metrics_qs = (
            AdMetricHistory.objects
            .select_related("ad", "ad__campaign", "ad__ad_group", "ad__creative", "ad__competitor")
            .filter(ad__in=ad_qs)
            .order_by("id")
        )

        campaign_buckets = defaultdict(_empty_bucket)
        adgroup_buckets = defaultdict(_empty_bucket)
        creative_buckets = defaultdict(_empty_bucket)

        processed = 0
        own_processed = 0
        skipped_competitor = 0
        skipped_own_no_campaign = 0
        skipped_own_no_adgroup = 0
        skipped_own_no_creative = 0

        sample_competitor_ads = []
        sample_broken_own_ads = []

        for metric in metrics_qs.iterator(chunk_size=1000):
            ad = metric.ad
            processed += 1

            if _is_competitor_metric(metric):
                skipped_competitor += 1
                if len(sample_competitor_ads) < 5:
                    sample_competitor_ads.append(f"#{ad.id} - {ad.name or ad.headline or 'Adsız rakip reklam'}")
                continue

            own_processed += 1

            if ad.campaign_id:
                _add_metric(campaign_buckets[(ad.campaign_id, metric.date)], metric)
            else:
                skipped_own_no_campaign += 1
                if len(sample_broken_own_ads) < 5:
                    sample_broken_own_ads.append(f"#{ad.id} - {ad.name or ad.headline or 'Adsız reklam'}")

            if ad.ad_group_id:
                _add_metric(adgroup_buckets[(ad.ad_group_id, metric.date)], metric)
            else:
                skipped_own_no_adgroup += 1

            if ad.creative_id:
                _add_metric(creative_buckets[(ad.creative_id, metric.date)], metric)
            else:
                skipped_own_no_creative += 1

        self.stdout.write(self.style.NOTICE(f"İşlenen toplam AdMetricHistory: {processed}"))
        self.stdout.write(self.style.NOTICE(f"Kendi reklam metriği: {own_processed}"))
        self.stdout.write(self.style.NOTICE(f"Rakip reklam metriği bilinçli atlandı: {skipped_competitor}"))
        self.stdout.write(self.style.NOTICE(f"Campaign bucket: {len(campaign_buckets)}"))
        self.stdout.write(self.style.NOTICE(f"AdGroup bucket: {len(adgroup_buckets)}"))
        self.stdout.write(self.style.NOTICE(f"Creative bucket: {len(creative_buckets)}"))

        if sample_competitor_ads:
            self.stdout.write(self.style.WARNING("Örnek atlanan rakip reklamlar:"))
            for item in sample_competitor_ads:
                self.stdout.write(self.style.WARNING(f"  - {item}"))

        if skipped_own_no_campaign or skipped_own_no_adgroup or skipped_own_no_creative:
            self.stdout.write(
                self.style.ERROR(
                    "Kendi reklamlarında eksik ilişki var - "
                    f"campaign yok: {skipped_own_no_campaign}, "
                    f"ad_group yok: {skipped_own_no_adgroup}, "
                    f"creative yok: {skipped_own_no_creative}"
                )
            )
            if sample_broken_own_ads:
                self.stdout.write(self.style.ERROR("Örnek eksik ilişkili kendi reklamlar:"))
                for item in sample_broken_own_ads:
                    self.stdout.write(self.style.ERROR(f"  - {item}"))
        else:
            self.stdout.write(self.style.SUCCESS("Kendi reklam ilişkilerinde eksik bağlantı bulunmadı."))

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run aktif: veritabanına yazılmadı."))
            return

        campaign_written = 0
        adgroup_written = 0
        creative_written = 0

        with transaction.atomic():
            for (campaign_id_value, date), bucket in campaign_buckets.items():
                CampaignMetricHistory.objects.update_or_create(
                    campaign_id=campaign_id_value,
                    date=date,
                    defaults=_calculated_values(bucket),
                )
                campaign_written += 1

            for (adgroup_id_value, date), bucket in adgroup_buckets.items():
                AdGroupMetricHistory.objects.update_or_create(
                    ad_group_id=adgroup_id_value,
                    date=date,
                    defaults=_calculated_values(bucket),
                )
                adgroup_written += 1

            for (creative_id_value, date), bucket in creative_buckets.items():
                CreativeMetricHistory.objects.update_or_create(
                    creative_id=creative_id_value,
                    date=date,
                    defaults=_calculated_values(bucket),
                )
                creative_written += 1

        self.stdout.write(self.style.SUCCESS("Backfill tamamlandı."))
        self.stdout.write(self.style.SUCCESS(f"CampaignMetricHistory yazılan/güncellenen: {campaign_written}"))
        self.stdout.write(self.style.SUCCESS(f"AdGroupMetricHistory yazılan/güncellenen: {adgroup_written}"))
        self.stdout.write(self.style.SUCCESS(f"CreativeMetricHistory yazılan/güncellenen: {creative_written}"))
