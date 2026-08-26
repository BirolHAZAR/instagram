# core/views/payment.py
from core.ai_agents.error_manager import capture_errors
from io import BytesIO
from pathlib import Path
from datetime import timedelta
from decimal import Decimal
from html import unescape
import re
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.conf import settings
from django.core.mail import send_mail
from django.http import HttpResponse
from django.contrib.staticfiles import finders

from core.models import (
    MembershipPlan, UserSubscription, Invoice, Payment, 
    PaymentTransaction, BillingInfo, Organization, OrganizationMember, AICreditPackage, AICreditLedger,
    ProductResearchPackage
)
from core.forms import CheckoutForm
from core.services.entitlements import (
    add_ai_credits,
    grant_plan_ai_credits,
    get_active_subscription,
    migration_safe_membership_queryset,
    model_table_has_column,
    refresh_ai_credit_balance,
    visible_agency_plans,
    visible_ai_credit_packages,
    visible_business_plans,
)
from core.services.cache_service import CacheService
from core.services.product_research_credits import add_product_research_units
from core.services.payment_methods import save_payment_method_from_checkout
from core.services.legal_documents import queue_purchase_legal_email, record_purchase_acceptance
from core.services.referrals import (
    award_referral_for_subscription,
    ensure_user_referral_code,
    record_pending_referral,
    referral_checkout_benefits,
    referral_program_enabled,
    validate_referral_for_checkout,
)


PRICING_CACHE_TIMEOUT = 900
BANK_TRANSFER_NOTICE_EMAIL = "birolhazar@gmail.com"


def _invoice_text(value, fallback="-"):
    if value is None:
        return fallback
    text = str(value).strip()
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    text = "".join(char for char in text if char.isprintable())
    return text.strip() if text.strip() else fallback


def _format_invoice_money(value):
    value = Decimal(value or 0)
    return f"{value:,.2f}".replace(",", "TMP").replace(".", ",").replace("TMP", ".") + " TL"


def _format_invoice_datetime(value, fmt="%d.%m.%Y %H:%M"):
    if not value:
        return "-"
    try:
        return timezone.localtime(value).strftime(fmt)
    except Exception:
        return value.strftime(fmt)


def _format_invoice_date(value):
    return value.strftime("%d.%m.%Y") if value else "-"


def _register_invoice_pdf_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    regular_candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/ARIAL.TTF"),
    ]
    bold_candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/ARIALBD.TTF"),
    ]
    regular = next((path for path in regular_candidates if path.exists()), None)
    bold = next((path for path in bold_candidates if path.exists()), None)
    if regular:
        pdfmetrics.registerFont(TTFont("InvoiceArial", str(regular)))
    if bold:
        pdfmetrics.registerFont(TTFont("InvoiceArial-Bold", str(bold)))
    return ("InvoiceArial" if regular else "Helvetica", "InvoiceArial-Bold" if bold else "Helvetica-Bold")


def _draw_wrapped_text(canvas, text, x, y, max_width, font_name, font_size, leading=13, color=None):
    from reportlab.lib.colors import HexColor
    from reportlab.pdfbase.pdfmetrics import stringWidth

    if color:
        canvas.setFillColor(HexColor(color))
    canvas.setFont(font_name, font_size)
    words = _invoice_text(text).split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    for line in lines or ["-"]:
        canvas.drawString(x, y, line)
        y -= leading
    return y


