import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from core.models import ContactMessage, DemoRequest
from core.services.notification_events import notify_user

logger = logging.getLogger(__name__)


def _admin_users():
    User = get_user_model()
    return User.objects.filter(is_active=True, is_staff=True).order_by("id")


def _notify_admins(title, message, link, level="info"):
    for user in _admin_users():
        notify_user(
            user=user,
            title=title,
            message=message,
            level=level,
            icon="📩",
            link=link,
        )


def _send_html_mail(*, subject, text_template, html_template, context, from_email, to_email, reply_to=None):
    recipients = [item.strip() for item in str(to_email or "").split(",") if item.strip()]
    if not recipients:
        return 0
    text_body = render_to_string(text_template, context)
    html_body = render_to_string(html_template, context)
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email,
        to=recipients,
        reply_to=[reply_to] if reply_to else None,
    )
    message.attach_alternative(html_body, "text/html")
    try:
        return message.send(fail_silently=False)
    except Exception as exc:
        logger.exception("Lead maili gonderilemedi: %s", exc)
        return 0


def create_contact_message(*, name, email, subject, message):
    contact = ContactMessage.objects.create(
        name=name,
        email=email,
        subject=subject,
        message=message,
    )
    context = {"contact": contact}
    sent = _send_html_mail(
        subject=f"Yeni iletisim mesaji: {subject}",
        text_template="emails/contact_message.txt",
        html_template="emails/contact_message.html",
        context=context,
        from_email=getattr(settings, "CONTACT_FROM_EMAIL", settings.DEFAULT_FROM_EMAIL),
        to_email=getattr(settings, "CONTACT_TO_EMAIL", settings.DEFAULT_FROM_EMAIL),
        reply_to=email,
    )
    _notify_admins(
        title="Yeni iletişim mesajı",
        message=f"{name} iletişim formundan mesaj gönderdi: {subject}",
        link="/admin/core/contactmessage/",
        level="info",
    )
    return contact, sent


def create_demo_request(*, name, email, phone, company, role="", ad_spend="", platforms=None, goal="", message=""):
    demo = DemoRequest.objects.create(
        name=name,
        email=email,
        phone=phone,
        company=company,
        role=role,
        ad_spend=ad_spend,
        platforms=platforms or [],
        goal=goal,
        message=message,
    )
    context = {"demo": demo}
    sent = _send_html_mail(
        subject=f"Yeni demo talebi: {company}",
        text_template="emails/demo_request.txt",
        html_template="emails/demo_request.html",
        context=context,
        from_email=getattr(settings, "DEMO_REQUEST_FROM_EMAIL", settings.DEFAULT_FROM_EMAIL),
        to_email=getattr(settings, "DEMO_REQUEST_TO_EMAIL", settings.DEFAULT_FROM_EMAIL),
        reply_to=email,
    )
    _notify_admins(
        title="Yeni demo talebi",
        message=f"{company} için {name} demo talebi oluşturdu.",
        link="/admin/core/demorequest/",
        level="success",
    )
    return demo, sent
import logging
