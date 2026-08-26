from django.core.management.base import BaseCommand

from core.models import Ad, Competitor, ControlTowerCardSnapshot, Creative, Notification, OctoTaskInstance, OctoTaskRule
from core.services.cache_service import CacheService
from core.services.competitor_live_sync import SUPPORTED_META_PLATFORMS


class Command(BaseCommand):
    help = "Remove synthetic/unsupported competitor intelligence data so live pages do not show misleading demo data."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="Actually delete/update data. Without this flag it only reports.")

    def handle(self, *args, **options):
        commit = options["commit"]

        demo_ads = Ad.objects.filter(source_type="COMPETITOR", raw_data__demo=True)
        demo_creative_ids = list(
            Creative.objects.filter(raw_data__demo=True, ads__source_type="COMPETITOR")
            .distinct()
            .values_list("id", flat=True)
        )
        demo_competitors = Competitor.objects.filter(raw_data__demo=True)
        unsupported_competitors = Competitor.objects.exclude(platform__code__in=SUPPORTED_META_PLATFORMS)
        unsupported_ads = Ad.objects.filter(source_type="COMPETITOR").exclude(competitor__platform__code__in=SUPPORTED_META_PLATFORMS)
        demo_competitor_tasks = OctoTaskInstance.objects.filter(rule__code="demo_competitor_pressure")
        demo_competitor_rules = OctoTaskRule.objects.filter(code="demo_competitor_pressure")
        demo_competitor_cards = ControlTowerCardSnapshot.objects.filter(card_key=ControlTowerCardSnapshot.CARD_COMPETITOR, payload__demo=True)
        demo_competitor_notifications = Notification.objects.filter(title__icontains="Rakip") | Notification.objects.filter(message__icontains="rakip")

        self.stdout.write(f"Demo rakip reklam: {demo_ads.count()}")
        self.stdout.write(f"Demo rakip kreatif: {len(demo_creative_ids)}")
        self.stdout.write(f"Demo rakip profil: {demo_competitors.count()}")
        self.stdout.write(f"Desteklenmeyen platform rakip profil: {unsupported_competitors.count()}")
        self.stdout.write(f"Desteklenmeyen platform rakip reklam: {unsupported_ads.count()}")
        self.stdout.write(f"Demo rakip gorev: {demo_competitor_tasks.count()}")
        self.stdout.write(f"Demo rakip kural: {demo_competitor_rules.count()}")
        self.stdout.write(f"Demo rakip kontrol karti: {demo_competitor_cards.count()}")
        self.stdout.write(f"Demo/rakip bildirim: {demo_competitor_notifications.count()}")

        if not commit:
            self.stdout.write(self.style.WARNING("Silme yapilmadi. Uygulamak icin --commit kullanin."))
            return

        user_ids = set(demo_competitors.values_list("user_id", flat=True)) | set(unsupported_competitors.values_list("user_id", flat=True))

        deleted_unsupported_ads, _ = unsupported_ads.delete()
        deleted_demo_ads, _ = demo_ads.delete()
        deleted_demo_creatives, _ = Creative.objects.filter(id__in=demo_creative_ids).delete()
        deactivated_unsupported = unsupported_competitors.update(is_active=False)
        deleted_demo_competitors, _ = demo_competitors.delete()
        deleted_demo_tasks, _ = demo_competitor_tasks.delete()
        deleted_demo_rules, _ = demo_competitor_rules.delete()
        deleted_demo_cards, _ = demo_competitor_cards.delete()
        deleted_demo_notifications, _ = demo_competitor_notifications.delete()

        for user_id in user_ids:
            CacheService.bump_version("competitors", user_id)
            CacheService.bump_version("competitor_movements", user_id)
            CacheService.bump_version("competitor_movements_page", user_id)
            CacheService.bump_version("competitor_intelligence", user_id)

        self.stdout.write(self.style.SUCCESS(
            "Temizlik tamamlandi: "
            f"unsupported_ads={deleted_unsupported_ads}, demo_ads={deleted_demo_ads}, "
            f"demo_creatives={deleted_demo_creatives}, unsupported_deactivated={deactivated_unsupported}, "
            f"demo_competitors={deleted_demo_competitors}, demo_tasks={deleted_demo_tasks}, "
            f"demo_rules={deleted_demo_rules}, demo_cards={deleted_demo_cards}, "
            f"demo_notifications={deleted_demo_notifications}"
        ))
