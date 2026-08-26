from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from core.models import Ad, AdMetricHistory


@shared_task
def create_daily_metric_snapshots():
    
    today = timezone.now().date()
    created = 0
    for ad in Ad.objects.filter(is_active=True):
        if not AdMetricHistory.objects.filter(ad=ad, date=today).exists():
            # API sync yoksa boş snapshot atmayalım; sadece kayıt sayısını dönelim.
            continue
    return {"created": created, "date": str(today), "source": "AdMetricHistory"}


@shared_task
def cleanup_old_metrics(days=180):
    cutoff = timezone.now().date() - timedelta(days=days)
    deleted, _ = AdMetricHistory.objects.filter(date__lt=cutoff).delete()
    return {"deleted": deleted, "cutoff": str(cutoff)}
