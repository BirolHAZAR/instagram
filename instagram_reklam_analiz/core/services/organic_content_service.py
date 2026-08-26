from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Max, Sum
from django.utils import timezone

from core.instagram_api import InstagramAPI
from core.models import PlatformAccount, SocialPost, SocialPostMetricHistory
from core.services.organic_publish import can_publish_post


READY_PLATFORM_CODES = {"instagram"}



def post_status(post: SocialPost) -> str:
    raw_status = (post.raw_data or {}).get("status")
    if raw_status:
        return str(raw_status)
    if post.posted_at:
        return "published"
    return "draft"


def post_status_label(status: str, labels: dict | None = None) -> str:
    labels = labels or {}
    return {
        "draft": labels.get("draft", "Taslak"),
        "scheduled": labels.get("status_scheduled", "Yayin kuyrugunda"),
        "published": labels.get("status_published", "Platforma gonderildi"),
        "synced": labels.get("status_synced", "Yayinda / senkronize"),
        "failed": labels.get("status_failed", "Yayin hatasi"),
    }.get(status, labels.get("draft", "Taslak"))


def post_status_class(status: str) -> str:
    return {
        "draft": "draft",
        "scheduled": "queued",
        "published": "published",
        "synced": "published",
        "failed": "failed",
    }.get(status, "draft")


def post_status_note(post: SocialPost, status: str, labels: dict | None = None) -> str:
    labels = labels or {}
    raw = post.raw_data or {}
    if status in {"published", "synced"}:
        sent_at = raw.get("published_at")
        return (
            labels.get("status_note_published_at", "Icerik platforma gonderildi ve performans takibine alindi.")
            if sent_at
            else labels.get("status_note_live", "Icerik yayinda olarak takip ediliyor.")
        )
    if status == "scheduled":
        scheduled_at = raw.get("scheduled_at")
        if scheduled_at:
            return f"{labels.get('status_note_scheduled_prefix', 'Planlanan yayin zamani')}: {scheduled_at}"
        return labels.get("status_note_scheduled", "Icerik yayin kuyrugunda bekliyor.")
    if status == "failed":
        return raw.get("error_message") or labels.get(
            "status_note_failed",
            "Platform yayini tamamlanamadi; baglanti ve izinleri kontrol et.",
        )
    if raw.get("source") == "creative_studio":
        return labels.get(
            "status_note_creative",
            "Creative Studio'dan aktarildi; yayin icin hesap ve izin durumu hazir olmali.",
        )
    return labels.get("status_note_draft", "Yayinlanmamis taslak.")


def is_publish_ready(post: SocialPost) -> bool:
    ready, _ = can_publish_post(post)
    return ready


def decorate_posts(posts, *, labels: dict | None = None):
    for post in posts:
        status = post_status(post)
        post.organic_status = status
        post.organic_status_label = post_status_label(status, labels)
        post.organic_status_class = post_status_class(status)
        post.organic_status_note = post_status_note(post, status, labels)
        post.organic_publish_ready = is_publish_ready(post)
        _, publish_block_reason = can_publish_post(post)
        post.organic_publish_block_reason = publish_block_reason
        post.organic_scheduled_at = (post.raw_data or {}).get("scheduled_at")
    return posts



def organic_summary_for_user(user, *, start_date=None, end_date=None, days: int = 30, platform_accounts=None) -> dict:
    today = timezone.localdate()
    if end_date is None:
        end_date = today
    if start_date is None:
        start_date = end_date - timedelta(days=days)

    if platform_accounts is None:
        posts = SocialPost.objects.filter(user=user)
        metrics = SocialPostMetricHistory.objects.filter(social_post__user=user)
    else:
        posts = SocialPost.objects.filter(platform_account__in=platform_accounts)
        metrics = SocialPostMetricHistory.objects.filter(social_post__platform_account__in=platform_accounts)
    metrics = metrics.filter(date__gte=start_date, date__lte=end_date)
    totals = metrics.aggregate(
        impressions=Sum("impressions"),
        reach=Sum("reach"),
        engagement=Sum("engagement"),
        likes=Sum("likes"),
        comments=Sum("comments"),
        shares=Sum("shares"),
        saves=Sum("saves"),
        video_views=Sum("video_views"),
        profile_visits=Sum("profile_visits"),
        website_clicks=Sum("website_clicks"),
        avg_engagement_rate=Avg("engagement_rate"),
        latest_date=Max("date"),
    )
    status_counts = {"draft": 0, "scheduled": 0, "published": 0, "synced": 0}
    for status in posts.values_list("raw_data__status", flat=True):
        key = status or "draft"
        status_counts[key] = status_counts.get(key, 0) + 1

    published_count = posts.filter(posted_at__isnull=False).count()
    total_posts = posts.count()
    engagement = totals.get("engagement") or 0
    reach = totals.get("reach") or 0

    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_posts": total_posts,
        "active_posts": posts.filter(is_active=True).count(),
        "draft_posts": status_counts.get("draft", 0),
        "scheduled_posts": status_counts.get("scheduled", 0),
        "published_posts": published_count,
        "synced_posts": status_counts.get("synced", 0),
        "impressions": totals.get("impressions") or 0,
        "reach": reach,
        "engagement": engagement,
        "likes": totals.get("likes") or 0,
        "comments": totals.get("comments") or 0,
        "shares": totals.get("shares") or 0,
        "saves": totals.get("saves") or 0,
        "video_views": totals.get("video_views") or 0,
        "profile_visits": totals.get("profile_visits") or 0,
        "website_clicks": totals.get("website_clicks") or 0,
        "avg_engagement_rate": round(totals.get("avg_engagement_rate") or 0, 2),
        "latest_date": totals.get("latest_date"),
        "engagement_per_post": round(engagement / total_posts, 2) if total_posts else 0,
        "reach_per_post": round(reach / published_count, 2) if published_count else 0,
    }