def _build_invoice_pdf(invoice):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader

    regular_font, bold_font = _register_invoice_pdf_fonts()
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 14 * mm
    purple = colors.HexColor("#667eea")
    dark = colors.HexColor("#1f2937")
    muted = colors.HexColor("#64748b")
    light = colors.HexColor("#f8fafc")
    border = colors.HexColor("#e2e8f0")

    def text(x, y, value, size=10, font=regular_font, color=dark, right=False):
        pdf.setFillColor(color)
        pdf.setFont(font, size)
        value = _invoice_text(value)
        if right:
            pdf.drawRightString(x, y, value)
        else:
            pdf.drawString(x, y, value)

    logo_path = finders.find("images/logo2.png")
    y = height - margin
    if logo_path:
        img = ImageReader(logo_path)
        img_width, img_height = img.getSize()
        logo_width = 58 * mm
        logo_height = logo_width * img_height / img_width
        pdf.drawImage(img, margin, y - logo_height, width=logo_width, height=logo_height, preserveAspectRatio=True, mask="auto")
    else:
        text(margin, y - 16, "reklamanaliz.net", 22, bold_font, purple)
        logo_height = 16 * mm

    text(margin, y - logo_height - 10, "Reklamlarınızı veriyle güçlendirin", 9, regular_font, muted)
    text(margin, y - logo_height - 23, "www.reklamanaliz.com", 9, regular_font, muted)

    text(width - margin, y - 8, "FATURA", 25, bold_font, dark, right=True)
    text(width - margin, y - 26, f"#{invoice.invoice_number}", 11, bold_font, purple, right=True)
    y -= 54 * mm
    pdf.setStrokeColor(border)
    pdf.setLineWidth(1)
    pdf.line(margin, y, width - margin, y)
    y -= 10 * mm

    box_gap = 8 * mm
    box_width = (width - (2 * margin) - box_gap) / 2
    box_height = 44 * mm
    for x in (margin, margin + box_width + box_gap):
        pdf.setFillColor(light)
        pdf.setStrokeColor(border)
        pdf.roundRect(x, y - box_height, box_width, box_height, 8, fill=1, stroke=1)

    left_x = margin + 5 * mm
    right_x = margin + box_width + box_gap + 5 * mm
    top_y = y - 7 * mm
    text(left_x, top_y, "SATICI", 9, bold_font, muted)
    text(left_x, top_y - 14, "HZR Bilişim Yazılım San. Tic. LTD ŞTİ.", 10, bold_font, dark)
    seller_lines = [
        "Adres: Teknoloji Mah. İnovasyon Cad. No:42",
        "İstanbul / Türkiye",
        "Vergi Dairesi: İstanbul V.D.",
        "Vergi No: 1234567890",
        "Web: www.reklamanaliz.com",
        "E-posta: info@reklamanaliz.com",
    ]
    line_y = top_y - 28
    for item in seller_lines:
        text(left_x, line_y, item, 8.5, regular_font, dark)
        line_y -= 11

    billing = invoice.billing_info
    customer_name = (
        f"{billing.first_name} {billing.last_name}".strip()
        if billing else invoice.user.get_full_name() or invoice.user.username
    )
    text(right_x, top_y, "MÜŞTERİ", 9, bold_font, muted)
    text(right_x, top_y - 14, customer_name, 10, bold_font, dark)
    customer_lines = []
    if billing:
        if billing.company_name:
            customer_lines.append(billing.company_name)
        if billing.address:
            customer_lines.append(billing.address)
        if billing.city or billing.district:
            customer_lines.append(f"{billing.city or ''} / {billing.district or ''}".strip(" /"))
        if billing.tax_office:
            customer_lines.append(f"Vergi Dairesi: {billing.tax_office}")
        if billing.tax_number:
            customer_lines.append(f"Vergi No: {billing.tax_number}")
    customer_lines.append(f"E-posta: {invoice.user.email}")
    line_y = top_y - 28
    for item in customer_lines[:6]:
        text(right_x, line_y, item, 8.5, regular_font, dark)
        line_y -= 11

    y -= box_height + 13 * mm
    table_x = margin
    table_w = width - 2 * margin
    header_h = 10 * mm
    row_h = 22 * mm
    columns = [0, 90 * mm, 125 * mm, 160 * mm, table_w]
    pdf.setFillColor(colors.HexColor("#243041"))
    pdf.roundRect(table_x, y - header_h, table_w, header_h, 6, fill=1, stroke=0)
    text(table_x + 5 * mm, y - 7 * mm, "Açıklama", 9, bold_font, colors.white)
    text(table_x + columns[2] - 4 * mm, y - 7 * mm, "KDV Oranı", 9, bold_font, colors.white, right=True)
    text(table_x + columns[3] - 4 * mm, y - 7 * mm, "KDV Tutarı", 9, bold_font, colors.white, right=True)
    text(table_x + columns[4] - 5 * mm, y - 7 * mm, "Tutar", 9, bold_font, colors.white, right=True)
    y -= header_h
    pdf.setFillColor(colors.white)
    pdf.setStrokeColor(border)
    pdf.rect(table_x, y - row_h, table_w, row_h, fill=1, stroke=1)
    desc = _invoice_text(invoice.description, "Abonelik ücreti")
    text(table_x + 5 * mm, y - 9 * mm, desc, 9.5, bold_font, dark)
    package = invoice.subscription.plan.display_name + " Paketi" if invoice.subscription and invoice.subscription.plan else "Hizmet bedeli"
    text(table_x + 5 * mm, y - 17 * mm, package, 8.5, regular_font, muted)
    text(table_x + columns[2] - 4 * mm, y - 12 * mm, "%20", 9, regular_font, dark, right=True)
    text(table_x + columns[3] - 4 * mm, y - 12 * mm, _format_invoice_money(invoice.kdv_amount), 9, regular_font, dark, right=True)
    text(table_x + columns[4] - 5 * mm, y - 12 * mm, _format_invoice_money(invoice.amount), 9, regular_font, dark, right=True)
    y -= row_h + 8 * mm

    total_x = width - margin - 76 * mm
    total_w = 76 * mm
    total_h = 34 * mm
    pdf.setFillColor(purple)
    pdf.roundRect(total_x, y - total_h, total_w, total_h, 8, fill=1, stroke=0)
    text(total_x + 6 * mm, y - 9 * mm, "Ara Toplam", 9, regular_font, colors.white)
    text(total_x + total_w - 6 * mm, y - 9 * mm, _format_invoice_money(invoice.amount), 9, regular_font, colors.white, right=True)
    text(total_x + 6 * mm, y - 18 * mm, "KDV (%20)", 9, regular_font, colors.white)
    text(total_x + total_w - 6 * mm, y - 18 * mm, _format_invoice_money(invoice.kdv_amount), 9, regular_font, colors.white, right=True)
    pdf.setStrokeColor(colors.Color(1, 1, 1, alpha=0.35))
    pdf.line(total_x + 6 * mm, y - 23 * mm, total_x + total_w - 6 * mm, y - 23 * mm)
    text(total_x + 6 * mm, y - 30 * mm, "Toplam", 12, bold_font, colors.white)
    text(total_x + total_w - 6 * mm, y - 30 * mm, _format_invoice_money(invoice.total_amount), 12, bold_font, colors.white, right=True)

    meta_y = y - 8 * mm
    text(margin, meta_y, "Fatura Tarihi", 8.5, bold_font, muted)
    text(margin, meta_y - 11, _format_invoice_datetime(invoice.created_at), 9.5, bold_font, dark)
    text(margin, meta_y - 27, "Son Ödeme Tarihi", 8.5, bold_font, muted)
    text(margin, meta_y - 38, _format_invoice_date(invoice.due_date), 9.5, bold_font, dark)
    text(margin + 58 * mm, meta_y, "Ödeme Tarihi", 8.5, bold_font, muted)
    text(margin + 58 * mm, meta_y - 11, _format_invoice_datetime(invoice.payment_date), 9.5, bold_font, dark)
    method = "Kredi Kartı" if invoice.payment_method == "credit_card" else "Havale/EFT"
    text(margin + 58 * mm, meta_y - 27, "Ödeme Yöntemi", 8.5, bold_font, muted)
    text(margin + 58 * mm, meta_y - 38, method, 9.5, bold_font, dark)

    badge_w = 32 * mm
    badge_x = (width - badge_w) / 2
    badge_y = margin + 30 * mm
    pdf.setFillColor(colors.HexColor("#dcfce7") if invoice.status == "paid" else colors.HexColor("#fef3c7"))
    pdf.roundRect(badge_x, badge_y, badge_w, 9 * mm, 12, fill=1, stroke=0)
    pdf.setFillColor(colors.HexColor("#166534") if invoice.status == "paid" else colors.HexColor("#92400e"))
    pdf.setFont(bold_font, 8.5)
    pdf.drawCentredString(width / 2, badge_y + 3 * mm, "ÖDENDİ" if invoice.status == "paid" else _invoice_text(invoice.get_status_display()))

    footer_y = margin + 12 * mm
    pdf.setStrokeColor(border)
    pdf.line(margin, footer_y + 13, width - margin, footer_y + 13)
    pdf.setFillColor(muted)
    pdf.setFont(regular_font, 8.5)
    pdf.drawCentredString(width / 2, footer_y, "Bu fatura e-arşiv fatura olarak düzenlenmiştir. İmza ve kaşe gerektirmez.")
    pdf.drawCentredString(width / 2, footer_y - 11, "HZR Bilişim Yazılım San. Tic. LTD ŞTİ. | www.reklamanaliz.com | info@reklamanaliz.com")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _account_security_summary(user):
    summary = {
        "email_verified": False,
        "verified_email": "",
        "social_accounts_count": 0,
        "social_providers": [],
        "mfa_enabled": False,
        "mfa_methods_count": 0,
    }
    try:
        from allauth.account.models import EmailAddress

        verified_email = (
            EmailAddress.objects
            .filter(user=user, verified=True)
            .order_by("-primary", "email")
            .first()
        )
        summary["email_verified"] = verified_email is not None
        summary["verified_email"] = verified_email.email if verified_email else ""
    except Exception:
        pass

    try:
        from allauth.socialaccount.models import SocialAccount

        social_accounts = list(SocialAccount.objects.filter(user=user).order_by("provider"))
        summary["social_accounts_count"] = len(social_accounts)
        summary["social_providers"] = [account.get_provider().name for account in social_accounts]
    except Exception:
        pass

    try:
        from allauth.mfa.models import Authenticator

        methods_count = Authenticator.objects.filter(user=user).count()
        summary["mfa_methods_count"] = methods_count
        summary["mfa_enabled"] = methods_count > 0
    except Exception:
        pass

    return summary


