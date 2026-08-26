import json
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.models.notification import Notification
from core.models.notification_settings import ActivityLog, NotificationPreference
from core.services.activity_service import action_icon, record_activity_from_notification, status_label


LEVELS = ["success", "info", "warning", "critical", "error"]
LEVEL_LABELS = {
    "success": "Başarılı",
    "info": "Bilgi",
    "warning": "Uyarı",
    "critical": "Kritik",
    "error": "Hata",
}
ACTION_LABELS = {
    "notification": "Bildirim",
    "competitor": "Rakip",
    "campaign": "Kampanya",
    "ad": "Reklam",
    "ai": "AI",
    "optimization": "Optimizasyon",
    "account": "Hesap",
    "payment": "Ödeme",
    "system": "Sistem",
}
GENERIC_ACTIVITY_LINKS = {
    "",
    "/",
    "/performance-center/",
    "/creative-center/",
    "/creative-studio/",
    "/sync-center/",
    "/budget-optimization/",
    "/rakip-reklam-paneli/",
    "/rakip-reklam-hareketleri/",
    "/reklam-hareketleri/",
    "/ads-center/",
    "/campaign-center/",
    "/hesap-ekle/",
}
DEFAULT_ACTIVITY_MESSAGES = {
    "notification": "Bildirim merkezi üzerinden takip edilen bir sistem bildirimi oluştu.",
    "competitor": "Rakip izleme alanında bir kayıt veya güncelleme yapıldı.",
    "campaign": "Kampanya yönetimiyle ilgili bir işlem kayda alındı.",
    "ad": "Reklam hesabı veya reklam metriğiyle ilgili bir işlem gerçekleşti.",
    "ai": "Octo AI tarafından analiz, öneri veya içerik üretim süreci çalıştı.",
    "optimization": "Bütçe veya performans optimizasyonu ile ilgili bir işlem kayda alındı.",
    "account": "Bağlı platform hesabı veya senkronizasyon süreciyle ilgili işlem gerçekleşti.",
    "payment": "Ödeme, fatura veya üyelik planıyla ilgili bir işlem kayda alındı.",
    "system": "Sistem tarafından otomatik bir işlem kayda alındı.",
}

LEGACY_NOTIFICATION_LINKS = {
    "/": "dashboard",
    "/ai/dashboard/": "ai_dashboard",
    "/anomaly-dashboard/": "anomaly_detector",
    "/budget-optimization/history/": "optimization_history",
    "/budget-optimization/": "apply_rules_to_campaigns",
    "/campaigns/": "campaign_center",
    "/creative-studio/": "creative_studio_dashboard",
    "/hesap-ekle/": "hesap_ekle",
    "/instagram/": "instagram_dashboard",
    "/membership/": "my_account",
    "/rakip-analiz/": "competitor_intelligence",
    "/rakip-reklam-hareketleri/": "rakip_reklam_hareketleri",
    "/rakip-reklam-paneli/": "rakip_reklam_paneli",
    "/reklam-hareketleri/": "reklam_hareketleri",
    "/reklam-raporu/": "reports_center",
    "/reports/": "reports_center",
}


def _reverse_or_none(name):
    try:
        return reverse(name)
    except Exception:
        return None


def _inferred_object_url(notification):
    """Resolve legacy generic notifications to the object named in their copy."""
    from core.models import Ad, AdCampaign, Campaign, Competitor
    from core.services.activity_service import object_activity_link

    text = f"{notification.title or ''} {notification.message or ''}".casefold()
    candidates = []
    candidates.extend(Ad.objects.filter(user=notification.user).exclude(name="").only("id", "name", "source_type"))
    candidates.extend(Campaign.objects.filter(user=notification.user).exclude(name="").only("id", "name"))
    candidates.extend(
        AdCampaign.objects.filter(instagram_account__user=notification.user)
        .exclude(campaign_name="")
        .only("id", "campaign_name")
    )
    candidates.extend(Competitor.objects.filter(user=notification.user).exclude(name="").only("id", "name"))

    matches = []
    for obj in candidates:
        name = getattr(obj, "name", None) or getattr(obj, "campaign_name", None) or ""
        if len(name) >= 3 and name.casefold() in text:
            matches.append((len(name), obj))
    if not matches:
        return None
    return object_activity_link(max(matches, key=lambda item: item[0])[1])