def organic_type_breakdown(user, *, limit: int = 6):
    return (
        SocialPost.objects.filter(user=user)
        .values("post_type")
        .annotate(total=Count("id"))
        .order_by("-total")[:limit]
    )


def _parse_instagram_timestamp(value):
    if not value:
        return None
    try:
        parsed = timezone.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed)
    return parsed


def _post_type_from_media(media):
    media_type = str((media or {}).get("media_type") or "").upper()
    if media_type == "VIDEO":
        return "VIDEO"
    if media_type == "CAROUSEL_ALBUM":
        return "CAROUSEL"
    if media_type == "IMAGE":
        return "IMAGE"
    return "UNKNOWN"


def sync_instagram_organic_content(account: PlatformAccount, *, limit: int = 50) -> dict:
    if not account or getattr(account.platform, "code", "") != "instagram":
        return {"success": False, "created": 0, "updated": 0, "metrics": 0, "error": "Instagram hesabi bulunamadi."}

    token = getattr(account, "access_token", "") or getattr(getattr(account, "connection", None), "access_token", "") or ""
    instagram_business_id = (account.extra_data or {}).get("instagram_business_account_id") or account.account_id
    if not token or not instagram_business_id:
        return {"success": False, "created": 0, "updated": 0, "metrics": 0, "error": "Instagram token veya business id eksik."}

    api = InstagramAPI(access_token=token)
    response = api._request(
        f"{api.graph_url}/{instagram_business_id}/media",
        {
            "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count",
            "limit": int(limit or 50),
        },
    )
    if isinstance(response, dict) and response.get("error"):
        return {"success": False, "created": 0, "updated": 0, "metrics": 0, "error": response.get("error")}

    created = 0
    updated = 0
    metrics = 0
    now = timezone.now()
    for media in (response or {}).get("data", []):
        media_id = str(media.get("id") or "").strip()
        if not media_id:
            continue
        media_type = _post_type_from_media(media)
        media_url = media.get("media_url") or ""
        thumbnail_url = media.get("thumbnail_url") or media_url
        posted_at = _parse_instagram_timestamp(media.get("timestamp"))

        post, was_created = SocialPost.objects.update_or_create(
            user=account.user,
            platform_account=account,
            platform_post_id=media_id,
            defaults={
                "platform_connection": account.connection,
                "post_type": media_type,
                "caption": media.get("caption") or "",
                "permalink": media.get("permalink") or None,
                "image_url": media_url if media_type in {"IMAGE", "CAROUSEL", "UNKNOWN"} else None,
                "video_url": media_url if media_type == "VIDEO" else None,
                "thumbnail_url": thumbnail_url or None,
                "posted_at": posted_at,
                "raw_data": {
                    "status": "synced",
                    "source": "instagram_media_sync",
                    "instagram_business_account_id": instagram_business_id,
                    "raw": media,
                },
                "last_synced_at": now,
                "is_active": True,
            },
        )
        if was_created:
            created += 1
        else:
            updated += 1

        # Metrik geçmişi paylaşım tarihini değil snapshot tarihini tutar. Böylece
        # eski bir gönderinin bugün güncellenen beğenisi seçili dönemde görünür.
        metric_date = now.date()
        likes = int(media.get("like_count") or 0)
        comments = int(media.get("comments_count") or 0)
        engagement = likes + comments
        SocialPostMetricHistory.objects.update_or_create(
            social_post=post,
            date=metric_date,
            defaults={
                "likes": likes,
                "comments": comments,
                "engagement": engagement,
                "engagement_rate": Decimal("0"),
                "raw_metrics": {
                    "provider": "instagram_graph",
                    "like_count": likes,
                    "comments_count": comments,
                    "synced_at": now.isoformat(),
                },
            },
        )
        metrics += 1

    account.last_sync = now
    account.extra_data = {**(account.extra_data or {}), "organic_last_sync_at": now.isoformat()}
    account.save(update_fields=["last_sync", "extra_data", "updated_at"])
    return {"success": True, "created": created, "updated": updated, "metrics": metrics, "fetched": created + updated}

