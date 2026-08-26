from decimal import Decimal

from django.core.management.base import BaseCommand

from core.models import (
    AdGroupMetricHistory,
    AdMetricHistory,
    CampaignMetricHistory,
    CreativeMetricHistory,
)
from core.services.performance_metrics import normalize_metric_payload, safe_decimal


MODELS = {
    "campaign": CampaignMetricHistory,
    "adgroup": AdGroupMetricHistory,
    "ad": AdMetricHistory,
    "creative": CreativeMetricHistory,
}

FIELDS = (
    "conversions",
    "conversion_value",
    "purchases",
    "add_to_cart",
    "initiate_checkout",
    "leads",
    "landing_page_views",
    "outbound_clicks",
    "cost_per_conversion",
    "roas",
    "raw_metrics",
)


class Command(BaseCommand):
    help = (
        "raw_metrics icinde gelen platform donusum/deger alanlarini okuyup "
        "metric history tablolarindaki conversion_value ve hesaplanan alanlari doldurur."
    )

    def add_arguments(self, parser):
        parser.add_argument("--model", choices=[*MODELS.keys(), "all"], default="all")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options):
        selected = options["model"]
        model_items = MODELS.items() if selected == "all" else [(selected, MODELS[selected])]
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        grand_scanned = 0
        grand_updated = 0
        grand_recovered = 0
        grand_estimated = 0

        for label, model in model_items:
            fields = [field for field in FIELDS if hasattr(model, field)]
            qs = (
                model.objects
                .filter(conversions__gt=0, conversion_value=0)
                .exclude(raw_metrics__isnull=True)
                .exclude(raw_metrics={})
                .order_by("id")
            )
            aov = self._average_value_per_conversion(model)
            scanned = 0
            updated = 0
            recovered = 0
            estimated = 0
            pending = []

            for row in qs.iterator(chunk_size=batch_size):
                scanned += 1
                raw_metrics = dict(row.raw_metrics or {})
                raw_metrics.setdefault("spend", str(row.spend))
                raw_metrics.setdefault("conversions", str(row.conversions))
                raw_metrics.setdefault("currency", row.currency)
                raw_metrics.setdefault("estimated_conversion_value_per_conversion", str(aov))
                normalized = normalize_metric_payload(raw_metrics)
                changed = False

                before_value = safe_decimal(getattr(row, "conversion_value", 0))
                after_value = safe_decimal(normalized.get("conversion_value"))
                after_raw = normalized.get("raw_metrics") or raw_metrics
                if before_value > 0 or after_value <= 0:
                    continue

                for field in fields:
                    new_value = after_raw if field == "raw_metrics" else normalized.get(field)
                    if new_value is None:
                        continue
                    old_value = getattr(row, field)
                    is_changed = old_value != new_value if field == "raw_metrics" else safe_decimal(old_value) != safe_decimal(new_value)
                    if is_changed:
                        setattr(row, field, new_value)
                        changed = True

                if changed:
                    updated += 1
                    if before_value == Decimal("0") and after_value > Decimal("0"):
                        recovered += 1
                        if after_raw.get("conversion_value_estimated"):
                            estimated += 1
                    if not dry_run:
                        pending.append(row)
                        if len(pending) >= batch_size:
                            model.objects.bulk_update(pending, fields)
                            pending.clear()

            if pending and not dry_run:
                model.objects.bulk_update(pending, fields)

            grand_scanned += scanned
            grand_updated += updated
            grand_recovered += recovered
            grand_estimated += estimated
            self.stdout.write(
                f"{label}: scanned={scanned}, "
                f"{'would_update' if dry_run else 'updated'}={updated}, "
                f"recovered_conversion_value={recovered}, "
                f"estimated_conversion_value={estimated}, "
                f"estimate_per_conversion={aov}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"total: scanned={grand_scanned}, "
                f"{'would_update' if dry_run else 'updated'}={grand_updated}, "
                f"recovered_conversion_value={grand_recovered}, "
                f"estimated_conversion_value={grand_estimated}"
            )
        )

    def _average_value_per_conversion(self, model):
        total_value = Decimal("0")
        total_conversions = Decimal("0")
        for row in model.objects.filter(conversion_value__gt=0, conversions__gt=0).only(
            "conversion_value",
            "conversions",
        ).iterator(chunk_size=1000):
            total_value += safe_decimal(row.conversion_value)
            total_conversions += safe_decimal(row.conversions)
        if total_conversions:
            return (total_value / total_conversions).quantize(Decimal("0.01"))
        return Decimal("500.00")
