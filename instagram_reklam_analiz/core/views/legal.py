from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils.formats import date_format
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.views.decorators.cache import never_cache

from core.models import LegalDocument, LegalSiteSettings


def _token_values(site_settings, document):
    effective_date = document.effective_date or document.published_at or document.updated_at
    if hasattr(effective_date, "date"):
        effective_date = effective_date.date()
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


def render_legal_content(document, site_settings):
    content = document.content
    for token, value in _token_values(site_settings, document).items():
        content = content.replace(f"[[{token}]]", escape(value or "—"))
    return mark_safe(content)


@never_cache
def legal_document_index(request):
    documents = LegalDocument.objects.filter(status=LegalDocument.STATUS_PUBLISHED)
    preview_mode = request.user.is_staff and request.GET.get("preview") == "1"
    if preview_mode:
        documents = LegalDocument.objects.all()

    grouped = []
    for category, label in LegalDocument.CATEGORY_CHOICES:
        category_documents = [doc for doc in documents if doc.category == category]
        if category_documents:
            grouped.append((label, category_documents))
    return render(request, "legal/index.html", {"grouped_documents": grouped, "preview_mode": preview_mode})


@never_cache
def legal_document_detail(request, slug):
    document = get_object_or_404(LegalDocument, slug=slug)
    if document.status != LegalDocument.STATUS_PUBLISHED and not request.user.is_staff:
        raise Http404

    site_settings = LegalSiteSettings.load()
    return render(
        request,
        "legal/detail.html",
        {
            "document": document,
            "rendered_content": render_legal_content(document, site_settings),
            "site_settings": site_settings,
            "is_preview": document.status != LegalDocument.STATUS_PUBLISHED,
        },
    )
