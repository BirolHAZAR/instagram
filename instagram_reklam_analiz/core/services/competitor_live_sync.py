from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

from core.models import Ad, AdMetricHistory, Competitor, Creative


SUPPORTED_META_PLATFORMS = {"instagram", "facebook"}


class CompetitorSyncError(Exception):
    pass


def _first(value, default=""):
    if isinstance(value, list):
        return value[0] if value else default
    return value if value not in (None, "") else default


def _parse_dt(value):
    if not value:
        return None
    try:
        if len(value) == 10:
            return timezone.make_aware(datetime.fromisoformat(value))
        return timezone.make_aware(datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None))
    except Exception:
        return None


def _range_average(value):
    if isinstance(value, dict):
        lower = Decimal(str(value.get("lower_bound") or value.get("min") or 0))
        upper = Decimal(str(value.get("upper_bound") or value.get("max") or lower or 0))
        return (lower + upper) / Decimal("2") if upper else lower
    if isinstance(value, (int, float, Decimal, str)) and value != "":
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal("0")
    return Decimal("0")


def _engagement_estimate(impressions):
    return int(Decimal(impressions or 0) * Decimal("0.027"))


def _q4(value):
    return Decimal(value or 0).quantize(Decimal("0.0001"))


def _q2(value):
    return Decimal(value or 0).quantize(Decimal("0.01"))


def _token_for_competitor(competitor):
    account = competitor.platform_account
    connection = getattr(account, "connection", None) if account else None
    token = ""
    if connection and getattr(connection, "access_token", "") and connection.status == "active" and not connection.is_token_expired:
        token = connection.access_token
    if not token and account and getattr(account, "access_token", ""):
        token = account.access_token
    if not token:
        token = getattr(settings, "META_AD_LIBRARY_ACCESS_TOKEN", "") or getattr(settings, "INSTAGRAM_ACCESS_TOKEN", "")
    return token


def _ad_reached_countries_param():
    countries = getattr(settings, "META_AD_LIBRARY_COUNTRIES", ["TR"]) or ["TR"]
    countries = [str(country).strip().upper() for country in countries if str(country).strip()]
    if getattr(settings, "META_AD_LIBRARY_COUNTRIES_FORMAT", "comma") == "array_string":
        return "[" + ",".join(f"'{country}'" for country in countries) + "]"
    return ",".join(countries)


def _normalize_page_ids(value):
    if not value:
        return []
    values = value if isinstance(value, list) else str(value).split(",")
    page_ids = []
    for item in values:
        page_id = str(item).strip()
        if page_id.isdigit():
            page_ids.append(page_id)
    return page_ids


def _page_ids_for_competitor(competitor):
    raw_data = competitor.raw_data or {}
    page_ids = []
    page_ids.extend(_normalize_page_ids(raw_data.get("facebook_page_ids")))
    page_ids.extend(_normalize_page_ids(raw_data.get("facebook_page_id")))
    page_ids.extend(_normalize_page_ids(raw_data.get("page_ids")))
    page_ids.extend(_normalize_page_ids(raw_data.get("page_id")))
    page_ids.extend(_normalize_page_ids(competitor.platform_identifier))
    return list(dict.fromkeys(page_ids))


def _search_term(competitor):
    raw = (competitor.platform_identifier or competitor.name or "").strip()
    return raw.lstrip("@").replace("_", " ") or competitor.name


