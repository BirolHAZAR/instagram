from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.services.control_tower_snapshot import build_lightweight_snapshot_for_user


class Command(BaseCommand):
    help = "Control Tower dashboard verilerini hesaplar, snapshot tablolarına kaydeder."

    def add_arguments(self, parser):
        parser.add_argument("--username", default=None)
        parser.add_argument("--period", default="monthly", choices=["daily", "weekly", "monthly", "quarterly"])
        parser.add_argument("--days", type=int, default=30)

    def handle(self, *args, **options):
        User = get_user_model()
        users = User.objects.filter(is_active=True)
        if options.get("username"):
            users = users.filter(username=options["username"])

        count = 0
        for user in users.iterator():
            snapshot = build_lightweight_snapshot_for_user(user, period=options["period"], days=options["days"])
            count += 1
            self.stdout.write(self.style.SUCCESS(f"Snapshot oluşturuldu: user={user.username} snapshot_id={snapshot.id}"))

        self.stdout.write(self.style.SUCCESS(f"Tamamlandı. Toplam snapshot: {count}"))
