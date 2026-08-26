from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.services.control_tower_snapshot import build_lightweight_snapshot_for_user


class Command(BaseCommand):
    help = "Control Tower için günlük/24 saatlik Octo AI analiz raporlarını üretir ve DB'ye kaydeder."

    def add_arguments(self, parser):
        parser.add_argument("--username", type=str, default="", help="Tek kullanıcı için üretir.")
        parser.add_argument("--period", type=str, default="monthly", help="daily, weekly, monthly, quarterly")
        parser.add_argument("--days", type=int, default=30, help="Analiz gün sayısı")
        parser.add_argument("--active-only", action="store_true", help="Sadece aktif kullanıcılar")

    def handle(self, *args, **options):
        User = get_user_model()
        users = User.objects.all()
        if options.get("active_only"):
            users = users.filter(is_active=True)
        username = options.get("username")
        if username:
            users = users.filter(username=username)

        created = 0
        for user in users.iterator():
            snapshot = build_lightweight_snapshot_for_user(
                user,
                period=options.get("period") or "monthly",
                days=options.get("days") or 30,
            )
            created += 1
            self.stdout.write(self.style.SUCCESS(f"AI analiz snapshot oluşturuldu: user={user} snapshot={snapshot.id}"))

        self.stdout.write(self.style.SUCCESS(f"Tamamlandı. Oluşturulan rapor: {created}"))
