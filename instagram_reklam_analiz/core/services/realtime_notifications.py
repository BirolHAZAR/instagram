"""WebSocket üzerinden canlı bildirim gönderimi."""

import logging
from asgiref.sync import async_to_sync

logger = logging.getLogger(__name__)


def notification_payload(notification):
    return {
        "id": notification.id,
        "dom_id": f"notification_{notification.id}",
        "title": notification.title,
        "message": notification.message,
        "level": notification.level,
        "icon": notification.icon,
        "link": notification.link or "#",
        "created_at": notification.created_at.isoformat() if notification.created_at else None,
        "is_read": notification.is_read,
    }


def send_realtime_notification(notification):
    try:
        from channels.layers import get_channel_layer
    except Exception:
        return False

    try:
        user = getattr(notification, "user", None)
        if not user:
            return False

        preferences = getattr(user, "notification_preferences", None)
        if preferences and not getattr(preferences, "realtime_enabled", True):
            return False

        channel_layer = get_channel_layer()
        if not channel_layer:
            return False

        async_to_sync(channel_layer.group_send)(
            f"notifications_{user.id}",
            {
                "type": "notification.created",
                "notification": notification_payload(notification),
            },
        )
        return True
    except Exception as exc:
        logger.exception("Canlı bildirim gönderilemedi: %s", exc)
        return False
