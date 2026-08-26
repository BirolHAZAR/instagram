import logging
import json
from datetime import timedelta
from io import StringIO

from celery import shared_task
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError
from django.utils import timezone


logger = logging.getLogger(__name__)
DISABLED_AUTOMATIC_TASKS = {
    "config.celery.debug_task",
}


def _octo_summary(output):
    for line in reversed(output.splitlines()):
        if line.startswith("OCTO_SUMMARY_JSON="):
            return json.loads(line.split("=", 1)[1])
    return {}


@shared_task(bind=True, max_retries=2, name="core.tasks.admin_ops.generate_octo_tasks")
def generate_octo_tasks(
    self,
    user_id=None,
    clear_open=False,
    account_id=None,
    trigger="manual",
    days=7,
):
    from core.models import OctoRuleEngineRun, OctoTaskRule, PlatformAccount

    args = []
    if user_id:
        args += ["--user-id", str(user_id)]
    if account_id:
        args += ["--account-id", str(account_id)]
    if clear_open:
        args.append("--clear-open-tasks")
    args += ["--days", str(max(1, int(days or 7)))]

    # Geriye uyumluluk: kullanıcı verilmeden yapılan yönetici çağrısı tüm üyeleri işler.
    if not user_id:
        output = StringIO()
        call_command("generate_octo_tasks", *args, stdout=output, no_color=True)
        summary = _octo_summary(output.getvalue())
        return {"success": True, "user_id": None, **summary, "finished_at": timezone.now().isoformat()}

    account = None
    if account_id:
        account = PlatformAccount.objects.filter(id=account_id, user_id=user_id).first()
        if account is None:
            return {"success": False, "skipped": True, "reason": "account_user_mismatch"}

    now = timezone.now()
    stale_before = now - timedelta(minutes=40)
    OctoRuleEngineRun.objects.filter(
        user_id=user_id,
        status="running",
        started_at__lt=stale_before,
    ).update(
        status="failed",
        finished_at=now,
        error_message="Çalışan görev zaman aşımına uğradı; güvenlik taraması yeniden kuyruğa alabilir.",
    )

    try:
        run = OctoRuleEngineRun.objects.create(
            user_id=user_id,
            platform_account=account,
            trigger=trigger if trigger in dict(OctoRuleEngineRun.TRIGGER_CHOICES) else "manual",
            status="running",
            celery_task_id=str(getattr(self.request, "id", "") or ""),
            active_rule_count=OctoTaskRule.objects.filter(is_active=True).count(),
        )
    except IntegrityError:
        return {
            "success": True,
            "skipped": True,
            "reason": "already_running",
            "user_id": user_id,
        }

    output = StringIO()
    try:
        call_command("generate_octo_tasks", *args, stdout=output, no_color=True)
        summary = _octo_summary(output.getvalue())
        run.status = "completed"
        run.campaigns_evaluated = summary.get("campaigns_evaluated", 0)
        run.signals_matched = summary.get("signals_matched", 0)
        run.tasks_created = summary.get("tasks_created", 0)
        run.tasks_skipped = summary.get("tasks_skipped", 0)
        run.details = {
            **summary,
            "account_id": account_id,
            "days": days,
            "output_tail": output.getvalue().splitlines()[-12:],
        }
        run.finished_at = timezone.now()
        run.save(update_fields=[
            "status", "campaigns_evaluated", "signals_matched", "tasks_created",
            "tasks_skipped", "details", "finished_at",
        ])
        return {
            "success": True,
            "run_id": run.id,
            "user_id": user_id,
            "account_id": account_id,
            **summary,
            "finished_at": run.finished_at.isoformat(),
        }
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)
        run.details = {"output_tail": output.getvalue().splitlines()[-12:]}
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "details", "finished_at"])
        logger.exception("Octo kural motoru başarısız user=%s account=%s", user_id, account_id)
        raise self.retry(exc=exc, countdown=60)


@shared_task(name="core.tasks.admin_ops.dispatch_octo_rule_engine_sweep")
def dispatch_octo_rule_engine_sweep(trigger="periodic_sweep"):
    User = get_user_model()
    user_ids = list(
        User.objects.filter(
            is_active=True,
            platform_accounts__is_active=True,
            campaigns_v2__isnull=False,
        ).values_list("id", flat=True).distinct()
    )
    queued = []
    for index, user_id in enumerate(user_ids):
        result = generate_octo_tasks.apply_async(
            kwargs={"user_id": user_id, "trigger": trigger, "days": 7},
            countdown=index % 20,
            queue="ai",
        )
        queued.append({"user_id": user_id, "task_id": result.id})
    return {"success": True, "queued_count": len(queued), "queued": queued}


@shared_task(name="core.tasks.admin_ops.refresh_due_marketplace_researches")
def refresh_due_marketplace_researches(limit=100):
    from core.tasks.marketplace_sync import refresh_tracked_marketplace_researches

    return refresh_tracked_marketplace_researches.run(limit=limit)


@shared_task(name="core.tasks.admin_ops.refresh_expired_tokens")
def refresh_expired_tokens():
    from core.tasks.maintenance_tasks import refresh_expired_tokens as refresh_task

    return refresh_task.run()


@shared_task(name="core.tasks.admin_ops.sync_openai_usage")
def sync_openai_usage():
    output = StringIO()
    call_command("sync_openai_usage", stdout=output, no_color=True)
    for line in output.getvalue().splitlines():
        if line.strip():
            logger.info(line)
    return {
        "success": True,
        "finished_at": timezone.now().isoformat(),
    }


@shared_task(name="core.tasks.admin_ops.dispatch_admin_managed_schedules")
def dispatch_admin_managed_schedules():
    from config.celery import app
    from core.models import AdminManagedCelerySchedule

    now = timezone.now()
    dispatched = []
    for schedule in AdminManagedCelerySchedule.objects.filter(is_active=True).order_by("name"):
        if schedule.task_name in DISABLED_AUTOMATIC_TASKS:
            schedule.is_active = False
            schedule.last_error = "Debug task otomatik zamanlamadan devre disi birakildi."
            schedule.save(update_fields=["is_active", "last_error", "updated_at"])
            dispatched.append({"name": schedule.name, "task": schedule.task_name, "disabled": True})
            continue
        if not schedule.is_due(now=now):
            continue
        try:
            async_result = app.send_task(
                schedule.task_name,
                args=schedule.args or [],
                kwargs=schedule.kwargs or {},
            )
            schedule.last_run_at = now
            schedule.last_task_id = async_result.id
            schedule.last_error = ""
            schedule.save(update_fields=["last_run_at", "last_task_id", "last_error", "updated_at"])
            dispatched.append({"name": schedule.name, "task": schedule.task_name, "task_id": async_result.id})
        except Exception as exc:
            schedule.last_error = str(exc)
            schedule.save(update_fields=["last_error", "updated_at"])
            dispatched.append({"name": schedule.name, "task": schedule.task_name, "error": str(exc)})
    return {"dispatched": dispatched, "count": len(dispatched)}
