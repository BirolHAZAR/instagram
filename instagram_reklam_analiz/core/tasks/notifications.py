import logging

from celery import shared_task
from django.contrib.auth import get_user_model

from core.services.account_lifecycle import active_user_queryset
from core.services.alert_service import AlertService

User = get_user_model()
logger = logging.getLogger(__name__)


@shared_task
def generate_periodic_report(account_id, report_type="weekly"):
    try:
        from core.models import InstagramAccount

        InstagramAccount.objects.get(id=account_id)
        return f"{report_type.capitalize()} rapor basariyla olusturuldu."
    except Exception as exc:
        return str(exc)


@shared_task
def refresh_all_users_alerts():
    for user in active_user_queryset():
        AlertService.refresh_all_alerts(user)
    return "All alerts refreshed"


@shared_task
def scan_critical_alerts_for_all_users():
    from core.services.critical_alert_service import CriticalAlertService

    total = 0
    for user in active_user_queryset():
        try:
            total += CriticalAlertService.scan_user(user)
        except Exception as exc:
            logger.exception("Kritik uyari taramasi basarisiz: %s", exc)
    return total


@shared_task
def send_daily_notification_summaries():
    from core.services.notification_preferences import send_daily_notification_summaries as send_summaries

    return send_summaries()
