from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlencode

from django.db.models import Q
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from core.models import OctoTaskInstance


def _safe_decimal(value, default=Decimal("0")):
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _short(text, fallback="Octo tavsiyesi", limit=180):
    text = str(text or "").strip()
    if not text:
        text = fallback
    text = " ".join(text.split())
    return text[: limit - 1] + "…" if len(text) > limit else text


def _fmt_number(value, decimals=2):
    number = _safe_decimal(value)
    formatted = f"{number:,.{decimals}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_percent(value):
    return f"%{_fmt_number(value, 2)}"



def _format_numbers_in_text(text):
    """Metin içindeki uzun ondalık değerleri TR formatında 2 haneye indirir."""
    if text is None:
        return ""

    def repl(match):
        raw = match.group(0)
        prefix = ""
        number_text = raw
        if raw.startswith("%"):
            prefix = "%"
            number_text = raw[1:]
        try:
            return f"{prefix}{_fmt_number(number_text, 2)}"
        except Exception:
            return raw

    # Uzun Decimal/float değerler ve yüzde değerleri: 0.095349 -> 0,10 / %-80.40 -> %-80,40
    return re.sub(r"%?-?\d+\.\d+", repl, str(text))


def _split_to_bullets(text, fallback="Bilgi bulunamadı", max_items=5):
    text = _format_numbers_in_text(_short(text, fallback, 520))

    # Octo görev mesajları bazen tek paragrafta gelir:
    # "Tespit edilen durum: ... Mevcut değer: ... Önceki değer: ... Değişim: ...".
    # Rapor görünümünde bu alanların her biri ayrı madde olmalı.
    metric_labels = [
        "Kampanya",
        "Reklam Grubu",
        "Reklam",
        "Kreatif",
        "Tespit edilen durum",
        "Mevcut değer",
        "Önceki değer",
        "Değişim",
        "Beklenen etki",
        "Önerilen aksiyon",
        "Aksiyon",
        "Neden",
        "Sonuç",
    ]
    for label in metric_labels:
        text = re.sub(rf"(?<!^)(?<!\n)\s+({re.escape(label)}\s*:)", r"\n\1", text, flags=re.IGNORECASE)

    text = text.replace("•", "\n").replace(" - ", "\n").replace(";", "\n")
    parts = []
    for chunk in re.split(r"[\n]+|(?<!\d\.)(?<=[.!?])\s+", text):
        item = chunk.strip(" .-•\t")
        normalized = re.sub(r"\W+", " ", item, flags=re.UNICODE).strip().casefold()
        if item and normalized and normalized not in {part[0] for part in parts}:
            parts.append((normalized, item))
        if len(parts) >= max_items:
            break
    return [part[1] for part in parts] or [fallback]


def _without_repeated_finding(title, items):
    """Keep a finding once and remove detail lines that repeat its title."""
    title_key = re.sub(r"\W+", " ", title, flags=re.UNICODE).strip().casefold()
    result = [title]
    seen = {title_key}
    for item in items:
        item_key = re.sub(r"\W+", " ", item, flags=re.UNICODE).strip().casefold()
        if not item_key or item_key in seen:
            continue
        if title_key and item_key.startswith(f"{title_key} "):
            continue
        seen.add(item_key)
        result.append(item)
    return result


def _align_platform_references(text, task):
    """Prevent a generic rule explanation from naming the wrong platform."""
    current = _platform_name(task)
    if not current or current == "Platform":
        return text
    platforms = ("Instagram", "Facebook", "TikTok", "Google Ads", "YouTube", "LinkedIn", "X")
    updated = str(text or "")
    for platform in platforms:
        if platform.casefold() != current.casefold():
            updated = re.sub(rf"\b{re.escape(platform)}\b", current, updated, flags=re.IGNORECASE)
    return updated


