from django.http import Http404
from django.shortcuts import render

from core.models import Ad


def demo_competitor_landing(request, identifier, campaign_no):
    """Render the public destination page used by presentation demo ads."""
    suffix = f"/rakip/{identifier}/kampanya-{campaign_no}"
    ad = (
        Ad.objects.filter(
            source_type="COMPETITOR",
            competitor__platform_identifier=identifier,
            landing_url__endswith=suffix,
        )
        .select_related("competitor", "platform_account__platform")
        .order_by("id")
        .first()
    )
    if ad is None or not (ad.raw_data or {}).get("presentation_demo"):
        raise Http404("Kampanya bulunamadı.")

    return render(
        request,
        "rakip/demo_landing.html",
        {"ad": ad, "competitor": ad.competitor, "campaign_no": campaign_no},
    )
