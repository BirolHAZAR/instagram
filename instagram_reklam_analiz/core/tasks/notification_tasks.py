# core/tasks/notification_tasks.py
"""Bildirim, uyarı ve gerçek zamanlı haber verme görevleri."""

from celery import shared_task


@shared_task(name="core.tasks.notification_tasks.scan_critical_alerts_for_all_users")
def scan_critical_alerts_for_all_users():
    from core.tasks.notifications import scan_critical_alerts_for_all_users as legacy_task

    return legacy_task.run()


@shared_task(name="core.tasks.notification_tasks.refresh_all_users_alerts")
def refresh_all_users_alerts():
    from core.tasks.notifications import refresh_all_users_alerts as legacy_task

    return legacy_task.run()


@shared_task(name="core.tasks.notification_tasks.generate_periodic_report")
def generate_periodic_report(account_id, report_type="weekly"):
    from core.tasks.notifications import generate_periodic_report as legacy_task

    return legacy_task.run(account_id, report_type)


@shared_task(name="core.tasks.notification_tasks.send_daily_notification_summaries")
def send_daily_notification_summaries():
    from core.tasks.notifications import send_daily_notification_summaries as legacy_task

    return legacy_task.run()
