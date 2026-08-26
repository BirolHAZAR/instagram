from datetime import timedelta
from decimal import Decimal, InvalidOperation
import re

from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import OctoTaskInstance, OctoTaskActionLog


def _module_label(module):
    labels = {
        "performance": "Performans",
        "creative": "Kreatif",
        "budget": "Bütçe",
        "competitor": "Rakip",
        "conversion": "Dönüşüm",
    }
    return labels.get(module, "Genel")


def _severity_label(severity):
    labels = {
        "critical": "Kritik",
        "warning": "Uyarı",
        "info": "Bilgi",
        "opportunity": "Fırsat",
    }
    return labels.get(severity, "Görev")


def _status_label(status):
    labels = {
        "open": "Açık",
        "viewed": "İncelendi",
        "done": "Tamamlandı",
        "dismissed": "Kapatıldı",
        "snoozed": "Ertelendi",
    }
    return labels.get(status, "Açık")


def _format_task_number(value, *, percent=False):
    """Octo Görev Merkezi sayılarını okunabilir Türkçe formata çevirir.
    Binlik ayırıcı nokta, ondalık ayırıcı virgül olur.
    Ondalık değerler en fazla 2 haneye yuvarlanır.
    """
    if value is None or value == "":
        return "-"

    if isinstance(value, bool):
        return str(value)

    try:
        number = Decimal(str(value).replace("%", "").replace("₺", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return str(value)

    number = number.quantize(Decimal("0.01"))
    is_negative = number < 0
    number = abs(number)

    formatted = f"{number:,.2f}"
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")

    # Popup ve kartlarda sayı okunurluğu için her numerik değer 2 ondalık hane ile gösterilir.
    # Örn: 0 -> 0,00 / 12.5 -> 12,50 / 1234.567 -> 1.234,57
    if is_negative:
        formatted = f"-{formatted}"

    return f"%{formatted}" if percent else formatted




def _format_numbers_in_text(value):
    """Popup/kart açıklamalarında gömülü kalan ham ondalık sayıları TR formatına çevirir.
    Örn: 0.095349925 -> 0,10 / %-80.40 -> %-80,40.
    Tarih benzeri 22.06.2026 değerlerine dokunmaz.
    """
    text = str(value or "").strip()
    if not text:
        return text

    def repl(match):
        token = match.group(0)

        # Tarih formatlarını bozma: 22.06.2026 / 22.06.26
        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2,4}", token):
            return token

        has_prefix_percent = token.startswith("%")
        has_suffix_percent = token.endswith("%")
        raw = token.strip("%₺$€ ")

        # Sadece ondalık değerleri dönüştür. Düz adetleri (3 kreatif, 21 görev) bozma.
        if "." not in raw and "," not in raw:
            return token

        normalized = raw.replace(",", ".")
        try:
            Decimal(normalized)
        except (InvalidOperation, ValueError):
            return token

        formatted = _format_task_number(normalized, percent=False)
        if token.startswith("₺"):
            formatted = f"₺{formatted}"
        elif token.startswith("$"):
            formatted = f"${formatted}"
        elif token.startswith("€"):
            formatted = f"€{formatted}"

        if has_prefix_percent:
            formatted = f"%{formatted}"
        elif has_suffix_percent:
            formatted = f"{formatted}%"

        return formatted

    return re.sub(r"(?<![\w])[%₺$€]?-?\d+(?:[\.,]\d+)?%?(?![\w])", repl, text)


def _task_card(task):
    campaign = getattr(task, "campaign", None)
    account = getattr(task, "platform_account", None)
    platform = "-"
    try:
        if account and account.platform:
            platform = account.platform.name
    except Exception:
        platform = "-"

    return {
        "id": task.id,
        "title": task.title_tr,
        "message": _format_numbers_in_text(task.message_tr),
        "action": _format_numbers_in_text(task.action_text_tr or "İncele"),
        "campaign": getattr(campaign, "name", "Genel hesap görevi"),
        "campaign_id": getattr(campaign, "id", None),
        "platform": platform,
        "severity": task.severity,
        "severity_label": _severity_label(task.severity),
        "status": task.status,
        "status_label": _status_label(task.status),
        "module": task.module,
        "module_label": _module_label(task.module),
        "priority_score": task.priority_score,
        "priority_score_label": _format_task_number(task.priority_score),
        "detected_value": task.detected_value,
        "detected_value_label": _format_task_number(task.detected_value),
        "previous_value": task.previous_value,
        "previous_value_label": _format_task_number(task.previous_value),
        "change_percent": task.change_percent,
        "change_percent_label": _format_task_number(task.change_percent, percent=True),
        "source_period_start": task.source_period_start,
        "source_period_end": task.source_period_end,
        "last_detected_at": task.last_detected_at,
        "snoozed_until": task.snoozed_until,
    }


@login_required
def octo_task_center(request):
    user = request.user

    # Kanban sayfası tüm durum kolonlarını birlikte gösterir.
    # Varsayılan "open" olursa Atanan/İncelenen görevlerin sayacı dolu görünür,
    # ama liste sorgusu önce open ile filtrelendiği için atama kolonuna kayıt düşmez.
    # Bu yüzden varsayılan tüm durumlar olmalı.
    status_filter = request.GET.get("status", "all")
    module_filter = request.GET.get("module", "")
    severity_filter = request.GET.get("severity", "")
    search = (request.GET.get("q") or "").strip()

    tasks_qs = (
        OctoTaskInstance.objects
        .filter(user=user)
        .select_related("rule", "campaign", "platform_account", "platform_account__platform")
        .order_by("-priority_score", "-last_detected_at", "-created_at")
    )

    if status_filter and status_filter != "all":
        tasks_qs = tasks_qs.filter(status=status_filter)

    if module_filter:
        tasks_qs = tasks_qs.filter(module=module_filter)

    if severity_filter:
        tasks_qs = tasks_qs.filter(severity=severity_filter)

    if search:
        tasks_qs = tasks_qs.filter(
            Q(title_tr__icontains=search) |
            Q(message_tr__icontains=search) |
            Q(campaign__name__icontains=search)
        )

    all_user_tasks = OctoTaskInstance.objects.filter(user=user)

    stats = {
        "open": all_user_tasks.filter(status="open").count(),
        "critical": all_user_tasks.filter(status="open", severity="critical").count(),
        "warning": all_user_tasks.filter(status="open", severity="warning").count(),
        "opportunity": all_user_tasks.filter(status="open", severity="opportunity").count(),
        "done": all_user_tasks.filter(status="done").count(),
        "snoozed": all_user_tasks.filter(status="snoozed").count(),
        "viewed": all_user_tasks.filter(status="viewed").count(),
    }

    today = timezone.localdate()
    overdue_count = all_user_tasks.filter(
        status="snoozed",
        snoozed_until__date__lt=today,
    ).count()

    # Kolonlar aynı filtre tabanından beslenir.
    # Not: Atanan/İncelenen = status viewed. Sayaç ile liste aynı queryset mantığını kullanır.
    critical_qs = tasks_qs.filter(severity="critical", status__in=["open", "viewed"])
    warning_qs = tasks_qs.filter(severity="warning", status__in=["open", "viewed"])
    opportunity_qs = tasks_qs.filter(severity="opportunity", status__in=["open", "viewed"])
    assigned_qs = tasks_qs.filter(status="viewed")
    snoozed_qs = tasks_qs.filter(status="snoozed")
    done_qs = tasks_qs.filter(status="done")

    critical_rows = [_task_card(t) for t in critical_qs[:30]]
    warning_rows = [_task_card(t) for t in warning_qs[:30]]
    opportunity_rows = [_task_card(t) for t in opportunity_qs[:30]]
    assigned_rows = [_task_card(t) for t in assigned_qs[:30]]
    snoozed_rows = [_task_card(t) for t in snoozed_qs[:30]]
    done_rows = [_task_card(t) for t in done_qs[:30]]

    critical_count = critical_qs.count()
    warning_count = warning_qs.count()
    opportunity_count = opportunity_qs.count()
    assigned_count = assigned_qs.count()
    snoozed_count = snoozed_qs.count()
    done_count = done_qs.count()

    columns = [
        {
            "key": "critical",
            "title": "Kritik Görevler",
            "subtitle": "Önce müdahale edilmesi gerekenler",
            "icon": "fa-fire-flame-curved",
            "state": "critical",
            "count": critical_count,
            "rows": critical_rows,
        },
        {
            "key": "warning",
            "title": "Uyarılar",
            "subtitle": "Yakından izlenmesi gerekenler",
            "icon": "fa-triangle-exclamation",
            "state": "warning",
            "count": warning_count,
            "rows": warning_rows,
        },
        {
            "key": "opportunity",
            "title": "Fırsatlar",
            "subtitle": "Büyütülebilir alanlar",
            "icon": "fa-rocket",
            "state": "opportunity",
            "count": opportunity_count,
            "rows": opportunity_rows,
        },
        {
            "key": "assigned",
            "title": "Atanan / İncelenen",
            "subtitle": "Sahiplenilmiş görevler",
            "icon": "fa-user-check",
            "state": "assigned",
            "count": assigned_count,
            "rows": assigned_rows,
        },
        {
            "key": "snoozed",
            "title": "Ertelenenler",
            "subtitle": "Belirlenen tarihte tekrar bakılacak",
            "icon": "fa-clock",
            "state": "snoozed",
            "count": snoozed_count,
            "rows": snoozed_rows,
        },
        {
            "key": "done",
            "title": "Tamamlananlar",
            "subtitle": "Kapatılmış işler",
            "icon": "fa-circle-check",
            "state": "done",
            "count": done_count,
            "rows": done_rows,
        },
    ]

    module_breakdown = (
        all_user_tasks
        .filter(status="open")
        .values("module")
        .annotate(total=Count("id"))
        .order_by("-total")
    )

    context = {
        "stats": stats,
        "overdue_count": overdue_count,
        "columns": columns,
        "module_breakdown": module_breakdown,
        "filters": {
            "status": status_filter,
            "module": module_filter,
            "severity": severity_filter,
            "q": search,
        },
        "module_options": [
            ("performance", "Performans"),
            ("creative", "Kreatif"),
            ("budget", "Bütçe"),
            ("competitor", "Rakip"),
            ("conversion", "Dönüşüm"),
        ],
        "severity_options": [
            ("critical", "Kritik"),
            ("warning", "Uyarı"),
            ("opportunity", "Fırsat"),
            ("info", "Bilgi"),
        ],
        "status_options": [
            ("open", "Açık"),
            ("viewed", "İncelendi / Atandı"),
            ("snoozed", "Ertelendi"),
            ("done", "Tamamlandı"),
            ("all", "Tümü"),
        ],
    }

    return render(request, "dashboard/octo_task_center.html", context)


@login_required
@require_POST
def octo_task_update(request, task_id):
    task = get_object_or_404(OctoTaskInstance, id=task_id, user=request.user)
    action = request.POST.get("action")
    note = (request.POST.get("note") or "").strip()

    now = timezone.now()

    if action == "viewed":
        task.status = "viewed"
    elif action == "done":
        task.status = "done"
        task.completed_at = now
    elif action == "dismissed":
        task.status = "dismissed"
        task.dismissed_at = now
    elif action == "snoozed":
        task.status = "snoozed"
        task.snoozed_until = now + timedelta(days=1)
    elif action == "reopened":
        task.status = "open"
        task.completed_at = None
        task.dismissed_at = None
        task.snoozed_until = None
    else:
        return JsonResponse({"ok": False, "error": "Geçersiz işlem."}, status=400)

    task.save(update_fields=[
        "status",
        "completed_at",
        "dismissed_at",
        "snoozed_until",
        "updated_at",
    ])

    OctoTaskActionLog.objects.create(
        task=task,
        user=request.user,
        action=action,
        note=note,
    )

    return JsonResponse({
        "ok": True,
        "task_id": task.id,
        "status": task.status,
        "status_label": _status_label(task.status),
    })
