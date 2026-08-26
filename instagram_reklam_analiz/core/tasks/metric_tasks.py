"""Metric history and performance snapshot tasks."""

from celery import shared_task


@shared_task(name="core.tasks.metric_tasks.record_daily_metrics_for_all_ads")
def record_daily_metrics_for_all_ads():
    from core.tasks.metrics import create_daily_metric_snapshots

    result = create_daily_metric_snapshots.run()
    from core.tasks.admin_ops import dispatch_octo_rule_engine_sweep
    dispatch_octo_rule_engine_sweep.apply_async(
        kwargs={"trigger": "metric_refresh"}, countdown=5, queue="ai"
    )
    return result


@shared_task(name="core.tasks.metric_tasks.refresh_daily_demo_metrics")
def refresh_daily_demo_metrics():
    from core.services.demo_metrics import refresh_demo_metrics_for_date

    result = refresh_demo_metrics_for_date()
    from core.tasks.admin_ops import dispatch_octo_rule_engine_sweep
    dispatch_octo_rule_engine_sweep.apply_async(
        kwargs={"trigger": "metric_refresh"}, countdown=5, queue="ai"
    )
    return result


@shared_task(name="core.tasks.metric_tasks.cleanup_old_metric_history")
def cleanup_old_metric_history(days_to_keep=90):
    from core.tasks.metrics import cleanup_old_metrics

    return cleanup_old_metrics.run(days=days_to_keep)


@shared_task(name="core.tasks.metric_tasks.update_metric_deltas")
def update_metric_deltas():
    return {
        "success": False,
        "skipped": True,
        "reason": "Legacy metric delta task disabled; V2 sync writes metric history directly.",
    }


@shared_task(name="core.tasks.metric_tasks.fill_metric_history")
def fill_metric_history():
    return {
        "success": False,
        "skipped": True,
        "reason": "Legacy fill metric history task disabled; use backfill_metric_histories_from_ads when needed.",
    }
