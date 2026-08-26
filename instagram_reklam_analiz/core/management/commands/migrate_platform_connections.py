from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "PlatformAccount token bilgilerini PlatformConnection tablosuna taşır ve hesapları bağlantıya bağlar."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        from core.models import PlatformAccount, PlatformConnection

        created_count = 0
        linked_count = 0
        skipped_count = 0

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN: Kayıt yapılmayacak."))

        with transaction.atomic():
            accounts = PlatformAccount.objects.select_related("user", "platform").all()

            for account in accounts:
                token = getattr(account, "access_token", None)

                if not token:
                    skipped_count += 1
                    continue

                connection = getattr(account, "connection", None)

                if not connection:
                    if dry_run:
                        created_count += 1
                        linked_count += 1
                        continue

                    connection = PlatformConnection.objects.create(
                        user=account.user,
                        platform=account.platform,
                        name=account.account_name or account.account_id,
                        access_token=account.access_token,
                        refresh_token=getattr(account, "refresh_token", None),
                        token_expiry=getattr(account, "token_expiry", None),
                        status="active",
                        last_sync=account.last_sync,
                        extra_data={
                            "migrated_from": "PlatformAccount",
                            "platform_account_id": account.id,
                            "account_id": account.account_id,
                            "account_name": account.account_name,
                            "old_extra_data": account.extra_data,
                        },
                        is_active=account.is_active,
                    )

                    created_count += 1

                if not dry_run:
                    account.connection = connection
                    account.save(update_fields=["connection"])

                linked_count += 1

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS("PlatformConnection taşıma tamamlandı."))
        self.stdout.write(f"Oluşturulan bağlantı: {created_count}")
        self.stdout.write(f"Bağlanan hesap: {linked_count}")
        self.stdout.write(f"Atlanan hesap: {skipped_count}")