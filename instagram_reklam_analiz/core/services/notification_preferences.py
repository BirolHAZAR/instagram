from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils import timezone

from core.models.notification_settings import NotificationPreference


logger = logging.getLogger(__name__)


def get_preferences(user):
    if not user:
        return None
    preferences, _created = NotificationPreference.objects.get_or_create(user=user)
    return preferences


def category_from_title(title, level="info"):
    title_lower = (title or "").lower()
    if level == "critical":
        return "critical"
    if "rakip" in title_lower or "competitor" in title_lower:
        return "competitor"
    if "ai" in title_lower or "octo" in title_lower:
        return "ai"
    if "kampanya" in title_lower or "campaign" in title_lower:
        return "campaign"
    if "optimizasyon" in title_lower or "bütçe" in title_lower or "butce" in title_lower or "budget" in title_lower:
        return "optimization"
    return "system"


def is_in_app_allowed(user, title, level="info"):
    prefs = get_preferences(user)
    if not prefs:
        return True
    if not prefs.in_app_enabled:
        return False

    category = category_from_title(title, level)
    checks = {
        "critical": prefs.critical_notifications,
        "competitor": prefs.competitor_notifications,
        "ai": prefs.ai_notifications,
        "campaign": prefs.campaign_notifications,
        "optimization": prefs.optimization_notifications,
        "system": prefs.system_notifications,
    }
    return checks.get(category, True)


def send_notification_email(notification):
    user = getattr(notification, "user", None)
    if not user or not getattr(user, "email", None):
        return False

    prefs = get_preferences(user)
    if not prefs or not prefs.email_enabled:
        return False

    subject = f"ReklamAnaliz.net - {notification.title}"
    message = (
        f"{notification.title}\n\n"
        f"{notification.message}\n\n"
        f"Bildirim merkezi: {getattr(settings, 'SITE_URL', '').rstrip('/')}/bildirimler/"
    )
    try:
        return bool(send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        ))
    except Exception as exc:
        logger.exception("Bildirim e-postasi gonderilemedi: %s", exc)
        return False


def send_daily_notification_summaries():
    from core.models import Notification
    from core.services.account_lifecycle import active_user_queryset

    since = timezone.now() - timedelta(days=1)
    sent = 0

    users = active_user_queryset().filter(
        email__isnull=False,
        notification_preferences__daily_summary_enabled=True,
    ).exclude(email="")

    for user in users:
        notifications = list(
            Notification.objects
            .filter(user=user, created_at__gte=since)
            .order_by("-created_at")[:20]
        )
        if not notifications:
            continue

        unread_count = sum(1 for item in notifications if not item.is_read)
        lines = [
            "Son 24 saatteki bildirim ozeti:",
            "",
            f"Toplam bildirim: {len(notifications)}",
            f"Okunmamis bildirim: {unread_count}",
            "",
        ]
        for item in notifications:
            lines.append(f"- [{item.level}] {item.title}: {item.message[:180]}")

        try:
            sent += int(bool(send_mail(
                subject="ReklamAnaliz.net - Gunluk bildirim ozeti",
                message="\n".join(lines),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,
            )))
        except Exception as exc:
            logger.exception("Gunluk bildirim ozeti gonderilemedi: %s", exc)

    return sent