def _bank_transfer_details(request):
    return {
        "sender_name": (request.POST.get("transfer_sender_name") or "").strip(),
        "bank_name": (request.POST.get("transfer_bank_name") or "").strip(),
        "transfer_date": (request.POST.get("transfer_date") or "").strip(),
        "receipt_reference": (request.POST.get("transfer_receipt_reference") or "").strip(),
        "note": (request.POST.get("transfer_note") or "").strip(),
    }


def _validate_bank_transfer_details(details):
    errors = []
    if not details["sender_name"]:
        errors.append("Havale bildiriminde gönderen adı zorunludur.")
    if not details["bank_name"]:
        errors.append("Havale bildiriminde banka adı zorunludur.")
    if not details["transfer_date"]:
        errors.append("Havale bildiriminde ödeme tarihi zorunludur.")
    return errors


def _billing_value(data, field, lower=False):
    value = (data.get(field) or "").strip()
    return value.lower() if lower else value


def _billing_info_values(cleaned_data):
    return {
        "customer_type": _billing_value(cleaned_data, "customer_type") or "individual",
        "first_name": _billing_value(cleaned_data, "first_name"),
        "last_name": _billing_value(cleaned_data, "last_name"),
        "email": _billing_value(cleaned_data, "email", lower=True),
        "phone": _billing_value(cleaned_data, "phone"),
        "company_name": _billing_value(cleaned_data, "company_name"),
        "tax_office": _billing_value(cleaned_data, "tax_office"),
        "tax_number": _billing_value(cleaned_data, "tax_number"),
        "tc_kimlik": _billing_value(cleaned_data, "tc_kimlik"),
        "address": _billing_value(cleaned_data, "address"),
        "city": _billing_value(cleaned_data, "city"),
        "district": _billing_value(cleaned_data, "district"),
        "zip_code": _billing_value(cleaned_data, "zip_code"),
    }


def _get_or_create_billing_info(user, cleaned_data):
    values = _billing_info_values(cleaned_data)
    identity_hash = BillingInfo.build_identity_hash(values)
    existing = (
        BillingInfo.objects
        .filter(user=user, identity_hash=identity_hash)
        .order_by("-created_at", "-id")
        .first()
    )
    if existing:
        return existing
    try:
        return BillingInfo.objects.create(user=user, **values)
    except IntegrityError:
        return BillingInfo.objects.get(user=user, identity_hash=identity_hash)


def _send_bank_transfer_notice(request, billing_info, payment, item_name, details):
    recipient = getattr(settings, "BANK_TRANSFER_NOTICE_EMAIL", BANK_TRANSFER_NOTICE_EMAIL)
    subject = f"Havale/EFT ödeme bildirimi - {item_name}"
    message = "\n".join([
        "Yeni havale/EFT ödeme bildirimi alındı.",
        "",
        f"Ürün/Paket: {item_name}",
        f"Toplam Tutar: {payment.amount} TL",
        f"Ödeme Kaydı: #{payment.id}",
        f"Kullanıcı: {request.user.get_username()} ({request.user.email})",
        "",
        "Fatura Bilgileri",
        f"Müşteri Tipi: {billing_info.get_customer_type_display()}",
        f"Ad Soyad: {billing_info.first_name} {billing_info.last_name}",
        f"E-posta: {billing_info.email}",
        f"Telefon: {billing_info.phone}",
        f"Şirket Unvanı: {billing_info.company_name or '-'}",
        f"Vergi Dairesi: {billing_info.tax_office or '-'}",
        f"Vergi No: {billing_info.tax_number or '-'}",
        f"TC Kimlik No: {billing_info.tc_kimlik or '-'}",
        f"Adres: {billing_info.address}",
        f"İl/İlçe: {billing_info.city} / {billing_info.district}",
        f"Posta Kodu: {billing_info.zip_code}",
        "",
        "Ödeme Bildirim Formu",
        f"Gönderen Adı: {details['sender_name']}",
        f"Banka: {details['bank_name']}",
        f"Ödeme Tarihi: {details['transfer_date']}",
        f"Dekont / İşlem No: {details['receipt_reference'] or '-'}",
        f"Not: {details['note'] or '-'}",
    ])
    send_mail(
        subject,
        message,
        getattr(settings, "DEFAULT_FROM_EMAIL", None),
        [recipient],
        fail_silently=False,
    )


