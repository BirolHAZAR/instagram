from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connection, transaction
from django.db.models.deletion import Collector


class Command(BaseCommand):
    help = "Keep one admin user and purge every user-owned business record."

    def add_arguments(self, parser):
        parser.add_argument("--admin-username", default="admin")
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError("Refusing to delete data without --confirm.")

        User = get_user_model()
        admin_username = options["admin_username"]
        admin = User.objects.filter(username=admin_username).first()
        if not admin:
            raise CommandError(f"Admin user not found: {admin_username}")

        collector = Collector(using=DEFAULT_DB_ALIAS)
        non_admin_users = User.objects.exclude(pk=admin.pk)
        collector.collect(non_admin_users)

        admin_roots = []
        for model in apps.get_models():
            if model is User:
                continue

            for field in model._meta.get_fields():
                if not getattr(field, "is_relation", False):
                    continue
                if not (getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False)):
                    continue
                if getattr(field, "related_model", None) is not User:
                    continue

                qs = model.objects.filter(**{field.name: admin})
                count = qs.count()
                if count:
                    admin_roots.append((model._meta.label, field.name, count))
                    collector.collect(qs)

        self.stdout.write(f"Keeping user: {admin.id} / {admin.username}")
        self.stdout.write(f"Deleting users: {non_admin_users.count()}")
        self.stdout.write(f"Admin-owned root records: {admin_roots}")
        self.stdout.write("Collected delete counts:")
        for model, objects in sorted(collector.data.items(), key=lambda item: item[0]._meta.label):
            self.stdout.write(f"  {model._meta.label}: {len(objects)}")

        with transaction.atomic():
            self._delete_legacy_control_tower_strategic_rows()
            deleted = collector.delete()

        self.stdout.write(self.style.SUCCESS(f"Deleted: {deleted}"))
        remaining_users = list(User.objects.values_list("id", "username", "is_superuser"))
        self.stdout.write(f"Remaining users: {remaining_users}")

    def _delete_legacy_control_tower_strategic_rows(self):
        table_name = "core_controltowerstrategicanalysis"
        with connection.cursor() as cursor:
            if table_name not in connection.introspection.table_names(cursor):
                return

            cursor.execute(
                f"""
                DELETE FROM {table_name}
                WHERE snapshot_id IN (
                    SELECT id FROM core_controltowersnapshot
                )
                """
            )
            self.stdout.write(f"Deleted legacy strategic analysis rows: {cursor.rowcount}")
