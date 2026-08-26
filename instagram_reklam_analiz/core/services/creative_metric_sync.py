# core/services/creative_metric_sync.py
from django.utils import timezone

from core.models import CreativeMetricHistory
from core.services.performance_metrics import normalize_metric_payload


def _model_field_names(model):
    return {
        field.name
        for field in model._meta.get_fields()
        if getattr(field, "concrete", False) and not getattr(field, "many_to_many", False)
    }


def _safe_defaults(model, data):
    fields = _model_field_names(model)
    return {key: value for key, value in data.items() if key in fields}


def sync_creative_metric_from_ad(ad, raw_data=None, metric_date=None):
    """
    Ad + raw_data üzerinden CreativeMetricHistory kaydı oluşturur/günceller.

    Kullanım:
        sync_creative_metric_from_ad(ad, raw)

    Not:
    - Sadece ad.creative varsa çalışır.
    - CreativeMetricHistory modelinde hangi alanlar varsa sadece onları doldurur.
    - Alan adı değişikliklerinde patlamaması için güvenli defaults kullanır.
    """

    if not ad or not getattr(ad, "creative_id", None):
        return None

    raw = raw_data or getattr(ad, "raw_data", None) or {}
    metric_date = metric_date or timezone.now().date()
    default_candidates = normalize_metric_payload(raw)

    defaults = _safe_defaults(CreativeMetricHistory, default_candidates)

    obj, _ = CreativeMetricHistory.objects.update_or_create(
        creative=ad.creative,
        date=metric_date,
        defaults=defaults,
    )

    return obj


def sync_creative_metrics_for_ads(ads, metric_date=None):
    """
    Birden fazla reklam için creative metric sync yapar.
    """
    created_or_updated = 0

    for ad in ads:
        obj = sync_creative_metric_from_ad(
            ad=ad,
            raw_data=getattr(ad, "raw_data", None) or {},
            metric_date=metric_date,
        )
        if obj:
            created_or_updated += 1

    return created_or_updated
