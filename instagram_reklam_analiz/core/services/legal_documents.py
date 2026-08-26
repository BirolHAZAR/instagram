import hashlib
import logging
import re
from html import unescape
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.html import escape, strip_tags
from django.utils.safestring import mark_safe

from core.models import LegalAcceptance, LegalDocument, LegalSiteSettings


logger = logging.getLogger(__name__)

PURCHASE_LEGAL_SLUGS = (
    "mesafeli-satis-sozlesmesi",
    "on-bilgilendirme-formu",
    "uyelik-sozlesmesi",
    "kullanim-kosullari",
    "iptal-ve-iade-politikasi",
)

ACCEPTANCE_STATEMENT = (
    "Mesafeli Satış Sözleşmesi, Ön Bilgilendirme Formu, Üyelik Sözleşmesi, "
    "Kullanım Koşulları ile İptal ve İade Politikasını okudum ve kabul ediyorum."
)


def purchase_legal_documents():
    documents = LegalDocument.objects.filter(
        slug__in=PURCHASE_LEGAL_SLUGS,
        status=LegalDocument.STATUS_PUBLISHED,
    )
    by_slug = {document.slug: document for document in documents}
    return [by_slug[slug] for slug in PURCHASE_LEGAL_SLUGS if slug in by_slug]


def purchase_documents_ready():
    return len(purchase_legal_documents()) == len(PURCHASE_LEGAL_SLUGS)


def _effective_date(document):
    value = document.effective_date or document.published_at or document.updated_at
    return value.date() if hasattr(value, "date") else value


def legal_token_values(site_settings, document):
    effective_date = _effective_date(document)
    return {
        "COMPANY_NAME": site_settings.company_name,
        "BRAND_NAME": site_settings.brand_name,
        "ADDRESS": site_settings.address,
        "TAX_OFFICE": site_settings.tax_office,
        "TAX_NUMBER": site_settings.tax_number,
        "MERSIS_NUMBER": site_settings.mersis_number,
        "KEP_ADDRESS": site_settings.kep_address,
        "SUPPORT_EMAIL": site_settings.support_email,
        "KVKK_EMAIL": site_settings.kvkk_email,
        "PHONE": site_settings.phone,
        "SLA_TARGET": str(site_settings.sla_target).replace(".", ","),
        "EFFECTIVE_DATE": date_format(effective_date, "d F Y") if effective_date else "",
    }


def render_legal_content(document, site_settings, *, safe=False):
    content = document.content
    for token, value in legal_token_values(site_settings, document).items():
        content = content.replace(f"[[{token}]]", escape(value or "—"))
    return mark_safe(content) if safe else content


def build_document_snapshot(document, site_settings=None):
    site_settings = site_settings or LegalSiteSettings.load()
    rendered_content = render_legal_content(document, site_settings)
    return {
        "document_id": document.id,
        "slug": document.slug,
        "title": document.title,
        "version": document.version,
        "effective_date": _effective_date(document).isoformat() if _effective_date(document) else "",
        "summary": document.summary,
        "content": rendered_content,
        "content_sha256": hashlib.sha256(rendered_content.encode("utf-8")).hexdigest(),
    }


def build_purchase_snapshots():
    documents = purchase_legal_documents()
    if len(documents) != len(PURCHASE_LEGAL_SLUGS):
        raise ValueError("Satın alma için zorunlu hukuki metinlerin tamamı yayında değil.")
    site_settings = LegalSiteSettings.load()
    return [build_document_snapshot(document, site_settings) for document in documents]


def record_purchase_acceptance(request, payment, *, immediate_service_consent):
    return LegalAcceptance.objects.create(
        user=request.user,
        payment=payment,
        document_snapshots=build_purchase_snapshots(),
        acceptance_statement=ACCEPTANCE_STATEMENT,
        immediate_service_consent=bool(immediate_service_consent),
        ip_address=request.META.get("REMOTE_ADDR") or None,
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:500],
        email_recipient=(getattr(payment.billing_info, "email", "") or payment.user.email or "").strip(),
    )


def _register_pdf_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = {
        "regular": (
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ),
        "bold": (
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ),
    }
    regular_path = next((path for path in candidates["regular"] if path.exists()), None)
    bold_path = next((path for path in candidates["bold"] if path.exists()), None)
    if regular_path and "LegalSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("LegalSans", str(regular_path)))
    if bold_path and "LegalSans-Bold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("LegalSans-Bold", str(bold_path)))
    return (
        "LegalSans" if regular_path else "Helvetica",
        "LegalSans-Bold" if bold_path else "Helvetica-Bold",
    )


