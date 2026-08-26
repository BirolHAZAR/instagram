import logging
from datetime import timedelta

from django.utils import timezone
from core.services.activity_service import record_activity_from_notification
from core.services.notification_preferences import is_in_app_allowed

logger = logging.getLogger(__name__)


def notify_user(*, user, title, message, level="info", icon="🔔", link=None, dedupe_key=None):
    """Merkezi bildirim oluşturucu.

    Aynı user + aynı başlık + aynı mesaj birkaç saniye içinde tekrar üretilirse
    yeni kayıt oluşturmaz. Bu, signal + manuel çağrı çakışmalarından doğan çift
    bildirimleri DB seviyesinde keser.
    """
    if not user:
        return None
    if not is_in_app_allowed(user, title, level):
        return None

    try:
        from core.models import Notification

        recent_since = timezone.now() - timedelta(seconds=15)
        existing = Notification.objects.filter(
            user=user,
            title=title,
            message=message,
            created_at__gte=recent_since,
        ).order_by("-id").first()
        if existing:
            return existing

        fields = {f.name for f in Notification._meta.fields}
        kwargs = {"user": user, "title": title, "message": message}
        if "level" in fields:
            kwargs["level"] = level
        if "icon" in fields:
            kwargs["icon"] = icon
        if "link" in fields:
            kwargs["link"] = link
        if "dedupe_key" in fields and dedupe_key:
            kwargs["dedupe_key"] = dedupe_key

        notification = Notification.objects.create(**kwargs)
        record_activity_from_notification(notification)
        return notification
    except Exception as exc:
        logger.exception("Bildirim oluşturulamadı: %s", exc)
        return None
