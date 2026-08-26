from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import DateTimeField
from django.utils import timezone


class Command(BaseCommand):
    help = "Convert naive datetime values in project tables to timezone-aware values."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many records would be fixed without writing changes.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        current_tz = timezone.get_current_timezone()

        total_fixed = 0
        total_checked = 0

        for model in apps.get_models():
            datetime_fields = [
                field for field in model._meta.fields
                if isinstance(field, DateTimeField)
            ]
            if not datetime_fields:
                continue

            model_fixed = 0
            field_names = [field.name for field in datetime_fields]

            try:
                rows = model.objects.values("pk", *field_names).iterator()
                for row in rows:
                    total_checked += 1
                    updates = {}

                    for field_name in field_names:
                        value = row.get(field_name)
                        if value and timezone.is_naive(value):
                            updates[field_name] = timezone.make_aware(value, current_tz)

                    if not updates:
                        continue

                    model_fixed += 1
                    total_fixed += 1

                    if dry_run:
                        continue

                    try:
                        with transaction.atomic():
                            model.objects.filter(pk=row["pk"]).update(**updates)
                    except Exception as exc:
                        self.stdout.write(
                            self.style.ERROR(
                                f"{model._meta.label} id={row.get('pk')} could not be saved: {exc}"
                            )
                        )
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"{model._meta.label}: skipped -> {exc}"))
                continue

            if model_fixed:
                action = "would be fixed" if dry_run else "fixed"
                self.stdout.write(self.style.SUCCESS(f"{model._meta.label}: {model_fixed} records {action}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Records checked: {total_checked}"))

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Records to fix: {total_fixed}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Records fixed: {total_fixed}"))