def _payment_transaction(payment, note):
    reference = payment.transaction_id or f"demo-{timezone.now().strftime('%Y%m%d%H%M%S')}-{payment.id}"
    if not payment.transaction_id:
        payment.transaction_id = reference
        payment.save(update_fields=["transaction_id", "updated_at"])
    transaction_row, _ = PaymentTransaction.objects.get_or_create(
        payment=payment,
        transaction_type="payment",
        defaults={
            "user": payment.user,
            "amount": payment.amount,
            "status": "success",
            "reference_id": reference,
            "notes": note,
        },
    )
    return transaction_row


def _payment_invoice(payment, *, net_amount, description, is_paid, subscription=None, notes=None):
    invoice, _ = Invoice.objects.update_or_create(
        invoice_number=f"INV-{timezone.now().strftime('%Y%m%d')}-{payment.user_id}-{payment.id}",
        defaults={
            "user": payment.user,
            "subscription": subscription,
            "billing_info": payment.billing_info,
            "amount": net_amount,
            "kdv_amount": payment.kdv_amount,
            "total_amount": payment.amount,
            "payment_method": payment.payment_method,
            "is_paid": is_paid,
            "payment_date": timezone.now() if is_paid else None,
            "due_date": timezone.localdate() if is_paid else timezone.localdate() + timedelta(days=7),
            "status": "paid" if is_paid else "draft",
            "description": description,
            "notes": notes,
        },
    )
    return invoice


def _remember_payment_result(request, payment, *, title, detail, pending=False):
    request.session["payment_result"] = {
        "payment_id": payment.id,
        "title": title,
        "detail": detail,
        "pending": bool(pending),
    }


@transaction.atomic
def _create_addon_payment(*, user, billing_info, package, payment_method, kind):
    if kind == "ai_credit":
        relation = {"ai_credit_package": package}
        note = f"AI kredi paketi: {package.display_name} ({package.credits} kredi)"
        description = f"{package.display_name} - AI Kredi Paketi"
    elif kind == "product_research":
        relation = {"product_research_package": package}
        note = f"Ürün araştırma paketi: {package.display_name} ({package.units} hak)"
        description = f"{package.display_name} - Ürün Araştırma Paketi"
    else:
        raise ValueError("Bilinmeyen ek paket türü.")

    is_bank_transfer = payment_method == "bank_transfer"
    payment = Payment.objects.create(
        user=user,
        plan=None,
        billing_info=billing_info,
        amount=package.price_with_kdv,
        kdv_amount=package.price_with_kdv - package.price,
        payment_method=payment_method,
        status="pending" if is_bank_transfer else "completed",
        notes=note,
        **relation,
    )

    if is_bank_transfer:
        _payment_invoice(
            payment,
            net_amount=package.price,
            description=f"{description} - Havale/EFT bekleniyor",
            is_paid=False,
            notes="Havale/EFT bildirimi alındı; manuel ödeme onayı bekleniyor.",
        )
        return payment

    if kind == "ai_credit":
        add_ai_credits(
            user=user,
            amount=package.credits,
            action=AICreditLedger.ACTION_PURCHASE,
            package=package,
            reference=f"ai-credit-package:{package.id}:{payment.id}",
            note=f"{package.display_name} satın alındı.",
        )
    else:
        add_product_research_units(
            user=user,
            amount=package.units,
            package=package,
            reference=f"product-research-package:{package.id}:{payment.id}",
            note=f"{package.display_name} satın alındı. Haklar yalnızca içinde bulunulan ay için geçerlidir.",
        )

    _payment_transaction(payment, f"Demo kart ödemesi - {description}")
    _payment_invoice(
        payment,
        net_amount=package.price,
        description=description,
        is_paid=True,
        notes=note,
    )
    return payment

@capture_errors
def pricing_view(request):
    referral_code = (request.GET.get("ref") or "").strip().upper()
    if referral_code:
        request.session["checkout_referral_code"] = referral_code
    version = f"{CacheService.get_version('pricing_public')}:pricing-layout-v9-pdf-feature-order"
    cached_context = CacheService.get("pricing_public", "plans", version=version)
    if cached_context is not None:
        return render(request, 'pricing/pricing.html', cached_context)

    plans = (
        visible_business_plans()
        .exclude(name__icontains="demo")
        .exclude(display_name__icontains="demo")
    )
    for plan in plans:
        plan.price_with_kdv = plan.price * Decimal('1.20')
        plan.monthly_price = plan.price_with_kdv
        plan.account_limit_text = 'Sinirsiz' if plan.max_instagram_accounts >= 999 else str(plan.max_instagram_accounts)

    agency_plans = visible_agency_plans()
    for plan in agency_plans:
        plan.price_with_kdv = plan.price * Decimal('1.20')
        plan.monthly_price = plan.price_with_kdv
        plan.client_limit_text = 'Sinirsiz' if plan.max_client_accounts >= 999 else str(plan.max_client_accounts)

    ai_credit_packages = visible_ai_credit_packages()
    product_research_packages = ProductResearchPackage.objects.filter(is_active=True).order_by("order", "price")
    
    context = {
        'plans': plans,
        'agency_plans': agency_plans,
        'ai_credit_packages': ai_credit_packages,
        'product_research_packages': product_research_packages,
    }
    context["plans"] = list(context["plans"])
    context["agency_plans"] = list(context["agency_plans"])
    context["ai_credit_packages"] = list(context["ai_credit_packages"])
    context["product_research_packages"] = list(context["product_research_packages"])
    CacheService.set(
        "pricing_public",
        "plans",
        value=context,
        timeout=PRICING_CACHE_TIMEOUT,
        version=version,
    )
    return render(request, 'pricing/pricing.html', context)