def _task_report_sections(task, message, root_cause, action, impact):
    title = _format_numbers_in_text(_short(getattr(task, "title_tr", ""), "Octo görevi", 120))
    severity = (getattr(task, "severity", "") or "").lower()
    priority_note = "Bu kayıt öncelikli takip gerektirir." if severity in {"critical", "warning"} else "Bu kayıt iyileştirme/fırsat alanı olarak takip edilir."

    problem_items = _without_repeated_finding(
        title,
        _split_to_bullets(message, "Görev son performans sinyallerinden üretildi.", 6),
    )
    return [
        {
            "key": "problem",
            "title": "Sorun",
            "icon": "fa-triangle-exclamation",
            "items": problem_items[:5],
        },
        {
            "key": "why",
            "title": "Neden Önemli",
            "icon": "fa-circle-info",
            "items": _split_to_bullets(root_cause, "Performans, bütçe, kreatif veya rakip baskısı nedeniyle sonuçları etkileyebilir.", 4),
        },
        {
            "key": "action",
            "title": "Önerilen Aksiyonlar",
            "icon": "fa-list-check",
            "items": _split_to_bullets(action, "Görevi incele ve ilgili kampanya/reklam üzerinde aksiyon al.", 5),
        },
        {
            "key": "impact",
            "title": "Beklenen Etki",
            "icon": "fa-chart-line",
            "items": _split_to_bullets(impact, "Etki görev tamamlandıktan sonra ölçülür.", 4) + [priority_note],
        },
    ]

def _local_time(value):
    if not value:
        return ""
    try:
        return timezone.localtime(value).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)[:16]


def _priority_label_from_task(task):
    severity = (getattr(task, "severity", "") or "").lower()
    score = int(getattr(task, "priority_score", 0) or 0)
    if severity == "critical" or score >= 90:
        return "Acil", "urgent"
    if severity == "warning" or score >= 70:
        return "Yüksek", "high"
    if severity == "opportunity":
        return "Fırsat", "low"
    return "Orta", "medium"


def _status_label(status):
    return {
        "open": "Bekliyor",
        "viewed": "Atandı / İnceleniyor",
        "snoozed": "Ertelendi",
        "done": "Tamamlandı",
        "dismissed": "Kapatıldı",
    }.get(status or "open", "Bekliyor")


def _module_label(module):
    return {
        "performance": "Performans",
        "creative": "Kreatif",
        "budget": "Bütçe",
        "competitor": "Rakip",
        "conversion": "Dönüşüm",
    }.get(module or "", "Genel")


def _target_name(task):
    for obj in (getattr(task, "campaign", None), getattr(task, "ad_group", None), getattr(task, "ad", None), getattr(task, "creative", None), getattr(task, "platform_account", None)):
        if obj is None:
            continue
        name = getattr(obj, "name", None) or getattr(obj, "account_name", None) or str(obj)
        if name:
            return _short(name, "Kayıt", 90)
    return "Genel hesap görevi"


def _platform_name(task):
    platform_account = getattr(task, "platform_account", None)
    try:
        if platform_account and platform_account.platform:
            return platform_account.platform.name
    except Exception:
        pass
    return "Platform"


def _safe_reverse(name, fallback):
    try:
        return reverse(name)
    except NoReverseMatch:
        return fallback


def _task_target_url(task):
    ad = getattr(task, "ad", None)
    creative = getattr(task, "creative", None)
    ad_group = getattr(task, "ad_group", None)
    campaign = getattr(task, "campaign", None)

    if ad is not None and getattr(ad, "id", None):
        if getattr(ad, "source_type", None) == "COMPETITOR" or getattr(task, "module", None) == "competitor":
            base = _safe_reverse("competitor_intelligence", "/competitor-intelligence/")
            competitor = getattr(ad, "competitor", None)
            competitor_name = getattr(competitor, "name", None) or getattr(ad, "competitor_name", None) or "Rakip"
            return f"{base}?{urlencode({'open_competitor_ad': ad.id, 'competitor': competitor_name})}"
        base = _safe_reverse("ads_center", "/ads-center/")
        return f"{base}?{urlencode({'open_ad': ad.id})}"

    if creative is not None and getattr(creative, "id", None):
        base = _safe_reverse("creative_center", "/creative-center/")
        return f"{base}?{urlencode({'open_creative': creative.id})}"

    if ad_group is not None and getattr(ad_group, "id", None):
        base = _safe_reverse("adgroup_center", "/adgroup-center/")
        return f"{base}?{urlencode({'open_adgroup': ad_group.id})}"

    if campaign is not None and getattr(campaign, "id", None):
        base = _safe_reverse("campaign_center", "/campaign-center/")
        return f"{base}?{urlencode({'open_octo': campaign.id, 'campaign_name': getattr(campaign, 'name', '')})}"

    return _safe_reverse("octo_task_center", "/octo-gorev-merkezi/")


