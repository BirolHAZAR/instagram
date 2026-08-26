from django.core.management.base import BaseCommand

from core.services.referrals import ensure_referral_codes_for_all_users


class Command(BaseCommand):
    help = "Eksik referans/promosyon kodlarını kullanıcılar için otomatik oluşturur."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all-users",
            action="store_true",
            help="Pasif kullanıcılar dahil tüm kullanıcılar için kontrol yap.",
        )
        parser.add_argument(
            "--reward-amount",
            type=int,
            default=10000,
            help="Yeni oluşturulan kodların varsayılan AI kredi ödülü.",
        )

    def handle(self, *args, **options):
        result = ensure_referral_codes_for_all_users(
            only_active=not options["all_users"],
            reward_amount=options["reward_amount"],
        )
        if not result["enabled"]:
            self.stdout.write(self.style.WARNING("Referans/promosyon sistemi kapalı. Kod oluşturulmadı."))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Kontrol edilen: {result['checked']} | Yeni oluşturulan: {result['created']} | Mevcut: {result['existing']}"
        ))