class MetaAdLibraryCompetitorSync:
    def __init__(self, competitor: Competitor):
        self.competitor = competitor
        self.platform_code = getattr(competitor.platform, "code", "") if competitor.platform else ""
        self.token = _token_for_competitor(competitor)
        self.graph_url = getattr(settings, "FACEBOOK_GRAPH_URL", "https://graph.facebook.com/v25.0").rstrip("/")

    def sync(self, limit=None):
        if self.platform_code not in SUPPORTED_META_PLATFORMS:
            raise CompetitorSyncError(
                f"{self.platform_code or 'unknown'} için canlı rakip reklam çekimi desteklenmiyor. "
                "Canlı kaynak olarak şu an Meta Ad Library üzerinden Instagram/Facebook desteklenir."
            )
        if not self.token or self.token.startswith("demo") or self.token.startswith("placeholder"):
            raise CompetitorSyncError(
                "Meta Ad Library token bulunamadı. .env içine META_AD_LIBRARY_ACCESS_TOKEN veya geçerli Meta bağlantı tokenı eklenmeli."
            )

        payload = self._fetch(limit=limit)
        rows = payload.get("data") or []
        created = 0
        updated = 0
        ads = []
        for row in rows:
            ad, was_created = self._upsert_ad(row)
            ads.append(ad)
            if was_created:
                created += 1
            else:
                updated += 1

        self.competitor.total_ads_seen = Ad.objects.filter(
            user=self.competitor.user,
            source_type="COMPETITOR",
            competitor=self.competitor,
        ).count()
        self.competitor.last_seen_at = timezone.now()
        raw_data = self.competitor.raw_data or {}
        raw_data.update({
            "last_live_sync_at": timezone.now().isoformat(),
            "last_live_sync_source": "meta_ad_library",
            "last_live_sync_count": len(rows),
            "search_term": _search_term(self.competitor),
            "search_page_ids": _page_ids_for_competitor(self.competitor),
        })
        self.competitor.raw_data = raw_data
        self.competitor.save(update_fields=["total_ads_seen", "last_seen_at", "raw_data", "updated_at"])

        return {
            "success": True,
            "provider": "meta_ad_library",
            "created": created,
            "updated": updated,
            "total": self.competitor.total_ads_seen,
            "fetched": len(rows),
            "ads": [ad.id for ad in ads],
        }

    def _fetch(self, limit=None):
        page_ids = _page_ids_for_competitor(self.competitor)
        params = {
            "access_token": self.token,
            "ad_reached_countries": _ad_reached_countries_param(),
            "search_type": getattr(settings, "META_AD_LIBRARY_SEARCH_TYPE", "KEYWORD_UNORDERED"),
            "ad_active_status": getattr(settings, "META_AD_LIBRARY_ACTIVE_STATUS", "ALL"),
            "ad_type": getattr(settings, "META_AD_LIBRARY_AD_TYPE", "ALL"),
            "limit": int(limit or getattr(settings, "META_AD_LIBRARY_LIMIT", 50) or 50),
            "fields": ",".join([
                "id",
                "ad_creation_time",
                "ad_creative_bodies",
                "ad_creative_link_captions",
                "ad_creative_link_descriptions",
                "ad_creative_link_titles",
                "ad_delivery_start_time",
                "ad_delivery_stop_time",
                "ad_snapshot_url",
                "currency",
                "demographic_distribution",
                "funding_entity",
                "impressions",
                "page_id",
                "page_name",
                "publisher_platforms",
                "spend",
            ]),
        }
        if page_ids:
            params["search_page_ids"] = ",".join(page_ids)
        else:
            params["search_terms"] = _search_term(self.competitor)
        try:
            response = requests.get(f"{self.graph_url}/ads_archive", params=params, timeout=30)
        except requests.RequestException as exc:
            raise CompetitorSyncError(
                "Meta Ad Library baglantisi kurulamadi. Ag erisimi, firewall veya Meta Graph API erisimi kontrol edilmeli."
            ) from exc
        try:
            data = response.json()
        except ValueError:
            data = {"error": {"message": response.text[:300]}}
        if response.status_code >= 400 or data.get("error"):
            error = data.get("error", {})
            message = error.get("message") if isinstance(error, dict) else error
            code = error.get("code") if isinstance(error, dict) else None
            if code == 10 and message == "Application does not have permission for this action":
                message = (
                    "Meta uygulamasinda Ad Library API/ads_archive erisimi yok. "
                    "Meta App Review uzerinden Ad Library API erisimi onaylanmadan rakip reklamlari canli cekilemez."
                )
            raise CompetitorSyncError(f"Meta Ad Library hata verdi: {message or response.status_code}")
        return data

    def _upsert_ad(self, row: dict[str, Any]):
        now = timezone.now()
        platform_ad_id = str(row.get("id") or "")
        title = _first(row.get("ad_creative_link_titles"), self.competitor.name or "Rakip Reklam")
        body = _first(row.get("ad_creative_bodies"), "")
        description = _first(row.get("ad_creative_link_descriptions"), "")
        caption = _first(row.get("ad_creative_link_captions"), "")
        snapshot_url = row.get("ad_snapshot_url") or ""
        start_time = _parse_dt(row.get("ad_delivery_start_time") or row.get("ad_creation_time"))
        stop_time = _parse_dt(row.get("ad_delivery_stop_time"))
        is_active = stop_time is None or stop_time >= now
        creative_type = "UNKNOWN"
        platforms = row.get("publisher_platforms") or []
        if isinstance(platforms, list) and any(str(p).lower() == "instagram" for p in platforms):
            creative_type = "IMAGE"

        creative, _ = Creative.objects.update_or_create(
            user=self.competitor.user,
            platform_connection=getattr(self.competitor.platform_account, "connection", None),
            platform_account=self.competitor.platform_account,
            platform_creative_id=f"meta-library-{platform_ad_id}",
            defaults={
                "creative_type": creative_type,
                "name": title or f"Rakip Kreatif {platform_ad_id}",
                "title": title,
                "body_text": body,
                "description": description,
                "landing_url": snapshot_url,
                "raw_data": row,
                "first_seen_at": start_time or now,
                "last_seen_at": now,
            },
        )

        ad, created = Ad.objects.update_or_create(
            user=self.competitor.user,
            source_type="COMPETITOR",
            platform_ad_id=platform_ad_id,
            competitor=self.competitor,
            defaults={
                "platform_connection": getattr(self.competitor.platform_account, "connection", None),
                "platform_account": self.competitor.platform_account,
                "creative": creative,
                "ad_library_id": platform_ad_id,
                "name": title or f"{self.competitor.name} Reklam",
                "status": "ACTIVE" if is_active else "ENDED",
                "ad_format": creative_type,
                "objective": "UNKNOWN",
                "headline": title,
                "primary_text": body,
                "description": description or caption,
                "landing_url": snapshot_url,
                "preview_image_url": "",
                "first_seen_at": start_time,
                "last_seen_at": now,
                "ended_at": stop_time,
                "raw_data": {
                    "provider": "meta_ad_library",
                    "snapshot_url": snapshot_url,
                    "publisher_platforms": platforms,
                    "currency": row.get("currency") or "TRY",
                    "raw": row,
                },
                "last_synced_at": now,
                "is_active": True,
            },
        )
        self._upsert_metric(ad, row)
        return ad, created

    def _upsert_metric(self, ad, row):
        metric_date = timezone.now().date()
        impressions = int(_range_average(row.get("impressions") or 0))
        spend = _range_average(row.get("spend") or 0)
        engagement = _engagement_estimate(impressions)
        reach_min = int(Decimal(impressions) * Decimal("0.65")) if impressions else 0
        reach_max = int(Decimal(impressions) * Decimal("0.90")) if impressions else 0
        AdMetricHistory.objects.update_or_create(
            ad=ad,
            date=metric_date,
            defaults={
                "impressions": impressions,
                "reach": reach_max,
                "frequency": Decimal("1.0000"),
                "clicks": 0,
                "spend": _q2(spend),
                "currency": row.get("currency") or "TRY",
                "ctr": Decimal("0"),
                "cpc": Decimal("0"),
                "cpm": _q4(spend / Decimal(impressions) * Decimal("1000")) if impressions else Decimal("0"),
                "engagement": engagement,
                "engagement_rate": _q4(Decimal(engagement) / Decimal(impressions) * Decimal("100")) if impressions else Decimal("0"),
                "estimated_engagement": engagement,
                "estimated_reach_min": reach_min,
                "estimated_reach_max": reach_max,
                "is_competitor_snapshot": True,
                "raw_metrics": {
                    "provider": "meta_ad_library",
                    "impressions_range": row.get("impressions"),
                    "spend_range": row.get("spend"),
                    "demographic_distribution": row.get("demographic_distribution"),
                    "snapshot_date": metric_date.isoformat(),
                },
            },
        )


def sync_competitor_live(competitor: Competitor, limit=None):
    return MetaAdLibraryCompetitorSync(competitor).sync(limit=limit)