def _task_center_url(task=None):
    base = _safe_reverse("octo_task_center", "/octo-gorev-merkezi/")
    if task is not None and getattr(task, "id", None):
        return f"{base}?{urlencode({'open_task': task.id})}"
    return base


def _task_impact(task):
    rule = getattr(task, "rule", None)
    expected = getattr(rule, "expected_result", None) if rule is not None else None
    if expected:
        return _format_numbers_in_text(_short(expected, "Beklenen etki takipte", 160))

    change = getattr(task, "change_percent", None)
    detected = getattr(task, "detected_value", None)
    previous = getattr(task, "previous_value", None)
    parts = []
    if detected is not None:
        parts.append(f"Mevcut: {_fmt_number(detected)}")
    if previous is not None:
        parts.append(f"Önceki: {_fmt_number(previous)}")
    if change is not None:
        parts.append(f"Değişim: {_fmt_percent(change)}")
    return " · ".join(parts) if parts else "Etki görev tamamlandıktan sonra ölçülür"


def _task_strategy_detail(task):
    rule = getattr(task, "rule", None)
    message = _format_numbers_in_text(_short(getattr(task, "message_tr", ""), "Görev son performans sinyallerinden üretildi.", 320))
    root_cause = _format_numbers_in_text(
        _short(
            getattr(rule, "root_cause", "") if rule is not None else "",
            "Muhtemel neden performans, kreatif, bütçe veya rakip baskısı kaynaklı olabilir.",
            240,
        )
    )
    action = _format_numbers_in_text(
        _short(
            (getattr(task, "action_text_tr", "") or (getattr(rule, "cta_text", "") if rule is not None else "")),
            "Görevi incele ve ilgili kampanya/reklam üzerinde aksiyon al.",
            220,
        )
    )
    impact = _format_numbers_in_text(_task_impact(task))
    message = _align_platform_references(message, task)
    root_cause = _align_platform_references(root_cause, task)
    action = _align_platform_references(action, task)
    sections = _task_report_sections(task, message, root_cause, action, impact)

    flat_detail = " ".join(
        f"{section['title']}: " + " | ".join(section.get("items", []))
        for section in sections
    )
    return flat_detail, sections


def _task_row(task):
    priority_label, priority_class = _priority_label_from_task(task)
    campaign = getattr(task, "campaign", None)
    detail_text, report_sections = _task_strategy_detail(task)
    return {
        "source_type": "octo_task",
        "id": task.id,
        "task_id": task.id,
        "title": _short(getattr(task, "title_tr", ""), "Octo görevi", 110),
        "detail": detail_text,
        "report_sections": report_sections,
        "campaign_id": getattr(campaign, "id", None),
        "campaign_name": _target_name(task),
        "platform_name": _platform_name(task),
        "account_name": _module_label(getattr(task, "module", "")),
        "priority": getattr(task, "severity", "medium"),
        "priority_label": priority_label,
        "priority_class": priority_class,
        "is_applied": getattr(task, "status", "") == "done",
        "created_at": _local_time(getattr(task, "created_at", None)),
        "applied_at": _local_time(getattr(task, "completed_at", None)),
        "impact": _task_impact(task),
        "difficulty_level": "Orta" if getattr(task, "severity", "") != "critical" else "Yüksek",
        "implementation_time": "Bugün" if getattr(task, "severity", "") == "critical" else "1-3 gün",
        "action_type": _module_label(getattr(task, "module", "")),
        "analysis_score": getattr(task, "priority_score", 0) or 0,
        "target_url": _task_target_url(task),
        "task_url": _task_center_url(task),
        "status": getattr(task, "status", "open"),
        "status_label": _status_label(getattr(task, "status", "open")),
    }


