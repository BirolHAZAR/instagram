from celery import shared_task
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime


@shared_task(name="core.tasks.report_tasks.generate_weekly_report")
def generate_weekly_report():
    from core.services.account_lifecycle import active_user_queryset

    active_users = active_user_queryset().count()
    return {"success": True, "report_type": "weekly", "active_users": active_users}


@shared_task(name="core.tasks.report_tasks.generate_weekly_reports_for_all_users")
def generate_weekly_reports_for_all_users():
    return generate_weekly_report.run()


@shared_task(name="core.tasks.report_tasks.dispatch_due_scheduled_reports")
def dispatch_due_scheduled_reports():
    from core.models import ScheduledReport
    from core.services.scheduled_reports import due_reports, next_run_for

    checked = 0
    queued = 0
    for report in due_reports():
        checked += 1
        scheduled_for = report.next_run_at
        claimed_next_run = next_run_for(report)
        claimed = ScheduledReport.objects.filter(
            id=report.id,
            is_active=True,
            next_run_at=scheduled_for,
        ).update(next_run_at=claimed_next_run, updated_at=timezone.now())
        if not claimed:
            continue
        try:
            send_scheduled_report.delay(report.id, scheduled_for.isoformat())
        except Exception:
            ScheduledReport.objects.filter(
                id=report.id,
                next_run_at=claimed_next_run,
            ).update(next_run_at=scheduled_for, updated_at=timezone.now())
            raise
        queued += 1
    return {"success": True, "checked": checked, "queued": queued, "at": timezone.now().isoformat()}


@shared_task(name="core.tasks.report_tasks.send_scheduled_report")
def send_scheduled_report(report_id, scheduled_for_iso=None):
    from core.models import ScheduledReport
    from core.services.scheduled_reports import send_scheduled_report as send_report

    scheduled_for = parse_datetime(scheduled_for_iso) if scheduled_for_iso else None
    try:
        with transaction.atomic():
            report = (
                ScheduledReport.objects.select_for_update()
                .select_related("user")
                .filter(id=report_id, is_active=True)
                .first()
            )
            if not report:
                return {"success": False, "error": "report_not_found_or_inactive", "report_id": report_id}
            if scheduled_for and report.last_sent_at and report.last_sent_at >= scheduled_for:
                return {
                    "success": True,
                    "skipped": True,
                    "reason": "scheduled_run_already_sent",
                    "report_id": report_id,
                }
            result = send_report(report)
            return {"success": True, "report_id": report_id, **result}
    except Exception as exc:
        ScheduledReport.objects.filter(id=report_id).update(last_error=str(exc), updated_at=timezone.now())
        raise