@login_required
@capture_errors
def checkout(request, plan_id):
    plan_qs = migration_safe_membership_queryset().filter(id=plan_id, is_active=True)
    if model_table_has_column(MembershipPlan, "plan_type"):
        plan_qs = plan_qs.filter(plan_type__in=[
            MembershipPlan.PLAN_TYPE_BUSINESS,
            MembershipPlan.PLAN_TYPE_AGENCY,
        ])
    else:
        plan_qs = plan_qs.exclude(name__in=["bronze", "bronz"])
    plan = get_object_or_404(plan_qs)
    is_agency_plan = getattr(plan, "plan_type", "") == MembershipPlan.PLAN_TYPE_AGENCY
    
    billing_period = request.POST.get("billing_period") or request.GET.get("billing") or UserSubscription.BILLING_MONTHLY
    if billing_period not in {UserSubscription.BILLING_MONTHLY, UserSubscription.BILLING_YEARLY}:
        billing_period = UserSubscription.BILLING_MONTHLY
    base_amount = plan.yearly_price if billing_period == UserSubscription.BILLING_YEARLY else plan.price
    list_base_amount = (plan.price * Decimal("12")) if billing_period == UserSubscription.BILLING_YEARLY else plan.price
    yearly_discount_amount = max(list_base_amount - base_amount, Decimal("0"))
    kdv_rate = Decimal('0.20')
    kdv_amount = base_amount * kdv_rate
    total_amount = base_amount + kdv_amount
    discounted_base_amount = base_amount
    referral_benefits = None
    referrals_enabled = referral_program_enabled()
    
    if request.method == 'POST':
        form = CheckoutForm(request.POST)
        if form.is_valid():
            referral_code_value = form.cleaned_data.get("referral_code", "") if referrals_enabled else ""
            if referral_code_value:
                referral_code, referral_error = validate_referral_for_checkout(
                    referral_code_value,
                    user=request.user,
                    email=form.cleaned_data.get("email", ""),
                    phone=form.cleaned_data.get("phone", ""),
                    tax_number=form.cleaned_data.get("tax_number", ""),
                    tc_kimlik=form.cleaned_data.get("tc_kimlik", ""),
                )
                if referral_code is None:
                    messages.warning(
                        request,
                        (referral_error or "Promosyon kodu uygulanamadı.") + " Ödeme promosyon uygulanmadan devam edecek.",
                    )
                    referral_code_value = ""
                else:
                    referral_benefits = referral_checkout_benefits(
                        plan=plan,
                        billing_period=billing_period,
                        base_amount=base_amount,
                    )
                    discount_amount = referral_benefits.get("discount_amount", Decimal("0"))
                    discounted_base_amount = max(base_amount - discount_amount, Decimal("0"))
                    kdv_amount = discounted_base_amount * kdv_rate
                    total_amount = discounted_base_amount + kdv_amount
            transfer_details = _bank_transfer_details(request)
            selected_payment_method = form.cleaned_data.get('payment_method', 'credit_card')
            if selected_payment_method == "bank_transfer":
                transfer_errors = _validate_bank_transfer_details(transfer_details)
                if transfer_errors:
                    for error in transfer_errors:
                        messages.error(request, error)
                    return render(request, 'payment/checkout.html', {
                        'plan': plan,
                        'is_agency_plan': is_agency_plan,
                        'billing_period': billing_period,
                        'form': form,
                        'kdv_amount': kdv_amount,
                        'total_amount': total_amount,
                        'transfer_details': transfer_details,
                        'referrals_enabled': referrals_enabled,
                        'referral_benefits': referral_benefits,
                        'list_base_amount': list_base_amount,
                        'yearly_discount_amount': yearly_discount_amount,
                    })
            try:
                # Ödeme yöntemini formdan al veya varsayılan ata
                payment_method = form.cleaned_data.get('payment_method', 'credit_card')
                
                # Fatura bilgilerini oluştur
                billing_info = _get_or_create_billing_info(request.user, form.cleaned_data)
                invoice_note_parts = []
                if yearly_discount_amount:
                    invoice_note_parts.append(f"Yillik abonelik indirimi: {yearly_discount_amount} TL")
                if referral_code_value:
                    invoice_note_parts.append(f"Promosyon kodu: {referral_code_value}")
                if referral_benefits:
                    invoice_note_parts.append(f"Promosyon indirimi: {referral_benefits.get('discount_amount')} TL")
                    invoice_note_parts.append(f"Promosyon odulu: {referral_benefits.get('reward_amount')} {referral_benefits.get('reward_type')}")
                invoice_notes = "\n".join(invoice_note_parts)
                
                payment_method_obj = None
                if payment_method != "bank_transfer":
                    payment_method_obj = save_payment_method_from_checkout(request.user, form.cleaned_data)

                # Ödeme kaydı
                payment = Payment.objects.create(
                    user=request.user,
                    plan=plan,
                    billing_info=billing_info,
                    billing_period=billing_period,
                    amount=total_amount,
                    kdv_amount=kdv_amount,
                    payment_method=payment_method,
                    status='pending' if payment_method == "bank_transfer" else 'completed',
                )
                legal_acceptance = record_purchase_acceptance(
                    request,
                    payment,
                    immediate_service_consent=form.cleaned_data.get("immediate_service_consent"),
                )
                
                # Abonelik oluştur/güncelle
                if payment_method == "bank_transfer":
                    if referral_code_value:
                        record_pending_referral(
                            code=referral_code_value,
                            referred_user=request.user,
                            payment=payment,
                            reward_type=referral_benefits.get("reward_type") if referral_benefits else None,
                            reward_amount=referral_benefits.get("reward_amount") if referral_benefits else None,
                            note="Havale/EFT bildirimi alındı; ödeme onayı bekleniyor.",
                        )
                    Invoice.objects.create(
                        user=request.user,
                        subscription=None,
                        billing_info=billing_info,
                        invoice_number=f"INV-{timezone.now().strftime('%Y%m%d')}-{request.user.id}-{payment.id}",
                        amount=discounted_base_amount,
                        kdv_amount=kdv_amount,
                        total_amount=total_amount,
                        payment_method=payment_method,
                        is_paid=False,
                        due_date=timezone.now().date() + timedelta(days=7),
                        status='draft',
                        description=f"{plan.display_name} - Havale/EFT bekleyen ödeme",
                        notes=("Havale/EFT bildirimi alindi. Manuel odeme onayi bekleniyor." + (f"\n{invoice_notes}" if invoice_notes else "")),
                    )
                    _send_bank_transfer_notice(
                        request,
                        billing_info,
                        payment,
                        f"{plan.display_name} Paketi",
                        transfer_details,
                    )
                    queue_purchase_legal_email(legal_acceptance)
                    _remember_payment_result(
                        request,
                        payment,
                        title="Havale bildirimi alındı",
                        detail=f"{plan.display_name} aboneliği için ödeme onayı bekleniyor.",
                        pending=True,
                    )
                    request.session.pop("checkout_referral_code", None)
                    messages.success(request, "Havale/EFT bildiriminiz alındı. Ödeme kontrolünden sonra paketiniz manuel olarak aktif edilecektir.")
                    return redirect('payment_success')

                organization = None
                if is_agency_plan:
                    agency_name = (
                        request.POST.get("agency_name", "").strip()
                        or form.cleaned_data.get("company_name", "").strip()
                        or f"{request.user.get_full_name() or request.user.email} Ajansı"
                    )
                    organization, _ = Organization.objects.update_or_create(
                        owner=request.user,
                        name=agency_name,
                        defaults={
                            "active_plan": plan,
                            "is_active": True,
                            "report_brand_name": agency_name,
                        },
                    )
                    OrganizationMember.objects.update_or_create(
                        organization=organization,
                        user=request.user,
                        defaults={
                            "role": OrganizationMember.ROLE_OWNER,
                            "is_active": True,
                            "invited_email": request.user.email or "",
                        },
                    )
                    CacheService.bump_version("agency_dashboard", organization.id)

                subscription, created = UserSubscription.objects.update_or_create(
                    user=request.user,
                    organization=organization,
                    defaults={
                        'plan': plan,
                        'start_date': timezone.now().date(),
                        'end_date': timezone.now().date() + (timedelta(days=365) if billing_period == UserSubscription.BILLING_YEARLY else timedelta(days=30)),
                        'billing_period': billing_period,
                        'auto_renew': request.POST.get("auto_renew", "on") == "on",
                        'default_payment_method': payment_method_obj,
                        'next_renewal_date': timezone.now().date() + (timedelta(days=365) if billing_period == UserSubscription.BILLING_YEARLY else timedelta(days=30)),
                        'is_active': True,
                    }
                )
                grant_plan_ai_credits(subscription)
                referral_result = None
                if referral_code_value:
                    referral_result = award_referral_for_subscription(
                        code=referral_code_value,
                        referred_user=request.user,
                        subscription=subscription,
                        payment=payment,
                        reward_type=referral_benefits.get("reward_type") if referral_benefits else None,
                        reward_amount=referral_benefits.get("reward_amount") if referral_benefits else None,
                    )
                
                # Fatura oluştur
                Invoice.objects.create(
                    user=request.user,
                    subscription=subscription,
                    billing_info=billing_info,
                    invoice_number=f"INV-{timezone.now().strftime('%Y%m%d')}-{request.user.id}-{payment.id}",
                    amount=discounted_base_amount,
                    kdv_amount=kdv_amount,
                    total_amount=total_amount,
                    payment_method=payment_method,
                    is_paid=True,
                    payment_date=timezone.now(),
                    due_date=timezone.now().date() + timedelta(days=30),
                    status='paid',
                    notes=invoice_notes or None,
                    description=f"{plan.display_name} - {'Yıllık' if billing_period == UserSubscription.BILLING_YEARLY else 'Aylık'} Abonelik",
                )
                _payment_transaction(payment, f"Demo kart ödemesi - {plan.display_name} aboneliği")
                queue_purchase_legal_email(legal_acceptance)
                _remember_payment_result(
                    request,
                    payment,
                    title="Abonelik aktif edildi",
                    detail=f"{plan.display_name} paketiniz başarıyla aktif edildi.",
                )
                request.session.pop("checkout_referral_code", None)
                
                messages.success(request, f'✅ {plan.display_name} paketiniz başarıyla aktif edildi!')
                return redirect('payment_success')
                
            except Exception as e:
                messages.error(request, f'❌ Ödeme işlemi sırasında bir hata oluştu: {str(e)}')
        else:
            # Form hatalarını göster
            for field, errors in form.errors.items():
                label = form.fields[field].label if field in form.fields else field
                for error in errors:
                    messages.error(request, f'{label}: {error}')
    else:
        form = CheckoutForm(initial={
            'first_name': request.user.get_full_name() or request.user.first_name,
            'last_name': request.user.last_name,
            'email': request.user.email,
            'customer_type': 'individual',
            'payment_method': 'credit_card',
        })
        form.initial['referral_code'] = request.GET.get("ref") or request.session.get("checkout_referral_code", "")
    
    context = {
        'plan': plan,
        'is_agency_plan': is_agency_plan,
        'list_base_amount': list_base_amount,
        'base_amount': base_amount,
        'discounted_base_amount': discounted_base_amount,
        'yearly_discount_amount': yearly_discount_amount,
        'referrals_enabled': referrals_enabled,
        'referral_benefits': referral_benefits,
        'billing_period': billing_period,
        'form': form,
        'kdv_amount': kdv_amount,
        'total_amount': total_amount,
    }
    return render(request, 'payment/checkout.html', context)


