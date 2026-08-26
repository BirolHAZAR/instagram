# core/tasks/sync_tasks.py
"""Platform senkronizasyon görevleri.

Bu dosya, reklam hesaplarından veri çekme ve senkronizasyon işlerinin
ana giriş noktasıdır. Eski v2 task fonksiyonlarını bozmadan profesyonel
tek isimlendirme sağlar.
"""

from celery import shared_task


@shared_task(bind=True, max_retries=3, default_retry_delay=300, name="core.tasks.sync_tasks.sync_platform_account_ads")
def sync_platform_account_ads(self, account_id, source_type="OWN"):
    from core.tasks.v2_platform_sync import sync_v2_platform_account_ads

    return sync_v2_platform_account_ads.run(account_id, source_type)


@shared_task(name="core.tasks.sync_tasks.sync_all_platform_accounts")
def sync_all_platform_accounts():
    from core.tasks.v2_platform_sync import sync_all_v2_platform_accounts

    return sync_all_v2_platform_accounts.run()


@shared_task(name="core.tasks.sync_tasks.sync_meta_accounts")
def sync_meta_accounts():
    from core.models import PlatformAccount
    from core.tasks.v2_platform_sync import (
        _should_skip_ad_sync,
        _skip_result,
        sync_v2_platform_account_ads,
    )

    results = []
    for account in PlatformAccount.objects.filter(
        is_active=True,
        platform__code__in=["facebook", "instagram"],
    ).select_related("connection"):
        skip_reason = _should_skip_ad_sync(account, account.platform.code)
        if skip_reason:
            results.append(_skip_result(account, account.platform.code, "OWN", skip_reason))
            continue
        async_result = sync_v2_platform_account_ads.delay(account.id, "OWN")
        results.append({"account_id": account.id, "platform": account.platform.code, "task_id": async_result.id})
    return results


@shared_task(name="core.tasks.sync_tasks.sync_google_ads")
def sync_google_ads():
    from core.models import PlatformAccount
    from core.tasks.v2_platform_sync import sync_v2_platform_account_ads

    results = []
    for account in PlatformAccount.objects.filter(is_active=True, platform__code="google_ads"):
        async_result = sync_v2_platform_account_ads.delay(account.id, "OWN")
        results.append({"account_id": account.id, "task_id": async_result.id})
    return results


@shared_task(name="core.tasks.sync_tasks.sync_tiktok")
def sync_tiktok():
    from core.models import PlatformAccount
    from core.tasks.v2_platform_sync import sync_v2_platform_account_ads

    results = []
    for account in PlatformAccount.objects.filter(is_active=True, platform__code="tiktok"):
        async_result = sync_v2_platform_account_ads.delay(account.id, "OWN")
        results.append({"account_id": account.id, "task_id": async_result.id})
    return results


@shared_task(name="core.tasks.sync_tasks.sync_organic_account")
def sync_organic_account(account_id):
    from core.models import PlatformAccount
    from core.services.organic_content_service import sync_instagram_organic_content
    from core.services.sync_policy import policy_for_user

    account = PlatformAccount.objects.select_related("platform", "connection", "user").filter(
        id=account_id, is_active=True, platform__code="instagram"
    ).first()
    if not account:
        return {"success": False, "skipped": True, "reason": "account_not_found"}
    policy = policy_for_user(account.user)
    if not policy:
        return {"success": False, "skipped": True, "reason": "active_subscription_required"}
    return sync_instagram_organic_content(account, limit=policy.max_records)


@shared_task(name="core.tasks.sync_tasks.sync_due_organic_accounts")
def sync_due_organic_accounts():
    from core.models import PlatformAccount
    from core.services.sync_policy import acquire_sync_lock, is_sync_due

    queued = []
    accounts = PlatformAccount.objects.filter(is_active=True, platform__code="instagram").select_related("user")
    for account in accounts:
        last_sync = (account.extra_data or {}).get("organic_last_sync_at")
        if not is_sync_due(account.user, last_sync, kind="organic"):
            continue
        _lock_key, acquired = acquire_sync_lock("organic-dispatch", account.id, timeout=1800)
        if not acquired:
            continue
        result = sync_organic_account.delay(account.id)
        queued.append({"account_id": account.id, "task_id": result.id})
    return {"queued": len(queued), "items": queued}
