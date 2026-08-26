from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import (
    Ad,
    AdGroupMetricHistory,
    AdMetricHistory,
    AgencyClient,
    Campaign,
    CampaignMetricHistory,
    CreativeMetricHistory,
    Organization,
    PlatformAccount,
    PlatformConnection,
)
from core.services.cache_service import CacheService, DashboardCacheManager


INTEGER_FIELDS = (
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
)
DECIMAL_TOTAL_FIELDS = (
    "spend",
    "conversions",
    "conversion_value",
    "purchases",
    "add_to_cart",
    "initiate_checkout",
    "leads",
)
METRIC_UPDATE_FIELDS = [
    *INTEGER_FIELDS,
    "frequency",
    "spend",
    "currency",
    "ctr",
    "cpc",
    "cpm",
    "conversions",
    "conversion_value",
    "cost_per_conversion",
    "purchases",
    "add_to_cart",
    "initiate_checkout",
    "leads",
    "roas",
    "engagement_rate",
    "raw_metrics",
]


def _decimal(value, places="0.01"):
    return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


class Command(BaseCommand):
    help = (
        "Demo ajansın sentetik hesaplarını Demo Marka'ya bağlar ve yalnız sentetik "
        "kampanya/reklamlar için son 90 günlük metrik geçmişini güvenle yeniler."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", default="demo")
        parser.add_argument("--client-name", default="Demo Marka")
        parser.add_argument("--days", type=int, default=90)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--remove-live-connections", action="store_true")

    def handle(self, *args, **options):
        username = options["username"]
        client_name = options["client_name"]
        days = max(30, min(int(options["days"]), 365))
        dry_run = options["dry_run"]
        remove_live_connections = options["remove_live_connections"]

        user = get_user_model().objects.filter(username=username, is_active=True).first()
        if not user:
            raise CommandError(f"Aktif kullanıcı bulunamadı: {username}")

        organization = Organization.objects.filter(owner=user, is_active=True).order_by("id").first()
        if not organization:
            raise CommandError(f"{username} için aktif ajans organizasyonu bulunamadı.")

        client = AgencyClient.objects.filter(
            organization=organization,
            name=client_name,
        ).first()
        if not client and dry_run:
            raise CommandError(f"Dry-run sırasında müşteri bulunamadı: {client_name}")

        synthetic_accounts = list(
            PlatformAccount.objects.filter(user=user)
            .filter(Q(extra_data__demo=True) | Q(account_id__startswith="demo-"))
            .order_by("id")
        )
        all_synthetic_account_ids = [account.id for account in synthetic_accounts]
        demo_account_ids = []
        for account in synthetic_accounts:
            marker = (account.extra_data or {}).get("demo_agency_client")
            if marker == client_name or (not marker and client_name == "Demo Marka"):
                demo_account_ids.append(account.id)
        demo_accounts = PlatformAccount.objects.filter(id__in=demo_account_ids).order_by("id")
        live_accounts = PlatformAccount.objects.filter(user=user).exclude(id__in=all_synthetic_account_ids)
        live_account_count = live_accounts.count()
        demo_connection_ids = set(
            demo_accounts.exclude(connection_id=None).values_list("connection_id", flat=True)
        )
        live_connection_ids = [
            connection.id
            for connection in PlatformConnection.objects.filter(user=user)
            if connection.id not in demo_connection_ids and not (connection.extra_data or {}).get("demo")
        ]
        if not demo_accounts.exists():
            raise CommandError("Güncellenecek sentetik demo platform hesabı bulunamadı.")

        demo_campaigns = Campaign.objects.filter(platform_account__in=demo_accounts).order_by("id")
        demo_ads = (
            Ad.objects.filter(
                platform_account__in=demo_accounts,
                source_type="OWN",
            )
            .select_related("campaign", "ad_group", "creative", "platform_account")
            .order_by("id")
        )

        self.stdout.write(
            f"Kapsam: organizasyon={organization.name}, müşteri={client_name}, "
            f"sentetik_hesap={demo_accounts.count()}, canlı_hesap={live_account_count}, "
            f"canlı_bağlantı={len(live_connection_ids)}, "
            f"kampanya={demo_campaigns.count()}, reklam={demo_ads.count()}, gün={days}"
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run tamamlandı; veritabanında değişiklik yapılmadı."))
            return

        today = timezone.localdate()
        start_date = today - timedelta(days=days - 1)
        now = timezone.now()

        with transaction.atomic():
            client, _ = AgencyClient.objects.get_or_create(
                organization=organization,
                name=client_name,
                defaults={
                    "legal_name": f"{client_name} Ticaret A.Ş.",
                    "notes": "Rapor doğrulama için sentetik demo verileri.",
                    "is_active": True,
                },
            )
            if not client.is_active:
                client.is_active = True
                client.save(update_fields=["is_active", "updated_at"])

            removed_live_accounts = 0
            removed_live_connections = 0
            removed_live_related = 0
            if remove_live_connections:
                (
                    removed_live_accounts,
                    removed_live_connections,
                    removed_live_related,
                ) = self._delete_live_scope(live_accounts, live_connection_ids)

            # Her sentetik hesap kalıcı bir müşteri işareti taşır. Böylece komut
            # tekrar çalıştırıldığında başka ajans müşterisinin hesabını devralmaz.
            account_objects = list(demo_accounts)
            for account in account_objects:
                account.agency_client = client
                account.extra_data = {
                    **(account.extra_data or {}),
                    "demo": True,
                    "demo_agency_client": client_name,
                }
            PlatformAccount.objects.bulk_update(
                account_objects,
                ["agency_client", "extra_data"],
                batch_size=250,
            )

            campaign_objects = list(demo_campaigns)
            for campaign in campaign_objects:
                campaign.status = "ACTIVE"
                campaign.start_time = now - timedelta(days=days - 1)
                campaign.last_synced_at = now
                campaign.raw_data = {
                    **(campaign.raw_data or {}),
                    "demo": True,
                    "demo_agency_history": True,
                    "history_days": days,
                }
            Campaign.objects.bulk_update(
                campaign_objects,
                ["status", "start_time", "last_synced_at", "raw_data"],
                batch_size=250,
            )

            ad_objects = list(demo_ads)
            for ad in ad_objects:
                ad.status = "ACTIVE"
                ad.started_at = now - timedelta(days=days - 1)
                ad.first_seen_at = now - timedelta(days=days - 1)
                ad.last_seen_at = now
                ad.last_synced_at = now
                ad.raw_data = {
                    **(ad.raw_data or {}),
                    "demo": True,
                    "demo_agency_history": True,
                    "history_days": days,
                }
            Ad.objects.bulk_update(
                ad_objects,
                ["status", "started_at", "first_seen_at", "last_seen_at", "last_synced_at", "raw_data"],
                batch_size=250,
            )

            self._trim_old_history(ad_objects, start_date, today)
            counts = self._refresh_history(ad_objects, start_date, days)

            DashboardCacheManager.invalidate_user_dashboard(user.id)
            CacheService.bump_version("control_tower", user.id)

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo ajans geçmişi yenilendi: {start_date} - {today}; "
                f"ad={counts['ad']}, campaign={counts['campaign']}, "
                f"adgroup={counts['adgroup']}, creative={counts['creative']}"
            )
        )
        if remove_live_connections:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Demo kullanıcıdan canlı hesap/bağlantı kaldırıldı: "
                    f"hesap={removed_live_accounts}, bağlantı={removed_live_connections}, "
                    f"bağlı_kayıt={removed_live_related}."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{live_account_count} canlı hesap korundu; token ve bağlantı ayarları değiştirilmedi."
                )
            )

    def _delete_live_scope(self, live_accounts, live_connection_ids):
        """Delete every record directly tied to demo user's real connections.

        Several legacy relations use SET_NULL. Deleting only PlatformAccount or
        PlatformConnection would leave orphan campaign/social/raw-data rows, so
        those reverse relations are explicitly deleted first.
        """
        accounts = list(live_accounts)
        connections = list(
            PlatformConnection.objects.filter(id__in=live_connection_ids).order_by("id")
        )
        related_deleted = 0

        for instance in [*accounts, *connections]:
            for relation in instance._meta.related_objects:
                if relation.many_to_many:
                    continue
                related_model = relation.related_model
                relation_filter = {relation.field.name: instance}
                queryset = related_model.objects.filter(**relation_filter)
                count = queryset.count()
                if count:
                    queryset.delete()
                    related_deleted += count

        account_count = len(accounts)
        if account_count:
            PlatformAccount.objects.filter(id__in=[account.id for account in accounts]).delete()

        connection_count = len(connections)
        if connection_count:
            PlatformConnection.objects.filter(id__in=[connection.id for connection in connections]).delete()

        return account_count, connection_count, related_deleted

    def _trim_old_history(self, ads, start_date, end_date):
        ad_ids = [ad.id for ad in ads]
        campaign_ids = {ad.campaign_id for ad in ads if ad.campaign_id}
        ad_group_ids = {ad.ad_group_id for ad in ads if ad.ad_group_id}
        creative_ids = {ad.creative_id for ad in ads if ad.creative_id}
        date_range = (start_date, end_date)

        AdMetricHistory.objects.filter(ad_id__in=ad_ids).exclude(date__range=date_range).delete()
        CampaignMetricHistory.objects.filter(campaign_id__in=campaign_ids).exclude(date__range=date_range).delete()
        AdGroupMetricHistory.objects.filter(ad_group_id__in=ad_group_ids).exclude(date__range=date_range).delete()
        CreativeMetricHistory.objects.filter(creative_id__in=creative_ids).exclude(date__range=date_range).delete()

    def _refresh_history(self, ads, start_date, days):
        ad_rows = []
        campaign_metrics = defaultdict(list)
        ad_group_metrics = defaultdict(list)
        creative_metrics = defaultdict(list)

        for day_index in range(days):
            date = start_date + timedelta(days=day_index)
            for ad in ads:
                metrics = self._daily_metrics(ad, date, day_index, days)
                ad_rows.append(
                    AdMetricHistory(
                        ad_id=ad.id,
                        date=date,
                        estimated_engagement=metrics["engagement"],
                        estimated_reach_min=metrics["reach"],
                        estimated_reach_max=metrics["impressions"],
                        is_competitor_snapshot=False,
                        **metrics,
                    )
                )
                if ad.campaign_id:
                    campaign_metrics[(ad.campaign_id, date)].append(metrics)
                if ad.ad_group_id:
                    ad_group_metrics[(ad.ad_group_id, date)].append(metrics)
                if ad.creative_id:
                    creative_metrics[(ad.creative_id, date)].append(metrics)

        self._upsert(
            AdMetricHistory,
            ad_rows,
            [*METRIC_UPDATE_FIELDS, "estimated_engagement", "estimated_reach_min", "estimated_reach_max", "is_competitor_snapshot"],
            ["ad", "date"],
        )

        campaign_rows = [
            CampaignMetricHistory(campaign_id=entity_id, date=date, **self._rollup(rows))
            for (entity_id, date), rows in campaign_metrics.items()
        ]
        ad_group_rows = [
            AdGroupMetricHistory(ad_group_id=entity_id, date=date, **self._rollup(rows))
            for (entity_id, date), rows in ad_group_metrics.items()
        ]
        creative_rows = []
        for (entity_id, date), rows in creative_metrics.items():
            rolled = self._rollup(rows)
            creative_rows.append(
                CreativeMetricHistory(
                    creative_id=entity_id,
                    date=date,
                    thumbstop_rate=_decimal(18 + float(rolled["ctr"]) * 3.2, "0.0001"),
                    hook_rate=_decimal(14 + float(rolled["ctr"]) * 2.4, "0.0001"),
                    hold_rate=_decimal(10 + float(rolled["ctr"]) * 1.8, "0.0001"),
                    **rolled,
                )
            )

        self._upsert(CampaignMetricHistory, campaign_rows, METRIC_UPDATE_FIELDS, ["campaign", "date"])
        self._upsert(AdGroupMetricHistory, ad_group_rows, METRIC_UPDATE_FIELDS, ["ad_group", "date"])
        self._upsert(
            CreativeMetricHistory,
            creative_rows,
            [*METRIC_UPDATE_FIELDS, "thumbstop_rate", "hook_rate", "hold_rate"],
            ["creative", "date"],
        )
        return {
            "ad": len(ad_rows),
            "campaign": len(campaign_rows),
            "adgroup": len(ad_group_rows),
            "creative": len(creative_rows),
        }

    def _upsert(self, model, rows, update_fields, unique_fields):
        if not rows:
            return
        model.objects.bulk_create(
            rows,
            batch_size=500,
            update_conflicts=True,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )

    def _daily_metrics(self, ad, date, day_index, days):
        seed_text = f"{ad.platform_ad_id or ad.id}:{date.isoformat()}"
        seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16)
        rng = random.Random(seed)
        progress = day_index / max(days - 1, 1)
        growth = 0.84 + progress * 0.30
        wave = 1 + math.sin(day_index / 7.5 + ad.id % 6) * 0.12
        platform_factor = 1 + (ad.platform_account_id % 5) * 0.07

        impressions = max(250, int((1450 + (ad.id % 9) * 175) * growth * wave * platform_factor * rng.uniform(0.88, 1.12)))
        ctr_rate = rng.uniform(0.012, 0.042) * (0.90 + progress * 0.16)
        clicks = max(1, int(impressions * ctr_rate))
        spend = _decimal((impressions / 1000) * rng.uniform(30, 78))
        conversions = _decimal(clicks * rng.uniform(0.025, 0.082), "0.0001")
        conversion_value = _decimal(float(conversions) * rng.uniform(620, 1480))
        reach = max(1, int(impressions * rng.uniform(0.64, 0.84)))
        engagement = max(clicks, int(impressions * rng.uniform(0.022, 0.071)))

        return {
            "impressions": impressions,
            "reach": reach,
            "frequency": _decimal(impressions / reach, "0.0001"),
            "clicks": clicks,
            "link_clicks": int(clicks * rng.uniform(0.74, 0.92)),
            "unique_clicks": int(clicks * rng.uniform(0.66, 0.86)),
            "spend": spend,
            "currency": "TRY",
            "ctr": _decimal(clicks / impressions * 100, "0.0001"),
            "cpc": _decimal(float(spend) / clicks, "0.0001"),
            "cpm": _decimal(float(spend) / impressions * 1000, "0.0001"),
            "conversions": conversions,
            "conversion_value": conversion_value,
            "cost_per_conversion": _decimal(float(spend) / max(float(conversions), 0.0001), "0.0001"),
            "purchases": conversions,
            "add_to_cart": _decimal(float(conversions) * rng.uniform(1.8, 3.6), "0.0001"),
            "initiate_checkout": _decimal(float(conversions) * rng.uniform(1.25, 2.2), "0.0001"),
            "leads": _decimal(clicks * rng.uniform(0.02, 0.09), "0.0001"),
            "landing_page_views": int(clicks * rng.uniform(0.58, 0.84)),
            "outbound_clicks": int(clicks * rng.uniform(0.46, 0.76)),
            "roas": _decimal(float(conversion_value) / max(float(spend), 0.01), "0.0001"),
            "likes": int(engagement * rng.uniform(0.42, 0.66)),
            "comments": int(engagement * rng.uniform(0.05, 0.13)),
            "shares": int(engagement * rng.uniform(0.06, 0.17)),
            "saves": int(engagement * rng.uniform(0.08, 0.20)),
            "video_views": int(impressions * rng.uniform(0.14, 0.46)),
            "engagement": engagement,
            "engagement_rate": _decimal(engagement / impressions * 100, "0.0001"),
            "raw_metrics": {
                "demo": True,
                "synthetic": True,
                "demo_agency_history": True,
                "source": "refresh_demo_agency_history",
            },
        }

    def _rollup(self, rows):
        totals = {field: sum(int(row[field]) for row in rows) for field in INTEGER_FIELDS}
        totals.update(
            {
                field: sum((Decimal(row[field]) for row in rows), Decimal("0"))
                for field in DECIMAL_TOTAL_FIELDS
            }
        )
        impressions = totals["impressions"]
        reach = totals["reach"]
        clicks = totals["clicks"]
        spend = totals["spend"]
        conversions = totals["conversions"]
        value = totals["conversion_value"]
        totals.update(
            {
                "frequency": _decimal(impressions / max(reach, 1), "0.0001"),
                "currency": "TRY",
                "ctr": _decimal(clicks / max(impressions, 1) * 100, "0.0001"),
                "cpc": _decimal(float(spend) / max(clicks, 1), "0.0001"),
                "cpm": _decimal(float(spend) / max(impressions, 1) * 1000, "0.0001"),
                "cost_per_conversion": _decimal(float(spend) / max(float(conversions), 0.0001), "0.0001"),
                "roas": _decimal(float(value) / max(float(spend), 0.01), "0.0001"),
                "engagement_rate": _decimal(totals["engagement"] / max(impressions, 1) * 100, "0.0001"),
                "raw_metrics": {
                    "demo": True,
                    "synthetic": True,
                    "demo_agency_history": True,
                    "rolled_up": True,
                },
            }
        )
        return totals
