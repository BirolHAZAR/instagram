# core/context_processors.py
"""Tüm template'lere bildirim verilerini ekler"""
import re
from urllib.parse import quote

from django.conf import settings

from core.services.alert_service import AlertService


def alert_notifications(request):
    """Tüm sayfalarda bildirimleri göster"""
    if request.user.is_authenticated:
        try:
            alerts = AlertService.get_alerts(request.user)
            unread = AlertService.get_unread_count(request.user)
            return {
                'global_alerts': alerts,
                'unread_count': unread,
            }
        except Exception as e:
            pass
    
    return {
        'global_alerts': [],
        'unread_count': {'total': 0, 'critical': 0, 'warning': 0, 'info': 0},
    }

def language_labels(request):
    from core.utils.translations import TRANSLATIONS
    current_language = "tr"
    labels = TRANSLATIONS["tr"]

    return {
        "labels": labels,
        "current_language": current_language,
    }


def auth_security_links(request):
    providers = [
        {"id": "google", "label": "Google", "icon": "fab fa-google", "class": "danger"},
        {"id": "facebook", "label": "Facebook", "icon": "fab fa-facebook", "class": "primary"},
        {"id": "instagram", "label": "Instagram", "icon": "fab fa-instagram", "class": "dark"},
        {"id": "tiktok", "label": "TikTok", "icon": "fab fa-tiktok", "class": "secondary"},
        {"id": "linkedin_oauth2", "label": "LinkedIn", "icon": "fab fa-linkedin", "class": "primary"},
        {"id": "twitter_oauth2", "label": "X", "icon": "fab fa-x-twitter", "class": "dark"},
    ]
    configured = set()
    try:
        from allauth.socialaccount.models import SocialApp

        configured = set(
            SocialApp.objects
            .filter(provider__in=[provider["id"] for provider in providers])
            .exclude(client_id="")
            .exclude(secret="")
            .values_list("provider", flat=True)
        )
    except Exception:
        configured = set()

    visible_providers = []
    for provider in providers:
        provider["configured"] = provider["id"] in configured
        provider["login_url"] = f"/accounts/{provider['id']}/login/"
        if provider["configured"]:
            visible_providers.append(provider)

    return {
        "social_login_providers": visible_providers,
        "all_social_login_providers": providers,
    }


def whatsapp_contact(request):
    phone_number = re.sub(r"\D", "", getattr(settings, "WHATSAPP_PHONE_NUMBER", "") or "")
    message = getattr(settings, "WHATSAPP_MESSAGE", "") or ""
    whatsapp_url = ""

    if phone_number:
        whatsapp_url = f"https://wa.me/{phone_number}"
        if message:
            whatsapp_url = f"{whatsapp_url}?text={quote(message)}"

    return {
        "whatsapp_phone_number": phone_number,
        "whatsapp_message": message,
        "whatsapp_url": whatsapp_url,
    }


def agency_client_scope(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"agency_scope": None, "agency_member_identity": None}

    from core.services.agency_scope import get_agency_scope
    from core.models import OrganizationMember

    membership = (
        OrganizationMember.objects
        .select_related("organization", "role_group")
        .filter(user=request.user, is_active=True, organization__is_active=True)
        .exclude(organization__owner=request.user)
        .order_by("id")
        .first()
    )
    return {
        "agency_scope": get_agency_scope(request),
        "agency_member_identity": membership,
    }


