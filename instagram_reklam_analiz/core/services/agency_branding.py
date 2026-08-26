from dataclasses import dataclass

from django.contrib.staticfiles import finders
from django.templatetags.static import static


@dataclass(frozen=True)
class ReportBranding:
    brand_name: str
    logo_path: str
    logo_url: str
    footer_note: str


def _default_branding():
    return ReportBranding(
        brand_name="ReklamAnaliz.net",
        logo_path=finders.find("images/logo2.png") or finders.find("images/logo.webp") or "",
        logo_url=static("images/logo2.png"),
        footer_note="",
    )


def get_report_branding(user=None, organization=None, agency_client=None):
    if agency_client is not None:
        if agency_client.logo:
            try:
                return ReportBranding(
                    brand_name=agency_client.name,
                    logo_path=agency_client.logo.path,
                    logo_url=agency_client.logo.url,
                    footer_note=agency_client.organization.report_footer_note,
                )
            except ValueError:
                pass
        # Müşteri raporunda müşteri logosu yoksa ürün markasını kullan.
        return _default_branding()

    if organization is None and agency_client is not None:
        organization = agency_client.organization

    if organization is None and user is not None:
        organization = (
            user.owned_organizations.filter(is_active=True).select_related("active_plan").first()
            or None
        )

    if organization is None:
        return _default_branding()

    logo_path = ""
    logo_url = ""
    if organization.use_logo_on_reports and organization.logo:
        try:
            logo_path = organization.logo.path
            logo_url = organization.logo.url
        except ValueError:
            logo_path = ""
            logo_url = ""

    if not logo_path:
        return _default_branding()

    return ReportBranding(
        brand_name=organization.report_brand_name or organization.name,
        logo_path=logo_path,
        logo_url=logo_url,
        footer_note=organization.report_footer_note,
    )
