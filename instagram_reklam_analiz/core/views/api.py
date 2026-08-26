from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from core.models import Ad, AdMetricHistory


@login_required
def api_analyze_instagram(request):
    return JsonResponse({"success": True, "message": "V2 analiz endpointi aktif."})


@login_required
def api_competitor_analysis(request):
    total = Ad.objects.filter(user=request.user, source_type="COMPETITOR").count()
    return JsonResponse({"success": True, "competitor_ads": total})


@login_required
def api_analyze_media(request):
    return JsonResponse({"success": True, "message": "Medya analizi V2 Creative/Ad üzerinden yapılacak."})


@login_required
def ad_metrics_detail_api(request, ad_id):
    ad = Ad.objects.filter(id=ad_id, user=request.user).first()
    if not ad:
        return JsonResponse({"success": False, "message": "Reklam bulunamadı."}, status=404)
    qs = AdMetricHistory.objects.filter(ad=ad).order_by("date")
    return JsonResponse({"success": True, "ad": {"id": ad.id, "name": str(ad)}, "metrics": [{"date": m.date.isoformat(), "impressions": m.impressions, "clicks": m.clicks, "spend": float(m.spend), "ctr": float(m.ctr), "conversions": float(m.conversions)} for m in qs]})


@login_required
def ad_demographics_api(request, ad_id):
    return JsonResponse({"success": True, "items": []})


@csrf_exempt
def payment_webhook(request):
    return JsonResponse({"success": True})


@login_required
def api_reklam_tarihce_raporu(request):
    qs = AdMetricHistory.objects.filter(ad__user=request.user, ad__source_type="OWN").values("date").annotate(spend=Sum("spend"), clicks=Sum("clicks"), impressions=Sum("impressions")).order_by("date")
    return JsonResponse({"success": True, "data": [{"date": r["date"].isoformat(), "spend": float(r["spend"] or 0), "clicks": r["clicks"] or 0, "impressions": r["impressions"] or 0} for r in qs]})
