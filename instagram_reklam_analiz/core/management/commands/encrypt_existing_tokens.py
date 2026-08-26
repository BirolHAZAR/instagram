from django.core.management.base import BaseCommand

from core.models.instagram import InstagramAccount
from core.models.platform_account import PlatformAccount


class Command(BaseCommand):
    help = "Mevcut düz metin access_token/refresh_token değerlerini şifreli formata çevirir."

    def handle(self, *args, **options):
        platform_count = 0
        instagram_count = 0

        for account in PlatformAccount.objects.all().iterator():
            update_fields = []

            if account.access_token:
                account.access_token = account.access_token
                update_fields.append("access_token")

            if account.refresh_token:
                account.refresh_token = account.refresh_token
                update_fields.append("refresh_token")

            if update_fields:
                account.save(update_fields=update_fields)
                platform_count += 1

        for account in InstagramAccount.objects.filter(access_token__isnull=False).iterator():
            if account.access_token:
                account.access_token = account.access_token
                account.save(update_fields=["access_token"])
                instagram_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Şifreleme tamamlandı. PlatformAccount: {platform_count}, InstagramAccount: {instagram_count}"
        ))
