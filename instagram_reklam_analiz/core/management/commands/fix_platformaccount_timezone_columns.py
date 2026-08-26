from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Convert PlatformAccount timestamp columns to timezone-aware PostgreSQL columns when needed."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write(self.style.WARNING("This command only applies to PostgreSQL."))
            return

        columns = ["created_at", "updated_at", "token_expiry", "last_sync"]
        converted = []

        with connection.cursor() as cursor:
            for column in columns:
                cursor.execute(
                    """
                    SELECT data_type
                    FROM information_schema.columns
                    WHERE table_name = 'core_platformaccount'
                      AND column_name = %s
                    """,
                    [column],
                )
                row = cursor.fetchone()
                if not row:
                    continue

                data_type = row[0]
                if data_type != "timestamp without time zone":
                    continue

                cursor.execute(
                    f"""
                    ALTER TABLE core_platformaccount
                    ALTER COLUMN {column}
                    TYPE timestamp with time zone
                    USING {column} AT TIME ZONE 'Europe/Istanbul'
                    """
                )
                converted.append(column)

        if converted:
            self.stdout.write(self.style.SUCCESS(f"Converted columns: {', '.join(converted)}"))
        else:
            self.stdout.write(self.style.SUCCESS("PlatformAccount timezone columns already look correct."))
