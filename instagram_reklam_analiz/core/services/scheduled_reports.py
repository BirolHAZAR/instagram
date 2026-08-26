from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db.models import Max, Sum
from django.template.loader import render_to_string
from django.utils.text import slugify
from django.utils import timezone

from core.models import AdMetricHistory, Campaign, CampaignMetricHistory, ScheduledReport
from core.services.agency_branding import get_report_branding
from core.templatetags.tr_numbers import tr_int, tr_money, tr_percent, tr_roas


PERIOD_DAYS = {
    "daily": 1,
    "weekly": 7,
    "biweekly": 15,
    "monthly": 30,
}


def _unique_recipient_emails(emails):
    unique = []
    seen = set()
    for raw_email in emails or []:
        email = str(raw_email).strip()
        key = email.casefold()
        if not email or key in seen:
            continue
        seen.add(key)
        unique.append(email)
    return unique


def next_run_for(report, from_time=None):
    base = from_time or timezone.now()
    days = PERIOD_DAYS.get(report.frequency, 7)
    candidate = (base + timedelta(days=days)).replace(
        hour=int(report.send_hour or 9),
        minute=0,
        second=0,
        microsecond=0,
    )
    if candidate <= base:
        candidate += timedelta(days=1)
    return candidate


def ensure_next_run(report):
    if not report.next_run_at:
        report.next_run_at = timezone.now().replace(
            hour=int(report.send_hour or 9),
            minute=0,
            second=0,
            microsecond=0,
        )
        if report.next_run_at <= timezone.now():
            report.next_run_at = next_run_for(report)
        report.save(update_fields=["next_run_at", "updated_at"])
    return report.next_run_at


def _period(report):
    days = PERIOD_DAYS.get(report.frequency, 7)
    end_date = timezone.localdate()
    start_date = end_date - timedelta(days=days - 1)
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    return start_date, end_date, previous_start, previous_end


def _zero_if_none(value):
    return value or Decimal("0")


def _aggregate(metrics):
    totals = metrics.aggregate(
        spend=Sum("spend"),
        impressions=Sum("impressions"),
        clicks=Sum("clicks"),
        conversions=Sum("conversions"),
        conversion_value=Sum("conversion_value"),
    )
    spend = _zero_if_none(totals["spend"])
    impressions = int(totals["impressions"] or 0)
    clicks = int(totals["clicks"] or 0)
    conversions = _zero_if_none(totals["conversions"])
    conversion_value = _zero_if_none(totals["conversion_value"])
    ctr = (Decimal(clicks) / Decimal(impressions) * 100) if impressions else Decimal("0")
    cpc = (spend / Decimal(clicks)) if clicks else Decimal("0")
    cpm = (spend / Decimal(impressions) * 1000) if impressions else Decimal("0")
    roas = (conversion_value / spend) if spend else Decimal("0")
    return {
        "spend": spend,
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions,
        "conversion_value": conversion_value,
        "ctr": ctr,
        "cpc": cpc,
        "cpm": cpm,
        "roas": roas,
    }


def _metric_queryset(model, report, start_date, end_date, campaigns=None):
    if model is CampaignMetricHistory:
        if campaigns:
            return model.objects.filter(campaign__in=campaigns, date__range=(start_date, end_date))
        filters = {"campaign__user": report.user, "date__range": (start_date, end_date)}
        if report.agency_client_id:
            filters = {"campaign__platform_account__agency_client": report.agency_client, "date__range": (start_date, end_date)}
        return model.objects.filter(**filters)

    if campaigns:
        return model.objects.filter(
            ad__campaign__in=campaigns,
            ad__source_type="OWN",
            date__range=(start_date, end_date),
        )
    filters = {"ad__user": report.user, "ad__source_type": "OWN", "date__range": (start_date, end_date)}
    if report.agency_client_id:
        filters = {
            "ad__campaign__platform_account__agency_client": report.agency_client,
            "ad__source_type": "OWN",
            "date__range": (start_date, end_date),
        }
    return model.objects.filter(**filters)


def _latest_metric_date(report, campaigns=None):
    if campaigns:
        campaign_qs = CampaignMetricHistory.objects.filter(campaign__in=campaigns)
        ad_qs = AdMetricHistory.objects.filter(ad__campaign__in=campaigns, ad__source_type="OWN")
    else:
        if report.agency_client_id:
            campaign_qs = CampaignMetricHistory.objects.filter(campaign__platform_account__agency_client=report.agency_client)
            ad_qs = AdMetricHistory.objects.filter(ad__campaign__platform_account__agency_client=report.agency_client, ad__source_type="OWN")
        else:
            campaign_qs = CampaignMetricHistory.objects.filter(campaign__user=report.user)
            ad_qs = AdMetricHistory.objects.filter(ad__user=report.user, ad__source_type="OWN")

    campaign_latest = campaign_qs.aggregate(value=Max("date"))["value"]
    ad_latest = ad_qs.aggregate(value=Max("date"))["value"]
    dates = [date for date in [campaign_latest, ad_latest] if date]
    return max(dates) if dates else None