def _base_task_queryset(user):
    return (
        OctoTaskInstance.objects
        .filter(user=user)
        .exclude(status="dismissed")
        .select_related(
            "rule",
            "campaign",
            "ad_group",
            "ad",
            "ad__competitor",
            "creative",
            "platform_account",
            "platform_account__platform",
            "platform_connection",
        )
    )


def build_octo_task_recommendation_context(user, status="pending", priority="all", q=""):
    """
    Octo Tavsiye Merkezi için ana kaynak OctoTaskInstance'tır.
    Görev Merkezi gerçek sinyali yakalar; bu servis o sinyali stratejik tavsiye formatına çevirir.
    """
    status = status or "pending"
    priority = priority or "all"
    q = (q or "").strip()

    base_qs = _base_task_queryset(user)

    qs = base_qs
    if status == "pending":
        qs = qs.filter(status__in=["open", "viewed", "snoozed"])
    elif status == "applied":
        qs = qs.filter(status="done")
    elif status == "critical":
        qs = qs.filter(severity="critical")
    elif status == "all":
        pass
    else:
        qs = qs.filter(status__in=["open", "viewed", "snoozed"])
        status = "pending"

    if priority == "urgent":
        qs = qs.filter(Q(severity="critical") | Q(priority_score__gte=90))
    elif priority == "high":
        qs = qs.filter(Q(severity__in=["critical", "warning"]) | Q(priority_score__gte=70))
    elif priority in {"medium", "low"}:
        # Eski filtrelerle uyumluluk için korunur.
        if priority == "medium":
            qs = qs.filter(priority_score__gte=40, priority_score__lt=70)
        else:
            qs = qs.filter(Q(severity="opportunity") | Q(priority_score__lt=40))

    if q:
        qs = qs.filter(
            Q(title_tr__icontains=q)
            | Q(message_tr__icontains=q)
            | Q(action_text_tr__icontains=q)
            | Q(campaign__name__icontains=q)
            | Q(ad_group__name__icontains=q)
            | Q(ad__name__icontains=q)
            | Q(creative__name__icontains=q)
            | Q(rule__title_tr__icontains=q)
        )

    stats = {
        "total": base_qs.count(),
        "pending": base_qs.filter(status__in=["open", "viewed", "snoozed"]).count(),
        "applied": base_qs.filter(status="done").count(),
        "critical": base_qs.filter(severity="critical", status__in=["open", "viewed", "snoozed"]).count(),
    }

    rows = [_task_row(task) for task in qs.order_by("-priority_score", "-last_detected_at", "-created_at")[:100]]

    module_counts = {}
    for item in base_qs.filter(status__in=["open", "viewed", "snoozed"]).values("module"):
        label = _module_label(item.get("module"))
        module_counts[label] = module_counts.get(label, 0) + 1

    top_module = max(module_counts.items(), key=lambda item: item[1])[0] if module_counts else "Genel"
    strategy_summary = {
        "title": "Octo görevlerinden üretilen stratejik tavsiye akışı",
        "text": (
            f"Octo Tavsiye Merkezi artık açık görevleri yorumlayarak önceliklendirir. "
            f"Şu anda {stats['pending']} bekleyen görev, {stats['critical']} kritik öncelik ve "
            f"en yoğun alan olarak {top_module} sinyali görünüyor."
        ),
        "source_label": "Kaynak: Octo Görev Merkezi",
    }

    return {
        "rows": rows,
        "stats": stats,
        "strategy_summary": strategy_summary,
        "selected_status": status,
        "selected_priority": priority,
        "q": q,
    }
