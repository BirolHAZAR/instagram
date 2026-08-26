from __future__ import annotations

from django.db.models import Avg, Max, Q, Sum
from django.utils import timezone

from core.models import Influencer, InfluencerMetricHistory
from core.services.cache_service import CacheService


CACHE_NAMESPACE = "influencer_discovery"


def influencer_cache_version(user_id: int) -> int:
    return CacheService.get_version(CACHE_NAMESPACE, user_id)


def invalidate_influencer_cache(user_id: int | None = None) -> None:
    CacheService.bump_version(CACHE_NAMESPACE, "global")
    if user_id:
        CacheService.bump_version(CACHE_NAMESPACE, user_id)


def influencer_queryset(filters: dict):
    qs = Influencer.objects.select_related("platform", "created_by").filter(is_active=True)
    query = (filters.get("q") or "").strip()
    platform = (filters.get("platform") or "").strip()
    category = (filters.get("category") or "").strip()
    country = (filters.get("country") or "").strip()
    min_followers = filters.get("min_followers")
    min_engagement = filters.get("min_engagement")

    if query:
        qs = qs.filter(
            Q(display_name__icontains=query)
            | Q(handle__icontains=query)
            | Q(notes__icontains=query)
        )
    if platform:
        qs = qs.filter(platform_id=platform)
    if category:
        qs = qs.filter(category=category)
    if country:
        qs = qs.filter(country__icontains=country)
    if min_followers:
        qs = qs.filter(follower_count__gte=min_followers)
    if min_engagement:
        qs = qs.filter(engagement_rate__gte=min_engagement)

    return qs.order_by("-follower_count", "-engagement_rate", "display_name")


def influencer_stats(qs):
    aggregate = qs.aggregate(
        total_followers=Sum("follower_count"),
        avg_engagement=Avg("engagement_rate"),
        max_followers=Max("follower_count"),
    )
    return {
        "total": qs.count(),
        "total_followers": aggregate.get("total_followers") or 0,
        "avg_engagement": aggregate.get("avg_engagement") or 0,
        "max_followers": aggregate.get("max_followers") or 0,
    }


def snapshot_influencer_metrics(influencer: Influencer, *, date=None) -> InfluencerMetricHistory:
    date = date or timezone.localdate()
    history, _created = InfluencerMetricHistory.objects.update_or_create(
        influencer=influencer,
        date=date,
        defaults={
            "follower_count": influencer.follower_count,
            "following_count": influencer.following_count,
            "post_count": influencer.post_count,
            "avg_likes": influencer.avg_likes,
            "avg_comments": influencer.avg_comments,
            "avg_views": influencer.avg_views,
            "engagement_rate": influencer.engagement_rate,
            "estimated_reach": influencer.estimated_reach,
            "raw_metrics": {"source": influencer.source},
        },
    )
    return history
