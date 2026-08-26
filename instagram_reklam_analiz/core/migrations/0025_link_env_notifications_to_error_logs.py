import uuid

from django.db import migrations
from django.db.models import Q


def link_existing_env_notifications(apps, schema_editor):
    Notification = apps.get_model("core", "Notification")
    SystemErrorLog = apps.get_model("core", "SystemErrorLog")

    notifications = Notification.objects.filter(
        title__startswith="Kritik ENV token hatas",
    ).filter(Q(link__in=["/admin/", ""]) | Q(link__isnull=True))

    grouped = {}
    for notification in notifications.iterator():
        key = (notification.title, notification.message)
        grouped.setdefault(key, []).append(notification.id)

    for (title, message), notification_ids in grouped.items():
        label = title.split(":", 1)[-1].strip() if ":" in title else "ENV_TOKEN"
        error_log = SystemErrorLog.objects.create(
            error_id=f"ENV-LEGACY-{uuid.uuid4().hex[:12].upper()}",
            message=f"{label}: {message}"[:500],
            severity="critical",
            status="new",
            file_name="core/services/platform_token_service.py",
            function_name="_notify_admins_for_env_failure",
            tags={
                "source": "platform_token_health",
                "category": "env_token",
                "token_label": label,
                "migrated_from_notification": True,
            },
            extra_data={"diagnostic_message": str(message)[:500]},
        )
        Notification.objects.filter(id__in=notification_ids).update(
            link=f"/admin/core/systemerrorlog/{error_log.pk}/change/"
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0024_legal_acceptance")]

    operations = [
        migrations.RunPython(link_existing_env_notifications, migrations.RunPython.noop),
    ]
