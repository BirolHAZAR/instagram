from decimal import Decimal
import re

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from core.models import CampaignOctoAnalysis, CampaignOctoRecommendation
from core.services.octo_recommendation_engine import build_octo_task_recommendation_context


def _safe_num(value, default=Decimal("0")):
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except Exception:
        return default


def _short(text, fallback="Octo AI tavsiyesi", limit=160):
    text = (text or "").strip()
    if not text:
        text = fallback
    text = " ".join(text.split())
    return text[: limit - 1] + "…" if len(text) > limit else text

def _fmt_number(value, decimals=2):
    try:
        number = Decimal(str(value or 0))
    except Exception:
        number = Decimal("0")
    formatted = f"{number:,.{decimals}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _format_numbers_in_text(text):
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

    return re.sub(r"%?-?\d+\.\d+", repl, str(text))


def _split_to_bullets(text, fallback="Bilgi bulunamadı", max_items=5):
    text = _format_numbers_in_text(_short(text, fallback, 420))
    text = text.replace("•", "\n").replace("- ", "\n")
    parts = []
    for chunk in re.split(r"[\n;]+|(?<!\d\.)(?<=[.!?])\s+", text):
        item = chunk.strip(" .-•\t")
        if item and item not in parts:
            parts.append(item)
        if len(parts) >= max_items:
            break
    return parts or [fallback]


def _legacy_report_sections(title, detail, impact):
    formatted_title = _format_numbers_in_text(title)
    detail_items = [
        item
        for item in _split_to_bullets(detail, "Kampanya için kayıtlı öneri detayı bulunuyor.", 5)
        if not item.casefold().startswith(formatted_title.casefold())
    ]
    return [
        {"key": "problem", "title": "Sorun", "icon": "fa-triangle-exclamation", "items": [formatted_title] + detail_items[:4]},
        {"key": "why", "title": "Neden Önemli", "icon": "fa-circle-info", "items": ["Bu öneri kampanya performansını, maliyet verimliliğini veya dönüşüm kalitesini etkileyebilir."]},
        {"key": "action", "title": "Önerilen Aksiyonlar", "icon": "fa-list-check", "items": _split_to_bullets(detail, "Öneriyi incele ve ilgili kampanya üzerinde aksiyon al.", 5)},
        {"key": "impact", "title": "Beklenen Etki", "icon": "fa-chart-line", "items": _split_to_bullets(impact, "Etki uygulama sonrası ölçülür.", 4)},
    ]


def _priority_label(priority):
    return {
        "urgent": "Acil",
        "high": "Yüksek",
        "medium": "Orta",
        "low": "Düşük",
    }.get((priority or "medium").lower(), "Orta")


def _priority_class(priority):
    return {
        "urgent": "urgent",
        "high": "high",
        "medium": "medium",
        "low": "low",
    }.get((priority or "medium").lower(), "medium")


def _impact_text(rec):
    parts = []
    roas_gain = _safe_num(getattr(rec, "estimated_roas_gain", 0))
    ctr_gain = _safe_num(getattr(rec, "estimated_ctr_gain", 0))
    conv_gain = _safe_num(getattr(rec, "estimated_conversion_gain", 0))
    if roas_gain:
        parts.append(f"ROAS +{_fmt_number(roas_gain, 2)}%")
    if ctr_gain:
        parts.append(f"CTR +{_fmt_number(ctr_gain, 2)}%")
    if conv_gain:
        parts.append(f"Dönüşüm +{_fmt_number(conv_gain, 2)}%")
    if parts:
        return " · ".join(parts)
    return _short(getattr(rec, "expected_impact", ""), "Etki analizi bekliyor", 90)


