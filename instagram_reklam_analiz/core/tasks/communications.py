from datetime import timedelta
from email.mime.image import MIMEImage

from celery import shared_task
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Max
from django.template.loader import render_to_string
from django.template import Context, Template
from django.utils import timezone

from core.models import (
    Announcement, AnnouncementDelivery, LifecycleEmailCampaign,
    LifecycleEmailDelivery, Notification, UserSubscription,
)


def _send_message(subject, template, context, recipient):
    context = {**context}
    text = render_to_string(f"emails/{template}.txt", context)
    source = context.get("campaign") or context.get("announcement")
    custom_html = getattr(source, "html_template", "") if source else ""
    html = Template(custom_html).render(Context(context)) if custom_html.strip() else render_to_string(f"emails/{template}.html", context)
    message = EmailMultiAlternatives(subject=subject, body=text, to=[recipient])
    message.attach_alternative(html, "text/html")
    logo_path = settings.BASE_DIR / "static" / "images" / "logo2.png"
    if logo_path.exists():
        logo = MIMEImage(logo_path.read_bytes(), _subtype="png")
        logo.add_header("Content-ID", "<brand-logo>")
        logo.add_header("Content-Disposition", "inline", filename="reklamanaliz-logo.png")
        message.attach(logo)
        message.mixed_subtype = "related"
    return message.send()


@shared_task(name="core.tasks.communications.dispatch_lifecycle_emails")
def dispatch_lifecycle_emails():
    User = get_user_model()
    now = timezone.now()
    paid_user_ids = UserSubscription.objects.exclude(plan__name="trial_14").values_list("user_id", flat=True)
    sent = failed = 0
    for campaign in LifecycleEmailCampaign.objects.filter(is_active=True):
        cutoff = now - timedelta(days=campaign.delay_days)
        users = User.objects.filter(is_active=True, date_joined__lte=cutoff).exclude(id__in=paid_user_ids).exclude(email="")
        for user in users.iterator():
            deliveries = campaign.deliveries.filter(user=user)
            count = deliveries.filter(status="sent").count()
            if count >= campaign.max_sends:
                continue
            last_sent = deliveries.filter(status="sent").aggregate(value=Max("sent_at"))["value"]
            if last_sent and last_sent > now - timedelta(days=campaign.repeat_days):
                continue
            sequence = count + 1
            context = {"user": user, "first_name": user.first_name or user.username, "campaign": campaign}
            try:
                _send_message(campaign.subject, "lifecycle_subscription", context, user.email)
                LifecycleEmailDelivery.objects.create(campaign=campaign, user=user, sequence=sequence, status="sent")
                sent += 1
            except Exception as exc:
                LifecycleEmailDelivery.objects.update_or_create(
                    campaign=campaign, user=user, sequence=sequence,
                    defaults={"status": "failed", "error": str(exc)[:2000], "sent_at": now},
                )
                failed += 1
    return {"sent": sent, "failed": failed}


@shared_task(name="core.tasks.communications.dispatch_announcements")
def dispatch_announcements():
    User = get_user_model()
    now = timezone.now()
    announcements = Announcement.objects.filter(is_active=True, processed_at__isnull=True, publish_at__lte=now)
    delivered = 0
    for announcement in announcements:
        if announcement.expires_at and announcement.expires_at <= now:
            announcement.processed_at = now
            announcement.save(update_fields=["processed_at", "updated_at"])
            continue
        for user in User.objects.filter(is_active=True).iterator():
            delivery, _ = AnnouncementDelivery.objects.get_or_create(announcement=announcement, user=user)
            errors = []
            if announcement.send_in_app and not delivery.notification_created:
                Notification.objects.create(user=user, title=announcement.title, message=announcement.message, level="info", icon="bullhorn", link=announcement.link or None)
                delivery.notification_created = True
            if announcement.send_email and user.email and not delivery.email_sent:
                try:
                    _send_message(announcement.title, "announcement", {"user": user, "announcement": announcement}, user.email)
                    delivery.email_sent = True
                except Exception as exc:
                    errors.append(str(exc))
            delivery.error = "\n".join(errors)[:2000]
            delivery.save(update_fields=["notification_created", "email_sent", "error"])
            delivered += 1
        announcement.processed_at = now
        announcement.save(update_fields=["processed_at", "updated_at"])
    return {"deliveries": delivered}