@login_required
@capture_errors
def credit_checkout(request, package_id):
    if not get_active_subscription(request.user):
        messages.error(request, "Ek kredi paketi satın almak için aktif deneme veya abonelik gereklidir.")
        return redirect("pricing")
    package = get_object_or_404(AICreditPackage, id=package_id, is_active=True)
    kdv_amount = package.price_with_kdv - package.price
    total_amount = package.price_with_kdv

    if request.method == 'POST':
        form = CheckoutForm(request.POST)
        if form.is_valid():
            transfer_details = _bank_transfer_details(request)
            selected_payment_method = form.cleaned_data.get('payment_method', 'credit_card')
            if selected_payment_method == "bank_transfer":
                transfer_errors = _validate_bank_transfer_details(transfer_details)
                if transfer_errors:
                    for error in transfer_errors:
                        messages.error(request, error)
                    return render(request, 'payment/checkout.html', {
                        'plan': None,
                        'package': package,
                        'is_credit_package': True,
                        'is_agency_plan': False,
                        'form': form,
                        'kdv_amount': kdv_amount,
                        'total_amount': total_amount,
                        'transfer_details': transfer_details,
                    })
            try:
                payment_method = form.cleaned_data.get('payment_method', 'credit_card')
                billing_info = _get_or_create_billing_info(request.user, form.cleaned_data)
                if payment_method != "bank_transfer":
                    save_payment_method_from_checkout(request.user, form.cleaned_data)
                payment = _create_addon_payment(
                    user=request.user,
                    billing_info=billing_info,
                    package=package,
                    payment_method=payment_method,
                    kind="ai_credit",
                )
                legal_acceptance = record_purchase_acceptance(
                    request,
                    payment,
                    immediate_service_consent=form.cleaned_data.get("immediate_service_consent"),
                )
                if payment_method == "bank_transfer":
                    _send_bank_transfer_notice(
                        request,
                        billing_info,
                        payment,
                        f"{package.display_name} AI Kredi Paketi",
                        transfer_details,
                    )
                    queue_purchase_legal_email(legal_acceptance)
                    _remember_payment_result(
                        request,
                        payment,
                        title="Havale bildirimi alındı",
                        detail=f"{package.display_name} için ödeme onayı bekleniyor.",
                        pending=True,
                    )
                    messages.success(request, "Havale/EFT bildiriminiz alındı. Ödeme kontrolünden sonra krediniz manuel olarak yüklenecektir.")
                    return redirect('payment_success')
                _remember_payment_result(
                    request,
                    payment,
                    title="AI kredileri yüklendi",
                    detail=f"{package.credits:,} AI kredi hesabınıza eklendi.",
                )
                queue_purchase_legal_email(legal_acceptance)
                messages.success(request, f'{package.display_name} başarıyla hesabınıza yüklendi.')
                return redirect('payment_success')
            except Exception as e:
                messages.error(request, f'Ödeme işlemi sırasında bir hata oluştu: {str(e)}')
        else:
            for field, errors in form.errors.items():
                label = form.fields[field].label if field in form.fields else field
                for error in errors:
                    messages.error(request, f'{label}: {error}')
    else:
        form = CheckoutForm(initial={
            'first_name': request.user.get_full_name() or request.user.first_name,
            'last_name': request.user.last_name,
            'email': request.user.email,
            'customer_type': 'individual',
            'payment_method': 'credit_card',
        })

    context = {
        'plan': None,
        'package': package,
        'is_credit_package': True,
        'is_agency_plan': False,
        'form': form,
        'kdv_amount': kdv_amount,
        'total_amount': total_amount,
        'referrals_enabled': False,
        'referral_benefits': None,
    }
    return render(request, 'payment/checkout.html', context)


