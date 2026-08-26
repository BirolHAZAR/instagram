from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import MarketplaceListing
from core.services.marketplace_sync import record_listing_change_history, record_listing_metric_history


class Command(BaseCommand):
    help = "Mevcut pazaryeri ürün kayıtları için günlük metrik ve ilk değişim geçmişi oluşturur."

    def add_arguments(self, parser):
        parser.add_argument("--date", dest="date", help="Snapshot tarihi. Format: YYYY-MM-DD")
        parser.add_argument("--limit", type=int, default=0, help="İşlenecek maksimum kayıt sayısı")

    def handle(self, *args, **options):
        metric_date = datetime.strptime(options["date"], "%Y-%m-%d").date() if options.get("date") else timezone.now().date()
        limit = options.get("limit") or 0

        qs = (
            MarketplaceListing.objects.select_related(
                "marketplace_account",
                "marketplace",
                "product",
                "variant",
            )
            .order_by("id")
        )
        if limit:
            qs = qs[:limit]

        processed = 0
        for listing in qs:
            record_listing_metric_history(listing, metric_date=metric_date)
            if not listing.change_history.exists():
                record_listing_change_history(listing, previous_values={}, created=True)
            processed += 1

        self.stdout.write(self.style.SUCCESS(f"Pazaryeri history backfill tamamlandı. İşlenen kayıt: {processed}"))