def _html_blocks(content):
    pattern = re.compile(r"<(h2|p|li)(?:\s[^>]*)?>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
    blocks = []
    for tag, raw in pattern.findall(content):
        text = unescape(strip_tags(raw)).strip()
        if text:
            blocks.append((tag.lower(), text))
    return blocks


def build_legal_pdf(snapshot, *, payment_reference=""):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer

    regular_font, bold_font = _register_pdf_fonts()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        topMargin=25 * mm,
        bottomMargin=22 * mm,
        title=snapshot["title"],
        author="ReklamAnaliz.net",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "LegalTitle",
        parent=styles["Title"],
        fontName=bold_font,
        fontSize=20,
        leading=25,
        textColor=colors.HexColor("#111827"),
        alignment=TA_CENTER,
        spaceAfter=9 * mm,
    )
    meta_style = ParagraphStyle(
        "LegalMeta",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#64748b"),
        alignment=TA_CENTER,
        spaceAfter=5 * mm,
    )
    heading_style = ParagraphStyle(
        "LegalHeading",
        parent=styles["Heading2"],
        fontName=bold_font,
        fontSize=12.5,
        leading=16,
        textColor=colors.HexColor("#087f8c"),
        spaceBefore=4 * mm,
        spaceAfter=2 * mm,
    )
    body_style = ParagraphStyle(
        "LegalBody",
        parent=styles["BodyText"],
        fontName=regular_font,
        fontSize=9.5,
        leading=15,
        textColor=colors.HexColor("#293544"),
        spaceAfter=3 * mm,
    )
    bullet_style = ParagraphStyle("LegalBullet", parent=body_style, leftIndent=5 * mm, firstLineIndent=-3 * mm)

    story = [
        Paragraph(escape(snapshot["title"]), title_style),
        Paragraph(
            f"Sürüm {escape(snapshot['version'])} · Yürürlük {escape(snapshot['effective_date'] or '—')}"
            + (f" · Ödeme referansı {escape(str(payment_reference))}" if payment_reference else ""),
            meta_style,
        ),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#dbe4ee"), spaceAfter=5 * mm),
    ]
    if snapshot.get("summary"):
        story.extend([Paragraph(f"<b>{escape(snapshot['summary'])}</b>", body_style), Spacer(1, 2 * mm)])
    for tag, text in _html_blocks(snapshot["content"]):
        safe_text = escape(text)
        if tag == "h2":
            story.append(Paragraph(safe_text, heading_style))
        elif tag == "li":
            story.append(Paragraph(f"• {safe_text}", bullet_style))
        else:
            story.append(Paragraph(safe_text, body_style))

    def draw_page(canvas, doc):
        canvas.saveState()
        width, height = A4
        canvas.setFillColor(colors.HexColor("#087f8c"))
        canvas.setFont(bold_font, 9)
        canvas.drawString(22 * mm, height - 13 * mm, "ReklamAnaliz.net")
        canvas.setFillColor(colors.HexColor("#7b8797"))
        canvas.setFont(regular_font, 7.5)
        canvas.drawRightString(width - 22 * mm, height - 13 * mm, "HZR Yazılım Danışmanlık Dijital Paz. LTD ŞTİ")
        canvas.setStrokeColor(colors.HexColor("#dbe4ee"))
        canvas.line(22 * mm, 15 * mm, width - 22 * mm, 15 * mm)
        canvas.setFillColor(colors.HexColor("#7b8797"))
        canvas.drawString(22 * mm, 9 * mm, "www.reklamanaliz.net · info@reklamanaliz.net")
        canvas.drawRightString(width - 22 * mm, 9 * mm, f"Sayfa {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    return buffer.getvalue()


def payment_item_label(payment):
    if payment.plan_id:
        return f"{payment.plan.display_name} Paketi"
    if payment.ai_credit_package_id:
        return payment.ai_credit_package.display_name
    if payment.product_research_package_id:
        return payment.product_research_package.display_name
    return "ReklamAnaliz.net hizmeti"


def _send_email(*, recipient, subject, context, snapshots, payment_reference=""):
    text_body = render_to_string("emails/purchase_legal.txt", context)
    html_body = render_to_string("emails/purchase_legal.html", context)
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    message.attach_alternative(html_body, "text/html")
    for index, snapshot in enumerate(snapshots, start=1):
        filename = f"{index:02d}-{snapshot['slug']}-v{snapshot['version']}.pdf"
        message.attach(filename, build_legal_pdf(snapshot, payment_reference=payment_reference), "application/pdf")
    return message.send(fail_silently=False)


def send_purchase_legal_email(acceptance_id):
    acceptance = LegalAcceptance.objects.select_related(
        "payment", "payment__plan", "payment__ai_credit_package", "payment__product_research_package", "payment__billing_info"
    ).get(pk=acceptance_id)
    payment = acceptance.payment
    recipient = acceptance.email_recipient or payment.user.email
    context = {
        "is_sample": False,
        "recipient_name": payment.user.get_full_name() or payment.user.username,
        "item_name": payment_item_label(payment),
        "amount": payment.amount,
        "payment_method": payment.get_payment_method_display(),
        "payment_status": payment.get_status_display(),
        "payment_reference": payment.id,
        "accepted_at": acceptance.accepted_at,
        "documents": acceptance.document_snapshots,
    }
    try:
        sent = _send_email(
            recipient=recipient,
            subject=f"Ödeme ve sözleşme belgeleriniz - {context['item_name']}",
            context=context,
            snapshots=acceptance.document_snapshots,
            payment_reference=payment.id,
        )
        acceptance.email_sent_at = timezone.now()
        acceptance.email_error = ""
        acceptance.save(update_fields=("email_sent_at", "email_error"))
        return sent
    except Exception as exc:
        acceptance.email_error = str(exc)[:2000]
        acceptance.save(update_fields=("email_error",))
        raise


def queue_purchase_legal_email(acceptance):
    def deliver():
        try:
            send_purchase_legal_email(acceptance.pk)
        except Exception:
            logger.exception("Sözleşme e-postası gönderilemedi acceptance_id=%s", acceptance.pk)

    transaction.on_commit(deliver)


def send_sample_purchase_legal_email(recipient):
    snapshots = build_purchase_snapshots()
    context = {
        "is_sample": True,
        "recipient_name": "Birol Bey",
        "item_name": "Örnek Silver Paketi",
        "amount": "1.200,00",
        "payment_method": "Kredi / Banka Kartı",
        "payment_status": "Örnek ödeme onayı",
        "payment_reference": "ORNEK-2026-001",
        "accepted_at": timezone.now(),
        "documents": snapshots,
    }
    return _send_email(
        recipient=recipient,
        subject="[ÖRNEK] Ödeme ve sözleşme belgeleriniz - ReklamAnaliz.net",
        context=context,
        snapshots=snapshots,
        payment_reference="ORNEK-2026-001",
    )
