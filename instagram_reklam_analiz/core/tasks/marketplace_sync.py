from celery import shared_task

from core.services.marketplace_sync import run_marketplace_sync
from core.services.marketplace_research import refresh_due_tracked_researches


@shared_task(
    bind=True,
    max_retries=1,
    default_retry_delay=120,
    name="core.tasks.marketplace_sync.run_product_research_agent",
)
def run_product_research_agent(self, research_id):
    from django.utils import timezone
    from core.models import MarketplaceProductResearch
    from core.services.marketplace_research import mark_research_failed
    from core.services.shopping_agent import run_shopping_agent

    research = MarketplaceProductResearch.objects.select_related(
        "user", "organization", "subscription", "product"
    ).filter(id=research_id).first()
    if not research:
        return {"completed": False, "reason": "not_found", "research_id": research_id}
    try:
        run_shopping_agent(research)
    except Exception as exc:
        from core.models import FeatureUsageLedger
        from core.services.usage_metering import record_usage_failure

        usage_ledger_id = (research.raw_result or {}).get("usage_ledger_id")
        usage_ledger = FeatureUsageLedger.objects.filter(id=usage_ledger_id).first() if usage_ledger_id else None
        if usage_ledger:
            record_usage_failure(
                user=research.user,
                organization=research.organization,
                subscription=research.subscription,
                operation=FeatureUsageLedger.OP_MARKETPLACE_PRODUCT_RESEARCH,
                reference=f"marketplace.product_research:{research.id}",
                note=str(exc),
                usage_ledger=usage_ledger,
            )
        mark_research_failed(research, exc)
        research.progress_percent = 100
        research.current_step = "Araştırma tamamlanamadı"
        research.finished_at = timezone.now()
        research.save(update_fields=["progress_percent", "current_step", "finished_at", "updated_at"])
        raise
    return {"completed": True, "research_id": research.id, "status": research.status}


@shared_task(bind=True, max_retries=3, default_retry_delay=300, name="core.tasks.marketplace_sync.sync_marketplace_account")
def sync_marketplace_account(self, sync_run_id):
    return run_marketplace_sync(sync_run_id)


@shared_task(name="core.tasks.marketplace_sync.refresh_tracked_marketplace_researches")
def refresh_tracked_marketplace_researches(limit=50):
    return {"refreshed": refresh_due_tracked_researches(limit=limit)}


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    name="core.tasks.marketplace_sync.refresh_single_tracked_research",
)
def refresh_single_tracked_research(self, research_id):
    from core.models import MarketplaceProductResearch
    from core.services.marketplace_research import refresh_tracked_research

    research = MarketplaceProductResearch.objects.select_related(
        "user", "organization", "subscription", "product"
    ).filter(
        id=research_id,
        track_price=True,
        status__in=[
            MarketplaceProductResearch.STATUS_COMPLETED,
            MarketplaceProductResearch.STATUS_PARTIAL,
        ],
    ).first()
    if not research:
        return {"refreshed": False, "reason": "not_found_or_not_tracked", "research_id": research_id}
    refresh_tracked_research(research)
    research.refresh_from_db(fields=["status", "last_tracked_at", "next_tracking_at", "recommended_price"])
    return {
        "refreshed": True,
        "research_id": research.id,
        "status": research.status,
        "recommended_price": str(research.recommended_price),
        "last_tracked_at": research.last_tracked_at.isoformat() if research.last_tracked_at else None,
        "next_tracking_at": research.next_tracking_at.isoformat() if research.next_tracking_at else None,
    }


@shared_task(name="core.tasks.marketplace_sync.sync_due_marketplace_accounts")
def sync_due_marketplace_accounts():
    from core.models import MarketplaceAccount, MarketplaceSyncRun
    from core.services.agency_permission_matrix import get_user_entitlement_plan
    from core.services.sync_policy import acquire_sync_lock, is_sync_due, policy_for_user

    queued = []
    accounts = MarketplaceAccount.objects.filter(is_active=True).select_related("user", "marketplace")
    for account in accounts:
        plan = get_user_entitlement_plan(account.user)
        if not plan or (plan.name != "trial_14" and int(plan.marketplace_product_research_per_month or 0) <= 0):
            continue
        if not is_sync_due(account.user, account.last_sync_at, kind="marketplace"):
            continue
        _lock_key, acquired = acquire_sync_lock("marketplace-dispatch", account.id, timeout=1800)
        if not acquired:
            continue
        run = MarketplaceSyncRun.objects.create(
            marketplace_account=account,
            sync_type=MarketplaceSyncRun.SYNC_TYPE_PRICE_STOCK,
            status=MarketplaceSyncRun.STATUS_QUEUED,
            product_limit=min(account.sync_product_limit, policy_for_user(account.user).max_records),
            filters={"trigger": "plan_schedule", "plan": plan.name},
        )
        result = sync_marketplace_account.delay(run.id)
        queued.append({"account_id": account.id, "sync_run_id": run.id, "task_id": result.id})
    return {"queued": len(queued), "items": queued}
