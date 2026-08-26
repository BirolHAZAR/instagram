# core/tasks/maintenance_tasks.py
"""Bakım, temizlik ve token yenileme görevleri."""

from celery import shared_task


@shared_task(name="core.tasks.maintenance_tasks.cleanup_old_raw_data")
def cleanup_old_raw_data(days=30):
    from core.tasks.maintenance import cleanup_old_raw_data as legacy_task

    return legacy_task.run(days=days)


@shared_task(name="core.tasks.maintenance_tasks.refresh_expired_tokens")
def refresh_expired_tokens():
    from core.services.platform_token_service import check_and_refresh_platform_tokens

    return check_and_refresh_platform_tokens()


@shared_task(name="core.tasks.maintenance_tasks.cleanup_old_data")
def cleanup_old_data(days=30):
    deleted_raw = cleanup_old_raw_data.run(days=days)
    return {"success": True, "raw_data_deleted": deleted_raw}


@shared_task(name="core.tasks.maintenance_tasks.purge_expired_pending_deletion_accounts")
def purge_expired_pending_deletion_accounts(limit=100):
    from core.services.account_lifecycle import expired_pending_deletion_users, mark_user_deletion_record_deleted

    users = list(expired_pending_deletion_users().order_by("profile__scheduled_deletion_at")[:limit])
    deleted = 0
    user_ids = []

    for user in users:
        user_ids.append(user.id)
        mark_user_deletion_record_deleted(user)
        user.delete()
        deleted += 1

    return {"success": True, "deleted": deleted, "user_ids": user_ids}


@shared_task(name="core.tasks.maintenance_tasks.sync_account_deletion_lifecycle")
def sync_account_deletion_lifecycle(limit=100):
    from core.services.account_lifecycle import mark_due_deletion_records_suspended

    suspended_records = mark_due_deletion_records_suspended()
    purge_result = purge_expired_pending_deletion_accounts.run(limit=limit)
    return {
        "success": True,
        "suspended_records": suspended_records,
        "purge": purge_result,
    }


@shared_task(name="core.tasks.maintenance_tasks.process_due_subscription_renewals")
def process_due_subscription_renewals(limit=100):
    from core.services.subscription_renewal import process_due_auto_renewals

    results = process_due_auto_renewals(limit=limit)
    return {
        "success": True,
        "processed": len(results),
        "renewed": sum(1 for item in results if item.get("success")),
        "results": results,
    }