def _campaign_budget(campaign, days):
    lifetime_budget = _zero_if_none(getattr(campaign, "lifetime_budget", None))
    daily_budget = _zero_if_none(getattr(campaign, "daily_budget", None))
    if lifetime_budget:
        return lifetime_budget
    if daily_budget:
        return daily_budget * Decimal(days or 1)
    return Decimal("0")


def _budget_summary(campaigns, days, spend):
    total_budget = sum((_campaign_budget(campaign, days) for campaign in campaigns), Decimal("0"))
    remaining_budget = max(Decimal("0"), total_budget - Decimal(spend or 0))
    usage_rate = (Decimal(spend or 0) / total_budget * 100) if total_budget else Decimal("0")
    return {
        "total": total_budget,
        "remaining": remaining_budget,
        "usage_rate": usage_rate,
        "campaign_count": len(campaigns),
    }


def _change(current, previous):
    current = Decimal(current or 0)
    previous = Decimal(previous or 0)
    if previous == 0:
        return None
    return (current - previous) / previous * 100


def _recommendations(current, previous):
    items = []
    ctr_change = _change(current["ctr"], previous["ctr"])
    cpc_change = _change(current["cpc"], previous["cpc"])
    spend_change = _change(current["spend"], previous["spend"])
    conv_change = _change(current["conversions"], previous["conversions"])

    if ctr_change is not None and ctr_change < -15:
        items.append("CTR belirgin şekilde düşmüş; düşük performanslı kreatifleri yenilemeyi değerlendirin.")
    if cpc_change is not None and cpc_change > 20:
        items.append("Tıklama maliyeti yükselmiş; hedef kitle, teklif ve yerleşim kırılımlarını kontrol edin.")
    if spend_change is not None and spend_change > 25 and (conv_change is None or conv_change <= 0):
        items.append("Harcama artarken dönüşüm aynı hızda artmamış; bütçe dağılımını yeniden dengeleyin.")
    if current["impressions"] > 0 and current["clicks"] == 0:
        items.append("Gösterim var ancak tıklama yok; reklam mesajı ve CTA tarafında hızlı revizyon önerilir.")
    if not items:
        items.append("Kritik sapma görünmüyor; en iyi performans veren reklamların bütçe payını kontrollü artırabilirsiniz.")
    return items


