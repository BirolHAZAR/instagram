# core/views/report_views.py (örnek)
from django.utils import timezone
from datetime import timedelta
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from ..services.comparison_report_service import ComparisonReportService


@login_required
def comparison_report_api(request):
    """Karşılaştırmalı rapor API endpoint'i"""
    
    # Parametreler
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    days = int(request.GET.get('days', 30))
    
    if not start_date or not end_date:
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days)
    else:
        from datetime import datetime
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    service = ComparisonReportService(request.user, start_date, end_date)
    report = service.generate_full_report()
    
    return JsonResponse(report)


@login_required
def compare_with_competitor_api(request, competitor_username):
    """Belirli bir rakip ile karşılaştırma"""
    
    days = int(request.GET.get('days', 30))
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days)
    
    service = ComparisonReportService(request.user, start_date, end_date)
    comparison = service.compare_with_competitor(competitor_username)
    
    return JsonResponse(comparison)


@login_required
def daily_trend_chart_api(request, ad_id=None):
    """Günlük trend verisi (grafik için)"""
    
    days = int(request.GET.get('days', 30))
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=days)
    
    service = ComparisonReportService(request.user, start_date, end_date)
    trends = service.get_daily_trend(ad_id=ad_id)
    
    return JsonResponse({'trends': trends})