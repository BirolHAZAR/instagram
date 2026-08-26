from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from core.models.notification import Notification


class Command(BaseCommand):
    help = "Aynı kullanıcıda aynı başlık+mesaj olan eski çift bildirimleri temizler."

    def add_arguments(self, parser):
        parser.add_argument("--username", default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        qs = Notification.objects.all().order_by("user_id", "title", "message", "-created_at")
        if options["username"]:
            User = get_user_model()
            user = User.objects.get(username=options["username"])
            qs = qs.filter(user=user)

        seen = set()
        delete_ids = []
        for n in qs:
            key = (n.user_id, n.title, n.message)
            if key in seen:
                delete_ids.append(n.id)
            else:
                seen.add(key)

        self.stdout.write(f"Silinecek duplicate bildirim: {len(delete_ids)}")
        if delete_ids and not options["dry_run"]:
            Notification.objects.filter(id__in=delete_ids).delete()
            self.stdout.write(self.style.SUCCESS("Duplicate bildirimler silindi."))
