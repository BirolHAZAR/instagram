# core/tasks/maintenance.py
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from core.models import RawDataSnapshot

logger = logging.getLogger(__name__)


@shared_task
def cleanup_old_raw_data(days=30):
    """Belirtilen günden eski ham veri anlık görüntülerini temizler."""
    cutoff = timezone.now() - timedelta(days=days)

    deleted, _ = RawDataSnapshot.objects.filter(
        fetched_at__lt=cutoff
    ).delete()

    logger.info(
        f"🧹 Temizlik tamamlandı: {deleted} eski ham veri kaydı silindi (>{days} gün)"
    )

    return deleted
