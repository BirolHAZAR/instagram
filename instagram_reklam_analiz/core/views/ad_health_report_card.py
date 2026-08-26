import os
import re
from html import escape
from datetime import date, timedelta
from io import BytesIO

from django.contrib.auth.decorators import login_required
from django.contrib.staticfiles import finders
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from core.models import Ad, AdMetricHistory, OctoRuleEngineRun, OctoTaskInstance, OctoTaskRule
from core.services.cache_service import CacheService
from core.services.agency_branding import get_report_branding
from core.services.agency_scope import get_agency_scope, scope_queryset
from core.views.health_center import _explain_ad, _health_score, _metric_totals
from core.tasks.admin_ops import generate_octo_tasks
from core.services.ad_ai_service import build_ad_rule_payload


REPORT_CARD_CACHE_TIMEOUT = 180


def _sentence_list(value, limit=6):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return []
    rows = [row.strip() for row in re.split(r"(?<=[.!?])\s+", text) if row.strip()]
    return rows[:limit]


def _unique_points(values, limit=8):
    rows = []
    seen = set()
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        key = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(text)
        if len(rows) >= limit:
            break
    return rows


def _rule_data_for_ad(ad):
    rules, active_rule_count = build_ad_rule_payload(ad)
    engine_run = (
        OctoRuleEngineRun.objects.filter(user=ad.user)
        .filter(Q(platform_account=ad.platform_account) | Q(platform_account__isnull=True))
        .order_by("-started_at", "-id")
        .first()
    )
    rows = [{
        "title": rule["title"],
        "severity": rule["severity"],
        "severity_label": {
            "critical": "Kritik",
            "warning": "Uyarı",
            "info": "Bilgi",
            "opportunity": "Fırsat",
        }.get(rule["severity"], "Bilgi"),
        "message_points": _unique_points(_sentence_list(rule["message"], limit=3), limit=3),
        "action_points": _unique_points(_sentence_list(rule["action"], limit=2), limit=2),
        "detected_at": rule["detected_at"],
        "scope_label": rule["scope_label"],
    } for rule in rules]
    return rows, active_rule_count, engine_run


