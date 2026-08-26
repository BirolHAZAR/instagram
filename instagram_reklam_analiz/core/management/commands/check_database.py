from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, OperationalError, connections


class Command(BaseCommand):
    help = "Checks that Django can connect to the configured default database."

    def handle(self, *args, **options):
        connection = connections[DEFAULT_DB_ALIAS]
        settings = connection.settings_dict
        host = settings.get("HOST") or "localhost"
        port = settings.get("PORT") or "default"
        name = settings.get("NAME") or ""
        user = settings.get("USER") or ""

        try:
            connection.ensure_connection()
        except OperationalError as exc:
            raise CommandError(
                "PostgreSQL baglantisi kurulamadi.\n"
                f"  Host: {host}\n"
                f"  Port: {port}\n"
                f"  Database: {name}\n"
                f"  User: {user}\n\n"
                "PostgreSQL servisinin calistigindan ve .env icindeki "
                "DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD degerlerinin "
                "dogru oldugundan emin olun.\n\n"
                f"Ayrinti: {exc}"
            ) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"PostgreSQL baglantisi hazir: {user}@{host}:{port}/{name}"
            )
        )