def _recommendation_rows(qs):
    rows = []
    for rec in qs:
        campaign = getattr(rec, "campaign", None)
        analysis = getattr(rec, "analysis", None)
        created_at = getattr(rec, "created_at", None)
        applied_at = getattr(rec, "applied_at", None)
        title = _short(
            getattr(rec, "summary", "")
            or getattr(rec, "recommendations", "")
            or getattr(rec, "expected_impact", ""),
            "Kampanya için Octo AI aksiyon önerisi",
            110,
        )
        detail = _short(
            getattr(rec, "recommendations", "")
            or getattr(rec, "summary", "")
            or getattr(rec, "weaknesses", "")
            or getattr(rec, "expected_impact", ""),
            "Bu kampanya için kayıtlı öneri detayı bulunuyor.",
            260,
        )
        impact = _impact_text(rec)
        rows.append({
            "source_type": "legacy_recommendation",
            "id": rec.id,
            "title": _format_numbers_in_text(title),
            "detail": _format_numbers_in_text(detail),
            "report_sections": _legacy_report_sections(title, detail, impact),
            "campaign_id": getattr(campaign, "id", None),
            "campaign_name": getattr(rec, "campaign_name", "") or getattr(campaign, "name", "") or "Kampanya",
            "platform_name": getattr(rec, "platform_name", "") or getattr(campaign, "platform", "") or "Platform",
            "account_name": getattr(rec, "account_name", "") or "",
            "priority": getattr(rec, "priority", "medium"),
            "priority_label": _priority_label(getattr(rec, "priority", "medium")),
            "priority_class": _priority_class(getattr(rec, "priority", "medium")),
            "is_applied": bool(getattr(rec, "is_applied", False)),
            "created_at": timezone.localtime(created_at).strftime("%d.%m.%Y %H:%M") if created_at else "",
            "applied_at": timezone.localtime(applied_at).strftime("%d.%m.%Y %H:%M") if applied_at else "",
            "impact": impact,
            "difficulty_level": getattr(rec, "difficulty_level", "") or "Orta",
            "implementation_time": getattr(rec, "implementation_time", "") or "3-7 gün",
            "action_type": getattr(rec, "action_type", "") or "Optimizasyon",
            "analysis_id": getattr(analysis, "id", None),
            "analysis_score": getattr(analysis, "octo_score", None) or getattr(analysis, "analysis_score", None) or 0,
            "target_url": "",
            "task_url": "",
        })
    return rows


@login_required
def campaign_octo_recommendations(request):
    status = request.GET.get("status", "pending")
    priority = request.GET.get("priority", "all")
    q = (request.GET.get("q") or "").strip()

    # Ana kaynak artık Octo Görev Merkezi'dir. Görev motoru gerçek sinyali yakalar;
    # bu sayfa o görevleri stratejik tavsiye ve yorum formatında gösterir.
    context = build_octo_task_recommendation_context(
        user=request.user,
        status=status,
        priority=priority,
        q=q,
    )

    legacy_analysis_rows = []

    # Eğer görev motorunda henüz kayıt yoksa eski CampaignOctoRecommendation kayıtları
    # yalnızca güvenli fallback olarak gösterilir. Normal akış OctoTaskInstance üzerinden ilerler.
    if not context["rows"]:
        qs = CampaignOctoRecommendation.objects.select_related("campaign", "analysis").filter(
            Q(user=request.user) | Q(user__isnull=True)
        )

        if status == "pending":
            qs = qs.filter(is_applied=False)
        elif status == "applied":
            qs = qs.filter(is_applied=True)
        elif status == "critical":
            qs = qs.filter(Q(priority="urgent") | Q(priority="high"))

        if priority in {"urgent", "high", "medium", "low"}:
            qs = qs.filter(priority=priority)

        if q:
            qs = qs.filter(
                Q(campaign_name__icontains=q)
                | Q(summary__icontains=q)
                | Q(recommendations__icontains=q)
                | Q(expected_impact__icontains=q)
                | Q(platform_name__icontains=q)
            )

        legacy_rows = _recommendation_rows(qs.order_by("is_applied", "-created_at")[:80])
        if legacy_rows:
            context["rows"] = legacy_rows
            base_qs = CampaignOctoRecommendation.objects.filter(Q(user=request.user) | Q(user__isnull=True))
            context["stats"] = {
                "total": base_qs.count(),
                "pending": base_qs.filter(is_applied=False).count(),
                "applied": base_qs.filter(is_applied=True).count(),
                "critical": base_qs.filter(Q(priority="urgent") | Q(priority="high")).count(),
            }
        else:
            analysis_qs = CampaignOctoAnalysis.objects.exclude(recommendation_text="").filter(
                Q(user=request.user) | Q(user__isnull=True)
            ).select_related("campaign").order_by("-created_at")[:20]
            for analysis in analysis_qs:
                legacy_analysis_rows.append({
                    "title": _short(analysis.recommendation_text, "Octo AI analiz önerisi", 120),
                    "detail": _short(analysis.recommendation_text, "Analiz önerisi", 260),
                    "campaign_name": getattr(analysis, "campaign_name", "") or getattr(getattr(analysis, "campaign", None), "name", "") or "Kampanya",
                    "platform_name": getattr(analysis, "platform_name", "") or "Platform",
                    "score": getattr(analysis, "octo_score", 0) or getattr(analysis, "analysis_score", 0),
                    "created_at": timezone.localtime(analysis.created_at).strftime("%d.%m.%Y %H:%M") if analysis.created_at else "",
                })

    context["legacy_analysis_rows"] = legacy_analysis_rows
    return render(request, "reports/campaign_octo_recommendations.html", context)