def _pdf_font_paths():
    candidates = [
        (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
        (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\segoeuib.ttf"),
        (r"C:\Windows\Fonts\calibri.ttf", r"C:\Windows\Fonts\calibrib.ttf"),
    ]
    for regular, bold in candidates:
        if os.path.exists(regular) and os.path.exists(bold):
            return regular, bold
    return None, None


def _register_pdf_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    regular, bold = _pdf_font_paths()
    if regular and bold and "ReportCard-Regular" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("ReportCard-Regular", regular))
        pdfmetrics.registerFont(TTFont("ReportCard-Bold", bold))
        return "ReportCard-Regular", "ReportCard-Bold"
    if "ReportCard-Regular" in pdfmetrics.getRegisteredFontNames():
        return "ReportCard-Regular", "ReportCard-Bold"
    return "Helvetica", "Helvetica-Bold"


def _static_path(path):
    found = finders.find(path)
    return found if found and os.path.exists(found) else ""


def _draw_text(c, text, x, y, width, font, size, color, max_lines=2, leading=None):
    from reportlab.lib.utils import simpleSplit

    leading = leading or size + 3
    c.setFillColor(color)
    c.setFont(font, size)
    lines = simpleSplit(str(text or ""), font, size, width)
    lines = lines[:max_lines]
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def _draw_label_value(c, label, value, x, y, w, h, font, bold_font):
    from reportlab.lib import colors

    c.setFillColor(colors.white)
    c.roundRect(x, y, w, h, 8, fill=1, stroke=0)
    c.setStrokeColor(colors.HexColor("#dbe2ee"))
    c.roundRect(x, y, w, h, 8, fill=0, stroke=1)
    c.setFont(bold_font, 6.8)
    c.setFillColor(colors.HexColor("#64748b"))
    c.drawString(x + 10, y + h - 13, str(label).upper())
    _draw_text(c, value, x + 10, y + h - 29, w - 18, bold_font, 9.2, colors.HexColor("#0f172a"), max_lines=1)


def _draw_metric(c, label, value, x, y, w, h, font, bold_font):
    from reportlab.lib import colors

    c.setFillColor(colors.white)
    c.roundRect(x, y, w, h, 9, fill=1, stroke=0)
    c.setStrokeColor(colors.HexColor("#dbe2ee"))
    c.roundRect(x, y, w, h, 9, fill=0, stroke=1)
    c.setFont(bold_font, 7)
    c.setFillColor(colors.HexColor("#64748b"))
    c.drawString(x + 10, y + h - 14, str(label).upper())
    c.setFont(bold_font, 14)
    c.setFillColor(colors.HexColor("#111827"))
    c.drawString(x + 10, y + 14, str(value))


def _draw_note(c, title, value, x, y, w, h, font, bold_font):
    from reportlab.lib import colors

    c.setFillColor(colors.white)
    c.roundRect(x, y, w, h, 10, fill=1, stroke=0)
    c.setStrokeColor(colors.HexColor("#dbe2ee"))
    c.roundRect(x, y, w, h, 10, fill=0, stroke=1)
    c.setFont(bold_font, 9)
    c.setFillColor(colors.HexColor("#0f172a"))
    c.drawString(x + 10, y + h - 17, title)
    _draw_text(c, value, x + 10, y + h - 34, w - 20, font, 8, colors.HexColor("#475569"), max_lines=4, leading=10)


def _build_report_card_pdf(context):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font, bold_font = _register_pdf_fonts()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Reklam Sağlık Karnesi",
    )
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("rc-normal", parent=styles["Normal"], fontName=font, fontSize=9, leading=12, textColor=colors.HexColor("#334155"))
    small = ParagraphStyle("rc-small", parent=normal, fontSize=7, leading=9, textColor=colors.HexColor("#64748b"))
    label = ParagraphStyle("rc-label", parent=small, fontName=bold_font, fontSize=6.5, leading=8, textColor=colors.HexColor("#64748b"))
    value = ParagraphStyle("rc-value", parent=normal, fontName=bold_font, fontSize=9.5, leading=12, textColor=colors.HexColor("#0f172a"))
    title = ParagraphStyle("rc-title", parent=normal, fontName=bold_font, fontSize=22, leading=26, textColor=colors.white)
    h2 = ParagraphStyle("rc-h2", parent=normal, fontName=bold_font, fontSize=13, leading=16, textColor=colors.HexColor("#0f172a"), spaceBefore=10, spaceAfter=7)
    story = []
    usable_w = A4[0] - doc.leftMargin - doc.rightMargin

    branding = context.get("branding")
    logo_path = branding.logo_path if branding and branding.logo_path else _static_path("images/logo2.png")
    logo = Image(logo_path, width=52 * mm, height=15 * mm, kind="proportional") if logo_path else Paragraph("reklamanaliz.net", title)
    grade = Table(
        [[
            [
                Paragraph(str(context["grade"]), ParagraphStyle("grade", parent=title, fontSize=36, leading=38, alignment=1)),
                Paragraph(f"{context['score']}/100 - {context['grade_label']}", ParagraphStyle("grade-sub", parent=small, fontName=bold_font, textColor=colors.white, alignment=1)),
            ]
        ]],
        colWidths=[28 * mm],
    )
    grade.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#2f557a")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#6b87a8")),
        ("ROUNDEDCORNERS", (0, 0), (-1, -1), 12),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    header_left = [logo, Spacer(1, 6), Paragraph("Reklam Sağlık Karnesi", title)]
    header = Table([[header_left, grade]], colWidths=[usable_w - 36 * mm, 36 * mm], rowHeights=[34 * mm])
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#123b63")),
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#0f172a")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story += [header, Spacer(1, 12)]

    ad_title = context["selected_ad"].name or context["selected_ad"].headline or "Reklam"
    story.append(Paragraph(ad_title, ParagraphStyle("ad-title", parent=normal, fontName=bold_font, fontSize=17, leading=21, textColor=colors.HexColor("#0f172a"))))
    story.append(Spacer(1, 7))

    def card(label_text, value_text):
        return [Paragraph(str(label_text).upper(), label), Paragraph(str(value_text or "Belirtilmemiş"), value)]

    meta = [
        [card("Platform", context["platform"]), card("Hesap", context["account"])],
        [card("Kampanya", context["campaign"]), card("Reklam Grubu", context["ad_group"])],
    ]
    meta_table = Table(meta, colWidths=[usable_w / 2 - 4, usable_w / 2 - 4], hAlign="LEFT")
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe2ee")),
        ("INNERGRID", (0, 0), (-1, -1), 4, colors.HexColor("#f7f9fc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [meta_table, Spacer(1, 9)]

    detail_cells = [card(k, v) for k, v in context["ad_details"].items()]
    while len(detail_cells) % 3:
        detail_cells.append([Paragraph("", label), Paragraph("", value)])
    detail_rows = [detail_cells[i:i + 3] for i in range(0, len(detail_cells), 3)]
    detail_table = Table(detail_rows, colWidths=[usable_w / 3 - 4, usable_w / 3 - 4, usable_w / 3 - 4], hAlign="LEFT")
    detail_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe2ee")),
        ("INNERGRID", (0, 0), (-1, -1), 4, colors.HexColor("#f7f9fc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story += [detail_table, Spacer(1, 9)]

    for k, v in context["identity_details"].items():
        row = Table([[card(k, v)]], colWidths=[usable_w])
        row.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe2ee")),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story += [row, Spacer(1, 5)]

    story.append(Paragraph("Temel Metrikler", h2))
    metric_cells = [[card(k, v) for k, v in list(context["metrics"].items())[i:i + 2]] for i in range(0, len(context["metrics"]), 2)]
    metrics_table = Table(metric_cells, colWidths=[usable_w / 2 - 4, usable_w / 2 - 4], hAlign="LEFT")
    metrics_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe2ee")),
        ("INNERGRID", (0, 0), (-1, -1), 4, colors.HexColor("#f7f9fc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story += [metrics_table, Spacer(1, 8)]

    story.append(Paragraph("Performans Bileşenleri", h2))
    component_data = [[Paragraph("Bileşen", label), Paragraph("Puan", label)]]
    for item in context["components"]:
        component_data.append([Paragraph(item["label"], normal), Paragraph(str(item["score"]), value)])
    component_table = Table(component_data, colWidths=[usable_w - 34 * mm, 34 * mm], repeatRows=1)
    component_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef8")),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe2ee")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5eaf3")),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [component_table, Spacer(1, 8)]

    story.append(Paragraph("Karne Notları", h2))
    def bullet_note(points):
        return Paragraph("<br/>".join(f"&#8226; {escape(str(point))}" for point in points), normal)

    notes = [
        [Paragraph("Güçlü Taraf", label), bullet_note(context["note_points"]["strength"])],
        [Paragraph("Risk", label), bullet_note(context["note_points"]["risk"])],
        [Paragraph("Aksiyon", label), bullet_note(context["note_points"]["action"])],
    ]
    notes_table = Table(notes, colWidths=[31 * mm, usable_w - 31 * mm], splitByRow=1)
    notes_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbe2ee")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5eaf3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(notes_table)

    def footer(canvas_obj, doc_obj):
        canvas_obj.saveState()
        canvas_obj.setFont(font, 8)
        canvas_obj.setFillColor(colors.HexColor("#64748b"))
        canvas_obj.drawString(doc_obj.leftMargin, 8 * mm, "Reklam Sağlık Karnesi")
        canvas_obj.drawRightString(A4[0] - doc_obj.rightMargin, 8 * mm, context["today"].strftime("%d.%m.%Y"))
        canvas_obj.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def _fmt_number(value, digits=2):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0
    text = f"{number:,.{digits}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _grade(score):
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "E"


def _grade_label(score):
    if score >= 80:
        return "Güçlü"
    if score >= 60:
        return "Geliştirilebilir"
    if score >= 40:
        return "Riskli"
    return "Kritik"


def _tr_value(value, mapping):
    key = str(value or "").strip().upper()
    if not key:
        return "Belirtilmemiş"
    return mapping.get(key, str(value).replace("_", " ").title())


def _objective_label(value):
    return _tr_value(value, {
        "TRAFFIC": "Trafik",
        "CONVERSIONS": "Dönüşüm",
        "SALES": "Satış",
        "LEADS": "Potansiyel Müşteri",
        "AWARENESS": "Farkındalık",
        "REACH": "Erişim",
        "ENGAGEMENT": "Etkileşim",
        "APP_INSTALLS": "Uygulama Yükleme",
        "VIDEO_VIEWS": "Video İzlenme",
        "MESSAGES": "Mesaj",
    })


def _creative_type_label(value):
    return _tr_value(value, {
        "IMAGE": "Görsel Reklam",
        "VIDEO": "Video Reklam",
        "CAROUSEL": "Çoklu Görsel",
        "TEXT": "Metin Reklamı",
        "STORY": "Hikaye Reklamı",
        "REELS": "Reels Reklamı",
        "UNKNOWN": "Belirtilmemiş",
    })


def _cta_label(value):
    return _tr_value(value, {
        "LEARN_MORE": "Daha Fazla Bilgi Al",
        "SHOP_NOW": "Şimdi Alışveriş Yap",
        "SIGN_UP": "Kaydol",
        "CONTACT_US": "Bize Ulaş",
        "GET_QUOTE": "Teklif Al",
        "DOWNLOAD": "İndir",
        "APPLY_NOW": "Hemen Başvur",
        "BOOK_NOW": "Rezervasyon Yap",
        "SUBSCRIBE": "Abone Ol",
        "MESSAGE_PAGE": "Mesaj Gönder",
        "BUY_NOW": "Şimdi Satın Al",
    })


def _component_rows(parts):
    labels = {
        "ctr": "Tıklama İsteği",
        "cpc": "Tıklama Maliyeti",
        "cpa": "Sonuç Maliyeti",
        "roas": "Gelir Verimliliği",
        "frequency": "Yorgunluk Kontrolü",
        "engagement": "Sosyal Etkileşim",
        "conversion": "Dönüşüm Kalitesi",
    }
    return [{"label": labels[key], "score": int(value or 0)} for key, value in parts.items()]


def _build_context(request, ad_id, days):
    today = date.today()
    start = today - timedelta(days=days - 1)
    ads = (
        scope_queryset(request, Ad.objects.filter(source_type="OWN"))
        .select_related("platform_account", "platform_account__platform", "campaign", "ad_group", "creative")
        .order_by("platform_account__platform__name", "name", "id")
    )
    selected_ad = ads.filter(id=ad_id).first() if ad_id else None
    if not selected_ad:
        return {
            "empty": True,
            "days": days,
            "ads": ads,
            "has_ads": ads.exists(),
            "today": today,
            "start": start,
        }

    metric_qs = AdMetricHistory.objects.filter(ad=selected_ad, date__gte=start, date__lte=today)
    totals = _metric_totals(metric_qs)
    has_data = totals["impressions"] > 0 or totals["spend"] > 0 or totals["clicks"] > 0
    score, parts = _health_score(totals) if has_data else (0, {"ctr": 0, "cpc": 0, "cpa": 0, "roas": 0, "frequency": 0, "engagement": 0, "conversion": 0})
    explanation = _explain_ad(totals, parts, score, has_data)
    rule_matches, active_rule_count, rule_engine_run = _rule_data_for_ad(selected_ad)
    strength_points = _sentence_list(explanation["reason"])
    risk_points = _sentence_list(explanation["risk_reason"])
    action_points = _sentence_list(explanation["action"])
    for match in rule_matches:
        if match["severity"] in {"critical", "warning"}:
            risk_points.extend(match["message_points"][:1] or [match["title"]])
        else:
            strength_points.append(match["title"])
        action_points.extend(match["action_points"][:1])
    platform = selected_ad.platform_account.platform.name if selected_ad.platform_account and selected_ad.platform_account.platform else "Platform yok"
    account = selected_ad.platform_account.account_name or selected_ad.platform_account.account_id if selected_ad.platform_account else "Hesap yok"
    image_url = selected_ad.preview_image_url or (selected_ad.creative.image_url if selected_ad.creative else "") or (selected_ad.creative.thumbnail_url if selected_ad.creative else "")
    raw_type = selected_ad.ad_format or (selected_ad.creative.creative_type if selected_ad.creative else "")
    raw_cta = selected_ad.call_to_action or (selected_ad.creative.call_to_action if selected_ad.creative else "")

    return {
        "empty": False,
        "has_ads": True,
        "ads": ads,
        "selected_ad": selected_ad,
        "branding": get_report_branding(
            request.user,
            agency_client=getattr(selected_ad.platform_account, "agency_client", None) if selected_ad.platform_account else None,
        ),
        "days": days,
        "today": today,
        "start": start,
        "platform": platform,
        "account": account,
        "campaign": selected_ad.campaign.name if selected_ad.campaign else "Kampanya yok",
        "ad_group": selected_ad.ad_group.name if selected_ad.ad_group else "Reklam grubu yok",
        "image_url": image_url,
        "ad_details": {
            "Yayın Durumu": selected_ad.get_status_display() if hasattr(selected_ad, "get_status_display") else selected_ad.status,
            "Reklam Türü": _creative_type_label(raw_type),
            "Kampanya Amacı": _objective_label(selected_ad.objective),
            "İlk Görülme": selected_ad.first_seen_at.strftime("%d.%m.%Y") if selected_ad.first_seen_at else "Belirtilmemiş",
            "Son Görülme": selected_ad.last_seen_at.strftime("%d.%m.%Y") if selected_ad.last_seen_at else "Belirtilmemiş",
        },
        "identity_details": {
            "Başlık": selected_ad.headline or (selected_ad.creative.title if selected_ad.creative else "") or selected_ad.name or "Belirtilmemiş",
            "Mesaj": selected_ad.primary_text or (selected_ad.creative.body_text if selected_ad.creative else "") or selected_ad.description or "Belirtilmemiş",
            "Çağrı": _cta_label(raw_cta),
        },
        "ad_copy": selected_ad.primary_text or (selected_ad.creative.body_text if selected_ad.creative else "") or selected_ad.description or "",
        "score": score,
        "grade": _grade(score),
        "grade_label": _grade_label(score) if has_data else "",
        "has_data": has_data,
        "components": _component_rows(parts),
        "reason": explanation["reason"],
        "risk_reason": explanation["risk_reason"],
        "action": explanation["action"],
        "note_points": {
            "strength": _unique_points(strength_points),
            "risk": _unique_points(risk_points),
            "action": _unique_points(action_points),
        },
        "rule_matches": rule_matches,
        "active_rule_count": active_rule_count,
        "matched_rule_count": len(rule_matches),
        "rule_engine": {
            "status": rule_engine_run.status if rule_engine_run else "pending",
            "last_run_at": rule_engine_run.finished_at if rule_engine_run and rule_engine_run.finished_at else None,
            "error": rule_engine_run.error_message if rule_engine_run and rule_engine_run.status == "failed" else "",
        },
        "metrics": {
            "Gösterim": _fmt_number(totals["impressions"], 0),
            "Tıklama": _fmt_number(totals["clicks"], 0),
            "CTR": f"%{_fmt_number(totals['ctr'])}",
            "Harcama": f"{_fmt_number(totals['spend'])} TL",
            "CPA": f"{_fmt_number(totals['cpa'])} TL",
            "ROAS": f"{_fmt_number(totals['roas'])}x",
            "Frekans": _fmt_number(totals["frequency"]),
            "Dönüşüm": _fmt_number(totals["conversions"], 0),
        },
    }


@login_required
def ad_health_report_card(request):
    try:
        days = int(request.GET.get("gun", 30) or 30)
    except ValueError:
        days = 30
    if days not in [7, 14, 30, 60, 90]:
        days = 30
    ad_id = request.GET.get("ad", "").strip()
    agency_scope = get_agency_scope(request)
    context = _build_context(request, ad_id, days)
    context["agency_scope"] = agency_scope

    selected_ad = context.get("selected_ad")
    engine = context.get("rule_engine") or {}
    last_run_at = engine.get("last_run_at")
    is_stale = not last_run_at or last_run_at < timezone.now() - timedelta(minutes=15)
    should_queue = bool(selected_ad and selected_ad.platform_account_id) and engine.get("status") != "running" and (is_stale or engine.get("status") == "failed")
    queue_guard = ("user", request.user.id, "account", selected_ad.platform_account_id if selected_ad else "none")
    if should_queue and not CacheService.get("health_card_rule_scan", *queue_guard):
        try:
            task = generate_octo_tasks.apply_async(
                kwargs={
                    "user_id": selected_ad.user_id,
                    "account_id": selected_ad.platform_account_id,
                    "trigger": "manual",
                    "days": min(days, 30),
                },
                queue="ai",
            )
            context["rule_scan_queued"] = True
            context["rule_scan_task_id"] = task.id
            CacheService.set("health_card_rule_scan", *queue_guard, value=True, timeout=90)
        except Exception as exc:
            context["rule_scan_error"] = str(exc)
    if request.GET.get("format") == "pdf" and not context.get("empty"):
        pdf = _build_report_card_pdf(context)
        filename = f"reklam-saglik-karnesi-{context['selected_ad'].id}.pdf"
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        return response

    return render(request, "reports/ad_health_report_card.html", context)
