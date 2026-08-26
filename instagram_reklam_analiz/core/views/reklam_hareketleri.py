from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.http import JsonResponse
from core.models import Ad, AdMetricHistory, PlatformAccount, Platform


@login_required
def reklam_hareketleri(request):
    ads = Ad.objects.filter(user=request.user, source_type="OWN").select_related("platform_account", "platform_account__platform")
    return render(request, "reklamlar/reklam_hareketleri.html", {"reklamlar": ads, "v2_only": True})


@login_required
def api_reklam_hareketleri(request):
    qs = AdMetricHistory.objects.filter(ad__user=request.user, ad__source_type="OWN").select_related("ad").order_by("-date")[:500]
    return JsonResponse({"success": True, "items": [{"ad_id": m.ad_id, "ad_name": str(m.ad), "date": m.date.isoformat(), "spend": float(m.spend), "clicks": m.clicks, "impressions": m.impressions} for m in qs]})
