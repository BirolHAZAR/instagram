import logging

from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)


ACTION_KEYWORDS = (
    ("competitor", ("rakip", "competitor")),
    ("campaign", ("kampanya", "campaign")),
    ("ad", ("reklam", "ad ")),
    ("ai", ("ai", "octo", "analiz")),
    ("optimization", ("optimizasyon", "bütçe", "butce", "budget")),
    ("account", ("hesap", "platform", "senkron", "sync", "bağlandı", "baglandi")),
    ("payment", ("ödeme", "odeme", "fatura", "payment", "invoice")),
    ("notification", ("bildirim", "notification")),
)


LEVEL_TO_STATUS = {
    "success": "Başarılı",
    "info": "Bilgi",
    "warning": "Uyarı",
    "critical": "Kritik",
    "error": "Hata",
}


ACTION_TO_ICON = {
    "notification": "fa-bell",
    "competitor": "fa-user-secret",
    "campaign": "fa-bullhorn",
    "ad": "fa-rectangle-ad",
    "ai": "fa-robot",
    "optimization": "fa-sliders",
    "account": "fa-plug",
    "payment": "fa-credit-card",
    "system": "fa-server",
}


def infer_action_type(title="", message="", fallback="system"):
    text = f"{title or ''} {message or ''}".lower()
    for action_type, keywords in ACTION_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return action_type
    return fallback


def status_label(level):
    return LEVEL_TO_STATUS.get((level or "info").lower(), "Bilgi")


def action_icon(action_type):
    return ACTION_TO_ICON.get(action_type or "system", ACTION_TO_ICON["system"])


def record_activity(
    *,
    user,
    title,
    message="",
    action_type=None,
    level="info",
    icon="",
    link=None,
    metadata=None,
    dedupe_key=None,
):
    if not user:
        return None

    try:
        from core.models import ActivityLog

        action_type = action_type or infer_action_type(title, message)
        metadata = metadata or {}
        if dedupe_key:
            metadata = {**metadata, "dedupe_key": dedupe_key}
            existing = ActivityLog.objects.filter(
                user=user,
                metadata__dedupe_key=dedupe_key,
            ).order_by("-id").first()
            if existing:
                return existing

        return ActivityLog.objects.create(
            user=user,
            action_type=action_type,
            title=title,
            message=message or "",
            level=level or "info",
            icon=icon or action_icon(action_type),
            link=link,
            metadata=metadata,
            created_at=timezone.now(),
        )
    except Exception as exc:
        logger.exception("Aktivite kaydı oluşturulamadı: %s", exc)
        return None


def object_activity_link(obj):
    if not obj:
        return None

    model_name = obj.__class__.__name__
    obj_id = getattr(obj, "id", None)
    if not obj_id:
        return None

    try:
        if model_name == "AdCampaign":
            return reverse("campaign_detail", kwargs={"campaign_id": obj_id})
        if model_name == "Campaign":
            return f"{reverse('campaign_center')}?open_octo={obj_id}"
        if model_name == "Ad":
            source_type = (getattr(obj, "source_type", "") or "").upper()
            if source_type == "COMPETITOR":
                return f"{reverse('competitor_intelligence')}?open_competitor_ad={obj_id}"
            return f"{reverse('ads_center')}?open_ad={obj_id}"
        if model_name == "Creative":
            return f"{reverse('creative_center')}?open_creative={obj_id}"
        if model_name == "CreativeProject":
            return f"{reverse('creative_studio')}?project={obj_id}"
        if model_name == "BudgetOptimizationLog":
            ad_id = getattr(getattr(obj, "reklam", None), "id", None)
            if ad_id:
                return f"{reverse('optimization_history')}?ad={ad_id}&log={obj_id}"
            return reverse("optimization_history")
        if model_name == "PlatformSyncJob":
            return f"{reverse('sync_center')}?job={obj_id}"
        if model_name == "RawDataSnapshot":
            return f"{reverse('sync_center')}?snapshot={obj_id}"
        if model_name == "AnomalyAlert":
            return f"{reverse('anomaly_dashboard')}?alert={obj_id}"
        if model_name == "Competitor":
            return f"{reverse('competitor_intelligence')}?competitor={obj_id}"
    except Exception:
        return None

    return None


def record_activity_from_notification(notification):
    if not notification or not getattr(notification, "user", None):
        return None

    notification_id = getattr(notification, "id", None)
    return record_activity(
        user=notification.user,
        title=notification.title,
        message=notification.message,
        action_type=infer_action_type(notification.title, notification.message, "notification"),
        level=getattr(notification, "level", "info"),
        icon=action_icon(infer_action_type(notification.title, notification.message, "notification")),
        link=getattr(notification, "link", None),
        metadata={
            "source": "notification",
            "notification_id": notification_id,
            "actor": "Sistem",
        },
        dedupe_key=f"notification_{notification_id}" if notification_id else None,
    )