def _notification_target_url(notification, request):
    raw_link = (notification.link or "").strip()
    fallback = reverse("notification_center")
    if not raw_link or raw_link == "#":
        return _inferred_object_url(notification) or fallback

    parsed = urlsplit(raw_link)
    query = parse_qs(parsed.query)
    if parsed.path.rstrip("/") == "/rakip-reklam-paneli" and query.get("ad"):
        try:
            ad_id = int(query["ad"][0])
        except (TypeError, ValueError):
            ad_id = None
        if ad_id:
            return f"{reverse('competitor_intelligence')}?open_competitor_ad={ad_id}"

    if parsed.path in {"/dashboard/", "/ads-center/", "/campaign-center/", "/rakip-reklam-paneli/"}:
        inferred = _inferred_object_url(notification)
        if inferred:
            return inferred

    normalized = LEGACY_NOTIFICATION_LINKS.get(raw_link)
    if normalized:
        return _reverse_or_none(normalized) or fallback

    if raw_link.startswith("/"):
        return raw_link

    if url_has_allowed_host_and_scheme(
        raw_link,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return raw_link

    return fallback


def _clean_text(value):
    if not value:
        return ""
    text = str(value)
    if any(marker in text for marker in ("Ã", "Ä", "Å", "â")):
        try:
            return text.encode("latin1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    replacements = {
        "Ä±": "ı",
        "Ä°": "İ",
        "ÄŸ": "ğ",
        "Ã¼": "ü",
        "Ã¶": "ö",
        "Ã§": "ç",
        "ÅŸ": "ş",
        "Åž": "Ş",
        "â‚º": "₺",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _specific_activity_link(link):
    link = (link or "").strip()
    if not link or link in GENERIC_ACTIVITY_LINKS:
        return ""
    if "?" in link:
        return link
    parts = [part for part in link.strip("/").split("/") if part]
    if any(part.isdigit() for part in parts):
        return link
    return ""


@login_required
def notification_center(request):
    query = request.GET.get("q", "").strip()
    level = request.GET.get("level", "").strip()
    status = request.GET.get("status", "").strip()

    notifications = Notification.objects.filter(user=request.user)

    if query:
        notifications = notifications.filter(Q(title__icontains=query) | Q(message__icontains=query))
    if level in LEVELS:
        notifications = notifications.filter(level=level)
    if status == "unread":
        notifications = notifications.filter(is_read=False)
    elif status == "read":
        notifications = notifications.filter(is_read=True)

    paginator = Paginator(notifications, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    counts = {
        "total": Notification.objects.filter(user=request.user).count(),
        "unread": Notification.objects.filter(user=request.user, is_read=False).count(),
        "critical": Notification.objects.filter(user=request.user, level="critical", is_read=False).count(),
        "warning": Notification.objects.filter(user=request.user, level="warning", is_read=False).count(),
    }

    preferences, _ = NotificationPreference.objects.get_or_create(user=request.user)

    return render(request, "notifications/notification_center.html", {
        "page_obj": page_obj,
        "notifications": page_obj.object_list,
        "counts": counts,
        "query": query,
        "selected_level": level,
        "selected_status": status,
        "preferences": preferences,
        "levels": LEVELS,
        "level_filters": [{"key": key, "label": LEVEL_LABELS.get(key, key)} for key in LEVELS],
    })


@login_required
def activity_log(request):
    query = request.GET.get("q", "").strip()
    action_type = request.GET.get("type", "").strip()
    level = request.GET.get("level", "").strip()

    for notification in Notification.objects.filter(user=request.user).order_by("-created_at")[:100]:
        record_activity_from_notification(notification)

    activities = ActivityLog.objects.filter(user=request.user)
    if query:
        activities = activities.filter(
            Q(title__icontains=query)
            | Q(message__icontains=query)
            | Q(metadata__actor__icontains=query)
        )
    if action_type:
        activities = activities.filter(action_type=action_type)
    if level:
        activities = activities.filter(level=level)

    base_qs = ActivityLog.objects.filter(user=request.user)
    counts_by_type = dict(base_qs.values_list("action_type").annotate(total=Count("id")))
    total_count = base_qs.count()
    warning_count = base_qs.filter(level__in=["warning", "critical", "error"]).count()
    success_count = base_qs.filter(level="success").count()
    latest_activity = base_qs.order_by("-created_at").first()

    paginator = Paginator(activities, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    activity_rows = []
    for activity in page_obj.object_list:
        metadata = activity.metadata or {}
        module_label = ACTION_LABELS.get(activity.action_type, "Sistem")
        message = _clean_text(activity.message) or DEFAULT_ACTIVITY_MESSAGES.get(activity.action_type, DEFAULT_ACTIVITY_MESSAGES["system"])
        activity_rows.append({
            "item": activity,
            "title": _clean_text(activity.title),
            "message": message,
            "actor": metadata.get("actor") or "Sistem",
            "module_label": module_label,
            "status_label": status_label(activity.level),
            "icon_class": activity.icon if str(activity.icon).startswith("fa-") else action_icon(activity.action_type),
            "detail_link": _specific_activity_link(activity.link),
        })

    return render(request, "notifications/activity_log.html", {
        "page_obj": page_obj,
        "activities": activity_rows,
        "query": query,
        "selected_type": action_type,
        "selected_level": level,
        "action_choices": ActivityLog.ACTION_CHOICES,
        "action_filters": [
            {"key": key, "label": ACTION_LABELS.get(key, label), "count": counts_by_type.get(key, 0)}
            for key, label in ActivityLog.ACTION_CHOICES
        ],
        "level_filters": [{"key": key, "label": LEVEL_LABELS.get(key, key)} for key in LEVELS],
        "owner_label": request.user.get_full_name() or request.user.username,
        "counts_by_type": counts_by_type,
        "summary": {
            "total": total_count,
            "success": success_count,
            "warning": warning_count,
            "latest": latest_activity,
        },
    })


@login_required
@require_POST
def mark_notification_read(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.is_read = True
    notification.save(update_fields=["is_read"])
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
        return JsonResponse({"success": True, "unread_count": unread_count})
    return redirect("notification_center")


@login_required
def open_notification(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])
    return redirect(_notification_target_url(notification, request))


@login_required
@require_POST
def delete_notification(request, notification_id):
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.delete()
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"success": True})
    return redirect("notification_center")


@login_required
@require_POST
def mark_all_notifications_read(request):
    updated = Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    if request.headers.get("x-requested-with") != "XMLHttpRequest":
        return redirect("notification_center")
    return JsonResponse({"success": True, "updated": updated})


@login_required
@require_POST
def bulk_notifications_action(request):
    action = request.POST.get("action")
    ids = request.POST.getlist("notification_ids")
    qs = Notification.objects.filter(user=request.user)
    if ids:
        qs = qs.filter(id__in=ids)

    if action == "mark_read":
        count = qs.update(is_read=True)
    elif action == "delete":
        count, _ = qs.delete()
    else:
        count = 0

    return JsonResponse({"success": True, "count": count})


@login_required
def update_notification_preferences(request):
    if request.method != "POST":
        return redirect(f"{reverse('notification_center')}#notification-preferences")

    preferences, _ = NotificationPreference.objects.get_or_create(user=request.user)
    fields = [
        "competitor_notifications", "ai_notifications", "campaign_notifications",
        "optimization_notifications", "system_notifications", "critical_notifications",
        "in_app_enabled", "realtime_enabled", "email_enabled", "daily_summary_enabled",
    ]
    for field in fields:
        setattr(preferences, field, request.POST.get(field) == "on")
    preferences.save(update_fields=fields + ["updated_at"])
    return redirect("notification_center")




@login_required
def latest_notifications_api(request):
    """Base.html fallback endpoint.

    Kritik kural:
    - after_id 0 ise eski okunmamış bildirimleri geri döndürme.
      Aksi halde sayfa açılır açılmaz eski 30-40 bildirim tekrar dropdown'a basılır.
    - Sayaç her zaman backend'deki gerçek okunmamış sayıdan döner.
    """
    try:
        after_id = int(request.GET.get("after_id", "0") or 0)
    except ValueError:
        after_id = 0

    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()

    if after_id <= 0:
        return JsonResponse({
            "success": True,
            "notifications": [],
            "unread_count": unread_count,
        })

    qs = Notification.objects.filter(
        user=request.user,
        is_read=False,
        id__gt=after_id,
    ).order_by("id")[:10]

    data = []
    for n in qs:
        data.append({
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "level": n.level,
            "icon": n.icon,
            "link": n.link or "#",
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "is_read": n.is_read,
        })

    return JsonResponse({
        "success": True,
        "notifications": data,
        "unread_count": unread_count,
    })


@login_required
@require_POST
def api_alert_dismiss(request):
    """Base.html dropdown için geriye dönük uyumlu okundu endpoint'i."""
    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        data = {}
    notification_id = data.get("notification_id") or request.POST.get("notification_id")
    if notification_id:
        Notification.objects.filter(user=request.user, id=notification_id).update(is_read=True)
    return JsonResponse({"success": True})
