from celery import shared_task

from core.models import Competitor
from core.services.cache_service import CacheService
from core.services.competitor_live_sync import CompetitorSyncError, SUPPORTED_META_PLATFORMS, sync_competitor_live


@shared_task(name="core.tasks.competitor_sync.sync_competitor_live_ads")
def sync_competitor_live_ads(competitor_id):
    from core.services.sync_policy import policy_for_user
    competitor = (
        Competitor.objects
        .select_related("platform", "platform_account", "platform_account__connection")
        .filter(id=competitor_id, is_active=True)
        .first()
    )
    if not competitor:
        return {"success": False, "skipped": True, "reason": "competitor_not_found_or_inactive", "competitor_id": competitor_id}
    try:
        policy = policy_for_user(competitor.user)
        if not policy:
            return {"success": False, "skipped": True, "reason": "active_subscription_required", "competitor_id": competitor.id}
        result = sync_competitor_live(competitor, limit=policy.max_records)
    except CompetitorSyncError as exc:
        return {
            "success": False,
            "skipped": True,
            "reason": str(exc),
            "competitor_id": competitor.id,
            "platform": competitor.platform.code if competitor.platform else "unknown",
        }
    CacheService.bump_version("competitors", competitor.user_id)
    CacheService.bump_version("competitor_ads", competitor.user_id, competitor.id)
    CacheService.bump_version("competitor_movements", competitor.user_id)
    CacheService.bump_version("competitor_intelligence", competitor.user_id)
    return {"success": True, "competitor_id": competitor.id, **result}


@shared_task(name="core.tasks.competitor_sync.sync_all_live_competitors")
def sync_all_live_competitors():
    from core.services.sync_policy import acquire_sync_lock, is_sync_due
    competitors = (
        Competitor.objects
        .select_related("platform")
        .filter(is_active=True, platform__code__in=SUPPORTED_META_PLATFORMS)
        .order_by("id")
    )
    results = []
    for competitor in competitors:
        last_sync = (competitor.raw_data or {}).get("last_live_sync_at")
        if not is_sync_due(competitor.user, last_sync, kind="competitor"):
            continue
        _lock_key, acquired = acquire_sync_lock("competitor-dispatch", competitor.id, timeout=1800)
        if not acquired:
            continue
        async_result = sync_competitor_live_ads.delay(competitor.id)
        results.append({
            "competitor_id": competitor.id,
            "platform": competitor.platform.code if competitor.platform else "unknown",
            "task_id": async_result.id,
        })
    return {"queued": len(results), "items": results}