def build_report_context(report):
    start_date, end_date, previous_start, previous_end = _period(report)
    days = (end_date - start_date).days + 1
    campaigns = list(
        report.campaigns.select_related(
            "platform_account__agency_client__organization"
        ).all()
    )
    client_ids = {
        campaign.platform_account.agency_client_id
        for campaign in campaigns
        if campaign.platform_account_id and campaign.platform_account.agency_client_id
    }
    agency_client = report.agency_client
    if agency_client is None and len(client_ids) == 1:
        agency_client = next(
            campaign.platform_account.agency_client
            for campaign in campaigns
            if campaign.platform_account_id and campaign.platform_account.agency_client_id
        )
    branding = get_report_branding(report.user, agency_client=agency_client)

    campaign_metrics = _metric_queryset(CampaignMetricHistory, report, start_date, end_date, campaigns)
    previous_campaign_metrics = _metric_queryset(CampaignMetricHistory, report, previous_start, previous_end, campaigns)
    ad_metrics = _metric_queryset(AdMetricHistory, report, start_date, end_date, campaigns)
    previous_ad_metrics = _metric_queryset(AdMetricHistory, report, previous_start, previous_end, campaigns)

    if not campaign_metrics.exists() and not ad_metrics.exists():
        latest_metric_date = _latest_metric_date(report, campaigns)
        if latest_metric_date and latest_metric_date < end_date:
            end_date = latest_metric_date
            start_date = end_date - timedelta(days=days - 1)
            previous_end = start_date - timedelta(days=1)
            previous_start = previous_end - timedelta(days=days - 1)
            campaign_metrics = _metric_queryset(CampaignMetricHistory, report, start_date, end_date, campaigns)
            previous_campaign_metrics = _metric_queryset(CampaignMetricHistory, report, previous_start, previous_end, campaigns)
            ad_metrics = _metric_queryset(AdMetricHistory, report, start_date, end_date, campaigns)
            previous_ad_metrics = _metric_queryset(AdMetricHistory, report, previous_start, previous_end, campaigns)

    has_campaign_metrics = campaign_metrics.exists()
    metrics = campaign_metrics if has_campaign_metrics else ad_metrics
    previous_metrics = previous_campaign_metrics if has_campaign_metrics else previous_ad_metrics
    totals = _aggregate(metrics)
    previous_totals = _aggregate(previous_metrics)

    budget_campaigns = campaigns
    if not budget_campaigns:
        metric_campaign_ids = campaign_metrics.values_list("campaign_id", flat=True).distinct()
        if metric_campaign_ids:
            budget_campaigns = list(Campaign.objects.filter(id__in=metric_campaign_ids))
        else:
            budget_filters = {"user": report.user, "ads__source_type": "OWN"}
            if report.agency_client_id:
                budget_filters = {"platform_account__agency_client": report.agency_client, "ads__source_type": "OWN"}
            budget_campaigns = list(Campaign.objects.filter(**budget_filters).distinct())
    budget = _budget_summary(budget_campaigns, days, totals["spend"])

    top_ads = (
        ad_metrics.values("ad_id", "ad__name", "ad__headline")
        .annotate(
            spend=Sum("spend"),
            impressions=Sum("impressions"),
            clicks=Sum("clicks"),
            conversions=Sum("conversions"),
        )
        .order_by("-clicks", "-conversions")[:8]
    )

    campaign_rows = (
        campaign_metrics.values(
            "campaign_id",
            "campaign__name",
            "campaign__daily_budget",
            "campaign__lifetime_budget",
        )
        .annotate(
            spend=Sum("spend"),
            impressions=Sum("impressions"),
            clicks=Sum("clicks"),
            conversions=Sum("conversions"),
            conversion_value=Sum("conversion_value"),
        )
        .order_by("-spend")
    )

    campaign_rows = list(campaign_rows)
    for row in campaign_rows:
        impressions = int(row.get("impressions") or 0)
        clicks = int(row.get("clicks") or 0)
        spend = _zero_if_none(row.get("spend"))
        conversions = _zero_if_none(row.get("conversions"))
        conversion_value = _zero_if_none(row.get("conversion_value"))
        row["budget"] = _campaign_budget(
            Campaign(
                daily_budget=row.get("campaign__daily_budget"),
                lifetime_budget=row.get("campaign__lifetime_budget"),
            ),
            days,
        )
        row["ctr"] = (Decimal(clicks) / Decimal(impressions) * 100) if impressions else Decimal("0")
        row["cpc"] = (spend / Decimal(clicks)) if clicks else Decimal("0")
        row["roas"] = (conversion_value / spend) if spend else Decimal("0")
        row["conversions"] = conversions

    if not campaign_rows and budget_campaigns:
        for campaign in budget_campaigns:
            campaign_rows.append({
                "campaign_id": campaign.id,
                "campaign__name": campaign.name,
                "campaign__daily_budget": campaign.daily_budget,
                "campaign__lifetime_budget": campaign.lifetime_budget,
                "budget": _campaign_budget(campaign, days),
                "spend": Decimal("0"),
                "impressions": 0,
                "clicks": 0,
                "conversions": Decimal("0"),
                "conversion_value": Decimal("0"),
                "ctr": Decimal("0"),
                "cpc": Decimal("0"),
                "roas": Decimal("0"),
            })

    return {
        "report": report,
        "branding": branding,
        "user": report.user,
        "start_date": start_date,
        "end_date": end_date,
        "days": days,
        "totals": totals,
        "budget": budget,
        "previous_totals": previous_totals,
        "changes": {key: _change(totals[key], previous_totals[key]) for key in ("spend", "clicks", "ctr", "cpc", "conversions")},
        "campaign_rows": campaign_rows,
        "top_ads": list(top_ads),
        "metric_source": "campaign" if has_campaign_metrics else "ad",
        "recommendations": _recommendations(totals, previous_totals),
    }


def scheduled_report_filename(report, extension="pdf"):
    name = slugify(report.name or "otomatik-rapor") or "otomatik-rapor"
    return f"{name}-{timezone.localdate().strftime('%Y%m%d')}.{extension}"


def render_scheduled_report_html(report, context=None):
    context = context or build_report_context(report)
    return render_to_string("emails/scheduled_report.html", context)


