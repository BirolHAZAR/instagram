from __future__ import annotations

from django.core.management.base import BaseCommand

from core.services.demo_media import create_demo_svg


class Command(BaseCommand):
    help = "Generate all local demo media files used by seed_demo_data."

    def handle(self, *args, **options):
        seeds = []

        # ============================================================
        # 1. REKLAM GÖRSELLERİ
        # seed_demo_data.py:
        # 7 platform × 2 hesap × 2 kampanya × 2 reklam = 56
        # ============================================================

        platforms = [
            "instagram",
            "facebook",
            "google_ads",
            "tiktok",
            "linkedin",
            "x",
            "youtube",
        ]

        for code in platforms:
            for account_no in range(1, 3):
                for campaign_no in range(1, 3):
                    for ad_no in range(1, 3):
                        seeds.append(
                            f"{code}-{account_no}-{campaign_no}-{ad_no}"
                        )

        # ============================================================
        # 2. MARKETPLACE GÖRSELLERİ
        # seed_demo_data.py:
        # 3 marketplace × 20 ürün = 60
        # ============================================================

        marketplaces = [
            "trendyol",
            "hepsiburada",
            "n11",
        ]

        for marketplace in marketplaces:
            for idx in range(1, 21):
                seeds.append(
                    f"{marketplace}-{idx}"
                )

        # ============================================================
        # 3. SOSYAL MEDYA GÖRSELLERİ
        # seed_demo_data.py:
        # 7 platform × 3 post = 21
        # ============================================================

        for idx, code in enumerate(platforms, start=1):
            for post_no in range(1, 4):
                seeds.append(
                    f"social-{idx}-{post_no}"
                )

        # Benzersiz seed'leri koru
        seeds = list(dict.fromkeys(seeds))

        self.stdout.write(
            f"Toplam demo görseli: {len(seeds)}"
        )

        created = 0
        skipped = 0

        for seed in seeds:
            path = create_demo_svg(seed)

            if path.exists():
                created += 1
            else:
                skipped += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo medya tamamlandi: {created} dosya"
            )
        )

        if skipped:
            self.stdout.write(
                self.style.WARNING(
                    f"Olusturulamayan dosya: {skipped}"
                )
            )