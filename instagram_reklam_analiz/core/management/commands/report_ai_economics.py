from collections import defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import AIOperationTariff, FeatureUsageLedger, OpenAITokenUsageLedger


def percentile(values, ratio):
    values = sorted(int(value or 0) for value in values)
    if not values:
        return 0
    index = min(len(values) - 1, max(0, round((len(values) - 1) * ratio)))
    return values[index]


class Command(BaseCommand):
    help = "AI operasyonlarinin token, kredi, basari ve P95 tuketim raporunu verir."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)

    def handle(self, *args, **options):
        days = max(1, min(int(options["days"] or 30), 365))
        since = timezone.now() - timedelta(days=days)
        tariffs = {row.key: row for row in AIOperationTariff.objects.all()}
        token_rows = OpenAITokenUsageLedger.objects.filter(used_at__gte=since).exclude(operation_key="")
        usage_rows = FeatureUsageLedger.objects.filter(created_at__gte=since)

        tokens_by_operation = defaultdict(list)
        calls_by_operation = defaultdict(int)
        for row in token_rows.only("operation_key", "total_tokens"):
            tokens_by_operation[row.operation_key].append(row.total_tokens)
            calls_by_operation[row.operation_key] += 1

        usage_by_operation = defaultdict(lambda: {"success": 0, "failed": 0, "credits": 0})
        for row in usage_rows.only("status", "metadata"):
            metadata = row.metadata or {}
            key = metadata.get("tariff_key") or ""
            if not key:
                continue
            bucket = usage_by_operation[key]
            bucket["failed" if row.status == FeatureUsageLedger.STATUS_FAILED else "success"] += 1
            if row.status != FeatureUsageLedger.STATUS_FAILED:
                bucket["credits"] += int(metadata.get("tariff_credits") or 0)

        keys = sorted(set(tokens_by_operation) | set(usage_by_operation))
        self.stdout.write(f"AI ekonomi raporu | son {days} gun")
        self.stdout.write("operation | success/failed | credits | calls | avg tokens/call | p95 tokens/call | tariff")
        for key in keys:
            values = tokens_by_operation[key]
            usage = usage_by_operation[key]
            average = round(sum(values) / len(values)) if values else 0
            tariff_cost = int(getattr(tariffs.get(key), "credit_cost", 0) or 0)
            self.stdout.write(
                f"{key} | {usage['success']}/{usage['failed']} | {usage['credits']} | "
                f"{calls_by_operation[key]} | {average} | {percentile(values, 0.95)} | {tariff_cost}"
            )