def _pdf_font_paths():
    candidates = [
        (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
        (Path("C:/Windows/Fonts/segoeui.ttf"), Path("C:/Windows/Fonts/segoeuib.ttf")),
    ]
    for regular, bold in candidates:
        if regular.exists() and bold.exists():
            return str(regular), str(bold)
    return None, None


def _build_scheduled_report_pdf_reportlab(context):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    regular_path, bold_path = _pdf_font_paths()
    font_name = "Helvetica"
    bold_font_name = "Helvetica-Bold"
    if regular_path and bold_path:
        if "ScheduledReport-Regular" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("ScheduledReport-Regular", regular_path))
        if "ScheduledReport-Bold" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("ScheduledReport-Bold", bold_path))
        font_name = "ScheduledReport-Regular"
        bold_font_name = "ScheduledReport-Bold"

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "SRTitle",
        parent=styles["Title"],
        fontName=bold_font_name,
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
        alignment=TA_LEFT,
        spaceAfter=6,
    )
    muted = ParagraphStyle(
        "SRMuted",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#64748b"),
    )
    heading = ParagraphStyle(
        "SRHeading",
        parent=styles["Heading2"],
        fontName=bold_font_name,
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#111827"),
        spaceAfter=8,
    )
    normal = ParagraphStyle(
        "SRNormal",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#111827"),
    )
    label = ParagraphStyle(
        "SRMetricLabel",
        parent=normal,
        fontName=font_name,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#64748b"),
        alignment=TA_CENTER,
    )
    value = ParagraphStyle(
        "SRMetricValue",
        parent=normal,
        fontName=bold_font_name,
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#111827"),
        alignment=TA_CENTER,
    )

    def p(text, style=normal):
        return Paragraph(str(text or ""), style)

    def panel_table(content, padding=12):
        table = Table([[content]], colWidths=[170 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#e5e7eb")),
            ("LEFTPADDING", (0, 0), (-1, -1), padding),
            ("RIGHTPADDING", (0, 0), (-1, -1), padding),
            ("TOPPADDING", (0, 0), (-1, -1), padding),
            ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
        ]))
        return table

    report = context["report"]
    branding = context.get("branding")
    totals = context["totals"]
    budget = context["budget"]
    header_content = []
    if branding and branding.logo_path:
        try:
            logo = Image(branding.logo_path)
            logo._restrictSize(42 * mm, 15 * mm)
            header_content.extend([logo, Spacer(1, 4)])
        except Exception:
            pass
    if branding and branding.brand_name:
        header_content.append(p(branding.brand_name, muted))
    header_content.extend([
        p(report.name, title),
        p(f"{context['start_date'].strftime('%d.%m.%Y')} - {context['end_date'].strftime('%d.%m.%Y')} performans özeti", muted),
    ])
    story = [
        panel_table(header_content),
        Spacer(1, 8),
    ]

    metric_cells = [
        ("Bütçe", tr_money(budget["total"])),
        ("Harcama", tr_money(totals["spend"])),
        ("Kalan Bütçe", tr_money(budget["remaining"])),
        ("Gösterim", tr_int(totals["impressions"])),
        ("Tıklama", tr_int(totals["clicks"])),
        ("CTR", tr_percent(totals["ctr"])),
        ("CPC", tr_money(totals["cpc"])),
        ("Dönüşüm", tr_int(totals["conversions"])),
        ("Bütçe Kullanımı", tr_percent(budget["usage_rate"])),
    ]
    metric_rows = []
    for index in range(0, len(metric_cells), 3):
        row = []
        for name, amount in metric_cells[index:index + 3]:
            row.append([p(name, label), p(amount, value)])
        metric_rows.append(row)
    metrics_table = Table(metric_rows, colWidths=[52 * mm, 52 * mm, 52 * mm], rowHeights=24 * mm)
    metrics_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#e5e7eb")),
        ("INNERGRID", (0, 0), (-1, -1), 0.8, colors.HexColor("#e5e7eb")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
    ]))
    story += [panel_table([p("Özet Metrikler", heading), metrics_table]), Spacer(1, 8)]

    if getattr(report, "include_rule_recommendations", False):
        items = [p(f"• {item}", normal) for item in context.get("recommendations", [])]
        story += [panel_table([p("Kural Bazlı Öneriler", heading), *items]), Spacer(1, 8)]

    if getattr(report, "include_campaign_summary", False) and context.get("campaign_rows"):
        table_heading = ParagraphStyle(
            "SRTableHeading",
            parent=heading,
            fontSize=6.5,
            leading=8,
            spaceAfter=0,
        )
        table_cell = ParagraphStyle(
            "SRTableCell",
            parent=normal,
            fontSize=6.2,
            leading=7.5,
        )
        data = [[
            p("Kampanya", table_heading),
            p("Bütçe", table_heading),
            p("Harcama", table_heading),
            p("Gösterim", table_heading),
            p("Tıklama", table_heading),
            p("CTR", table_heading),
            p("CPC", table_heading),
            p("Dönüşüm", table_heading),
            p("ROAS", table_heading),
        ]]
        for row in context["campaign_rows"]:
            data.append([
                p(row.get("campaign__name") or "Kampanyasız", table_cell),
                tr_money(row.get("budget")),
                tr_money(row.get("spend")),
                tr_int(row.get("impressions")),
                tr_int(row.get("clicks")),
                tr_percent(row.get("ctr")),
                tr_money(row.get("cpc")),
                tr_int(row.get("conversions")),
                tr_roas(row.get("roas")),
            ])
        table = Table(data, colWidths=[52 * mm, 21 * mm, 21 * mm, 17 * mm, 15 * mm, 13 * mm, 17 * mm, 15 * mm, 11 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
            ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#e5e7eb")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTSIZE", (1, 1), (-1, -1), 6.2),
            ("ALIGN", (1, 1), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story += [p("Kampanya Özeti", heading), table, Spacer(1, 8)]

    if getattr(report, "include_ad_performance", False) and context.get("top_ads"):
        ad_heading = ParagraphStyle("SRAdTableHeading", parent=heading, fontSize=7, leading=8, spaceAfter=0)
        ad_name_cell = ParagraphStyle("SRAdNameCell", parent=normal, fontSize=6.5, leading=7.5)
        ad_metric_cell = ParagraphStyle("SRAdMetricCell", parent=normal, fontSize=6.2, leading=7.2, alignment=1)
        data = [[p("Reklam", heading), p("Harcama", heading), p("Tıklama", heading), p("Dönüşüm", heading)]]
        data[0] = [
            p("Reklam", ad_heading),
            p("Harcama", ad_heading),
            p("T\u0131klama", ad_heading),
            p("D\u00f6n\u00fc\u015f\u00fcm", ad_heading),
        ]
        for row in context["top_ads"]:
            data.append([
                p(row.get("ad__name") or row.get("ad__headline") or "Reklam", ad_name_cell),
                p(tr_money(row.get("spend")), ad_metric_cell),
                p(tr_int(row.get("clicks")), ad_metric_cell),
                p(tr_int(row.get("conversions")), ad_metric_cell),
            ])
        table = Table(data, colWidths=[104 * mm, 27 * mm, 21 * mm, 22 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
            ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#e5e7eb")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story += [p("Öne Çıkan Reklamlar", heading), table, Spacer(1, 8)]

    story.append(p("Bu rapor ReklamAnaliz.net otomatik raporlama sistemi tarafından oluşturuldu.", muted))

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    doc.build(story)
    return buffer.getvalue()


def build_scheduled_report_pdf(report, context=None):
    context = context or build_report_context(report)
    return _build_scheduled_report_pdf_reportlab(context)


def send_scheduled_report(report):
    recipients = _unique_recipient_emails(report.recipient_emails)
    if not recipients:
        raise ValueError("Otomatik rapor için geçerli bir alıcı e-posta bulunamadı.")
    context = build_report_context(report)
    subject = f"{report.name} - {context['start_date'].strftime('%d.%m.%Y')} / {context['end_date'].strftime('%d.%m.%Y')}"
    html = render_scheduled_report_html(report, context)
    text = render_to_string("emails/scheduled_report.txt", context)
    pdf = build_scheduled_report_pdf(report, context)

    connection = get_connection(
        backend=settings.EMAIL_BACKEND,
        host=settings.EMAIL_HOST,
        port=settings.EMAIL_PORT,
        username=settings.EMAIL_HOST_USER,
        password=settings.EMAIL_HOST_PASSWORD,
        use_tls=settings.EMAIL_USE_TLS,
        use_ssl=settings.EMAIL_USE_SSL,
        timeout=getattr(settings, "EMAIL_TIMEOUT", 30),
    )
    message = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=settings.REPORTS_FROM_EMAIL,
        to=recipients,
        connection=connection,
    )
    message.attach_alternative(html, "text/html")
    message.attach(scheduled_report_filename(report), pdf, "application/pdf")
    sent = message.send(fail_silently=False)

    now = timezone.now()
    report.last_sent_at = now
    report.next_run_at = next_run_for(report, now)
    report.last_error = ""
    report.save(update_fields=["last_sent_at", "next_run_at", "last_error", "updated_at"])
    return {"sent": sent, "recipients": recipients, "next_run_at": report.next_run_at.isoformat()}


def due_reports(now=None):
    current = now or timezone.now()
    return ScheduledReport.objects.filter(is_active=True, next_run_at__lte=current).select_related("user")
