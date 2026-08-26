from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from core.models import AnomalyAlert, OpportunityWindow, AdMetricHistory


@login_required
def anomaly_dashboard(request):
    alerts = AnomalyAlert.objects.filter(user=request.user, is_dismissed=False).order_by("-detected_at")[:100]
    opportunities = OpportunityWindow.objects.filter(user=request.user, is_taken=False).order_by("-confidence_score")[:50]
    return render(request, "anomaly/detector.html", {"alerts": alerts, "opportunities": opportunities, "v2_only": True})


@login_required
def trigger_scan(request):
    return JsonResponse({"success": True, "message": "V2 anomali taraması için AdMetricHistory kullanılacak."})


@login_required
def dismiss_anomaly_alert(request, alert_id):
    AnomalyAlert.objects.filter(id=alert_id, user=request.user).update(is_dismissed=True)
    return JsonResponse({"success": True})


@login_required
def mark_all_alerts_read(request):
    AnomalyAlert.objects.filter(user=request.user).update(is_read=True)
    return JsonResponse({"success": True})


@login_required
def take_opportunity_action(request, opp_id):
    OpportunityWindow.objects.filter(id=opp_id, user=request.user).update(is_taken=True)
    return JsonResponse({"success": True})


@login_required
def anomaly_count_api(request):
    count = AnomalyAlert.objects.filter(user=request.user, is_read=False, is_dismissed=False).count()
    return JsonResponse({"success": True, "count": count})
