from django.core.management.base import BaseCommand

from core.models import UserAICreditBalance
from core.services.entitlements import refresh_all_ai_credit_balances


class Command(BaseCommand):
    help = "Uye ve ajans bazli AI kredi bakiyelerini yeniden hesaplar."

    def handle(self, *args, **options):
        synced = refresh_all_ai_credit_balances()
        total = UserAICreditBalance.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"AI kredi bakiyeleri senkronize edildi. Islenen={synced}, toplam_kayit={total}"
            )
        )