@login_required
@capture_errors
def product_research_checkout(request, package_id):
    subscription = get_active_subscription(request.user)
    if not subscription:
        messages.error(request, "Ürün araştırma paketi satın almak için aktif deneme veya abonelik gereklidir.")
        return redirect("pricing")
    if (
        subscription.plan.name != "trial_14"
        and int(subscription.plan.marketplace_product_research_per_month or 0) <= 0
    ):
        messages.error(request, "Mevcut paketiniz pazaryeri ve ürün araştırması özelliğini içermiyor.")
        return redirect("pricing")
    package = get_object_or_404(ProductResearchPackage, id=package_id, is_active=True)
    kdv_amount = package.price_with_kdv - package.price
    total_amount = package.price_with_kdv

    if request.method == 'POST':
        form = CheckoutForm(request.POST)
        if form.is_valid():
            transfer_details = _bank_transfer_details(request)
            payment_method = form.cleaned_data.get('payment_method', 'credit_card')
            if payment_method == "bank_transfer":
                transfer_errors = _validate_bank_transfer_details(transfer_details)
                if transfer_errors:
                    for error in transfer_errors:
                        messages.error(request, error)
                    return render(request, 'payment/checkout.html', {
                        'plan': None,
                        'package': package,
                        'is_product_research_package': True,
                        'is_agency_plan': False,
                        'form': form,
                        'kdv_amount': kdv_amount,
                        'total_amount': total_amount,
                        'transfer_details': transfer_details,
                    })
            try:
                billing_info = _get_or_create_billing_info(request.user, form.cleaned_data)
                if payment_method != "bank_transfer":
                    save_payment_method_from_checkout(request.user, form.cleaned_data)
                payment = _create_addon_payment(
                    user=request.user,
                    billing_info=billing_info,
                    package=package,
                    payment_method=payment_method,
                    kind="product_research",
                )
                legal_acceptance = record_purchase_acceptance(
                    request,
                    payment,
                    immediate_service_consent=form.cleaned_data.get("immediate_service_consent"),
                )
                if payment_method == "bank_transfer":
                    _send_bank_transfer_notice(
                        request,
                        billing_info,
                        payment,
                        f"{package.display_name} Ürün Araştırma Paketi",
                        transfer_details,
                    )
                    queue_purchase_legal_email(legal_acceptance)
                    _remember_payment_result(
                        request,
                        payment,
                        title="Havale bildirimi alındı",
                        detail=f"{package.display_name} için ödeme onayı bekleniyor.",
                        pending=True,
                    )
                    messages.success(request, "Havale/EFT bildiriminiz alındı. Ödeme kontrolünden sonra ürün araştırma hakkınız manuel olarak yüklenecektir.")
                    return redirect('payment_success')

                _remember_payment_result(
                    request,
                    payment,
                    title="Ürün araştırma hakları yüklendi",
                    detail=f"{package.units:,} araştırma hakkı bu ayki bakiyenize eklendi.",
                )
                queue_purchase_legal_email(legal_acceptance)
                messages.success(request, f'{package.display_name} bu ayki ürün araştırma bakiyenize yüklendi.')
                return redirect('payment_success')
            except Exception as e:
                messages.error(request, f'Ödeme işlemi sırasında bir hata oluştu: {str(e)}')
        else:
            for field, errors in form.errors.items():
                label = form.fields[field].label if field in form.fields else field
                for error in errors:
                    messages.error(request, f'{label}: {error}')
    else:
        form = CheckoutForm(initial={
            'first_name': request.user.get_full_name() or request.user.first_name,
            'last_name': request.user.last_name,
            'email': request.user.email,
            'customer_type': 'individual',
            'payment_method': 'credit_card',
        })

    context = {
        'plan': None,
        'package': package,
        'is_product_research_package': True,
        'is_agency_plan': False,
        'form': form,
        'kdv_amount': kdv_amount,
        'total_amount': total_amount,
        'referrals_enabled': False,
        'referral_benefits': None,
    }
    return render(request, 'payment/checkout.html', context)

