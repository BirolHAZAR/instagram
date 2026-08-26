from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.management.base import BaseCommand

from core.models import (
    AdGroupMetricHistory,
    AdMetricHistory,
    CampaignMetricHistory,
    CreativeMetricHistory,
)


CALCULATED_FIELDS = [
    "frequency",
    "ctr",
    "cpc",
    "cpm",
    "cost_per_conversion",
    "roas",
    "engagement_rate",
]

MODEL_MAP = {
    "campaign": CampaignMetricHistory,
    "adgroup": AdGroupMetricHistory,
    "ad": AdMetricHistory,
    "creative": CreativeMetricHistory,
}


def dec(value):
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def div(numerator, denominator, multiplier=1):
    denominator = dec(denominator)
    if not denominator:
        return Decimal("0")
    return dec(numerator) / denominator * dec(multiplier)


def q4(value):
    return dec(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def calculated_values(row):
    return {
        "frequency": q4(div(row.impressions, row.reach)),
        "ctr": q4(div(row.clicks, row.impressions, 100)),
        "cpc": q4(div(row.spend, row.clicks)),
        "cpm": q4(div(row.spend, row.impressions, 1000)),
        "cost_per_conversion": q4(div(row.spend, row.conversions)),
        "roas": q4(div(row.conversion_value, row.spend)),
        "engagement_rate": q4(div(row.engagement, row.impressions, 100)),
    }


class Command(BaseCommand):
    help = (
        "Recomputes calculated metric history fields in-place for Campaign, "
        "AdGroup, Ad and Creative metric history tables."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            choices=sorted(MODEL_MAP.keys()),
            default=None,
            help="Limit recalculation to one metric history model.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count rows that would change without writing to the database.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Bulk update batch size.",
        )

    def handle(self, *args, **options):
        selected = options.get("model")
        dry_run = options.get("dry_run")
        batch_size = max(1, int(options.get("batch_size") or 500))

        model_items = [(selected, MODEL_MAP[selected])] if selected else MODEL_MAP.items()
        total_changed = 0

        for label, model in model_items:
            changed = 0
            scanned = 0
            pending = []

            qs = model.objects.all().order_by("id")
            for row in qs.iterator(chunk_size=batch_size):
                scanned += 1
                values = calculated_values(row)
                is_changed = False
                for field, value in values.items():
                    if dec(getattr(row, field)) != value:
                        setattr(row, field, value)
                        is_changed = True

                if not is_changed:
                    continue

                changed += 1
                if not dry_run:
                    pending.append(row)
                    if len(pending) >= batch_size:
                        model.objects.bulk_update(pending, CALCULATED_FIELDS, batch_size=batch_size)
                        pending = []

            if pending and not dry_run:
                model.objects.bulk_update(pending, CALCULATED_FIELDS, batch_size=batch_size)

            total_changed += changed
            self.stdout.write(
                f"{model.__name__}: scanned={scanned}, "
                f"{'would_update' if dry_run else 'updated'}={changed}"
            )

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry-run complete. Total rows that would change: {total_changed}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Recalculation complete. Total updated rows: {total_changed}"))