@login_required
@capture_errors
def payment_success(request):
    result = request.session.pop("payment_result", None)
    payment = None
    subscription = None
    if result and result.get("payment_id"):
        payment = (
            Payment.objects.filter(id=result["payment_id"], user=request.user)
            .select_related("plan", "ai_credit_package", "product_research_package")
            .first()
        )
    if payment and payment.plan_id and payment.status == "completed":
        subscription = UserSubscription.objects.filter(user=request.user, plan=payment.plan, is_active=True).order_by("-created_at").first()
    return render(request, 'payment/success.html', {
        'subscription': subscription,
        'payment': payment,
        'payment_result': result,
    })


@login_required
@capture_errors
def my_account(request):
    active_subscription = UserSubscription.objects.filter(user=request.user, is_active=True).select_related("organization").first()
    subscriptions = UserSubscription.objects.filter(user=request.user).order_by('-created_at')
    payments = Payment.objects.filter(user=request.user).order_by('-created_at')[:10]
    invoices = Invoice.objects.filter(user=request.user).order_by('-created_at')[:10]
    security_summary = _account_security_summary(request.user)
    credit_organization = active_subscription.organization if active_subscription else None
    ai_credit_balance = refresh_ai_credit_balance(request.user, organization=credit_organization)
    ai_credit_total = 0
    ai_credit_usage_percent = 0
    if ai_credit_balance:
        ai_credit_total = int(ai_credit_balance.plan_credits or 0) + int(ai_credit_balance.purchased_credits or 0)
        if ai_credit_total > 0:
            ai_credit_usage_percent = min(100, round((int(ai_credit_balance.used_credits or 0) / ai_credit_total) * 100))
    referral_code = None
    referral_stats = {"pending": 0, "awarded": 0, "cancelled": 0}
    referral_share_url = ""
    if referral_program_enabled():
        referral_code, _ = ensure_user_referral_code(request.user)
        if referral_code:
            rewards = referral_code.rewards.all()
            referral_stats = {
                "pending": rewards.filter(status="pending").count(),
                "awarded": rewards.filter(status="awarded").count(),
                "cancelled": rewards.filter(status="cancelled").count(),
            }
            referral_share_url = request.build_absolute_uri(f"/pricing/?ref={referral_code.code}")
    
    return render(request, 'account/my_account.html', {
        'active_subscription': active_subscription,
        'subscriptions': subscriptions,
        'payments': payments,
        'invoices': invoices,
        'security_summary': security_summary,
        'ai_credit_balance': ai_credit_balance,
        'ai_credit_total': ai_credit_total,
        'ai_credit_usage_percent': ai_credit_usage_percent,
        'referral_code': referral_code,
        'referral_stats': referral_stats,
        'referral_share_url': referral_share_url,
    })


@login_required
@capture_errors
def my_subscriptions(request):
    subscriptions = UserSubscription.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'account/subscriptions.html', {'subscriptions': subscriptions})


@login_required
@capture_errors
def my_invoices(request):
    invoices = Invoice.objects.filter(user=request.user).order_by('-created_at')
    total_amount = invoices.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    paid_count = invoices.filter(status='paid').count()
    pending_count = invoices.exclude(status='paid').count()
    last_invoice = invoices.first()
    return render(request, 'account/invoices.html', {
        'invoices': invoices,
        'total_amount': total_amount,
        'paid_count': paid_count,
        'pending_count': pending_count,
        'last_invoice': last_invoice,
    })


@login_required
@capture_errors
def my_payments(request):
    payments = Payment.objects.filter(user=request.user).order_by('-created_at')
    total_amount = payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    return render(request, 'account/payments.html', {
        'payments': payments,
        'total_amount': total_amount,
    })


@login_required
@capture_errors
def invoice_detail(request, invoice_id):
    invoice = get_object_or_404(Invoice, id=invoice_id, user=request.user)
    return render(request, 'account/invoice_detail.html', {'invoice': invoice})


@login_required
@capture_errors
def invoice_pdf(request, invoice_id):
    invoice = get_object_or_404(Invoice, id=invoice_id, user=request.user)
    pdf_bytes = _build_invoice_pdf(invoice)
    filename = f"fatura-{invoice.invoice_number}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response
