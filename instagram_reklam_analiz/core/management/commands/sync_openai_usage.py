from datetime import datetime, time
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Sum
from django.utils import timezone

from core.models import OpenAITokenUsageLedger, SaaSAICreditPool
from core.services.entitlements import get_saas_ai_credit_cycle


class Command(BaseCommand):
    help = "OpenAI organization usage API'den aylik token kullanimini SaaS AI havuzuna birebir senkronlar."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, help="Senkronlanacak yil. Varsayilan: mevcut yil.")
        parser.add_argument("--month", type=int, help="Senkronlanacak ay. Varsayilan: mevcut ay.")
        parser.add_argument(
            "--purchased",
            type=int,
            default=None,
            help="Aylik satin alinan token/kontor havuzu. Verilmezse mevcut havuz degeri korunur.",
        )

    def handle(self, *args, **options):
        api_key = getattr(settings, "OPENAI_USAGE_API_KEY", "") or getattr(settings, "OPENAI_API_KEY", "")
        if not api_key:
            raise CommandError("OPENAI_USAGE_API_KEY veya OPENAI_API_KEY tanimli degil.")

        today = timezone.localdate()
        requested_year = options["year"]
        requested_month = options["month"]
        if requested_month is not None and (requested_month < 1 or requested_month > 12):
            raise CommandError("Ay 1-12 araliginda olmali.")
        if (requested_year is None) != (requested_month is None):
            raise CommandError("Yil ve ay birlikte verilmelidir.")

        try:
            connection.ensure_connection()
        except Exception as exc:
            raise CommandError(f"Veritabani baglantisi kurulamadigi icin OpenAI senkronu baslatilmadi: {exc}") from exc

        local_tz = ZoneInfo(getattr(settings, "TIME_ZONE", "UTC"))
        if requested_year and requested_month:
            period_start_date = datetime(requested_year, requested_month, 1).date()
            if requested_month == 12:
                period_end_date = datetime(requested_year + 1, 1, 1).date()
            else:
                period_end_date = datetime(requested_year, requested_month + 1, 1).date()
        else:
            period_start_date, period_end_date = get_saas_ai_credit_cycle(today)

        start_dt = datetime.combine(period_start_date, time.min, tzinfo=local_tz)
        end_dt = datetime.combine(period_end_date, time.min, tzinfo=local_tz)

        total_tokens = 0
        next_page = None
        page_count = 0
        params = {
            "start_time": int(start_dt.timestamp()),
            "end_time": int(min(end_dt.timestamp(), timezone.now().timestamp())),
            "bucket_width": "1d",
            "group_by": ["model"],
        }

        while True:
            page_count += 1
            if page_count > 100:
                raise CommandError("OpenAI usage API sayfalama limiti asildi.")

            if next_page:
                params["page"] = next_page
            else:
                params.pop("page", None)

            response = requests.get(
                "https://api.openai.com/v1/organization/usage/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                params=params,
                timeout=60,
            )
            if response.status_code == 403:
                raise CommandError(
                    "OpenAI usage API yetkisi yok. API key icin api.usage.read scope'u veya admin/owner yetkisi gerekiyor."
                )
            if response.status_code >= 400:
                raise CommandError(f"OpenAI usage API hatasi {response.status_code}: {response.text[:500]}")

            payload = response.json()
            for bucket in payload.get("data", []):
                for result in bucket.get("results", []):
                    input_tokens = int(result.get("input_tokens") or 0)
                    output_tokens = int(result.get("output_tokens") or 0)
                    total_tokens += input_tokens + output_tokens

            next_page = payload.get("next_page")
            if not next_page:
                break

        pool, created = SaaSAICreditPool.objects.get_or_create(
            month=period_start_date,
            defaults={"purchased_credits": options["purchased"] or 1_000_000, "provider_name": "OpenAI"},
        )
        pool.provider_name = pool.provider_name or "OpenAI"
        previous_used = int(pool.used_credits or 0)
        if options["purchased"] is not None or created:
            pool.purchased_credits = options["purchased"] or pool.purchased_credits
        pool.used_credits = total_tokens
        pool.note = (
            "OpenAI organization usage API ile birebir senkronlandi. "
            f"Donem={period_start_date:%d.%m.%Y}-{period_end_date:%d.%m.%Y}, "
            f"onceki admin degeri={previous_used}, OpenAI API toplam={total_tokens}."
        )
        pool.save(update_fields=["provider_name", "purchased_credits", "used_credits", "note", "updated_at"])

        reconciliation_reference = f"openai.provider_reconciliation:{period_start_date:%Y-%m}"
        locally_recorded = OpenAITokenUsageLedger.objects.filter(
            used_at__gte=start_dt,
            used_at__lt=end_dt,
        ).exclude(reference=reconciliation_reference).aggregate(total=Sum("total_tokens"))["total"] or 0
        unassigned_tokens = max(0, total_tokens - int(locally_recorded))
        reconciliation, _ = OpenAITokenUsageLedger.objects.update_or_create(
            reference=reconciliation_reference,
            defaults={
                "user": None,
                "organization": None,
                "model_name": "provider-unattributed",
                "input_tokens": 0,
                "output_tokens": unassigned_tokens,
                "total_tokens": unassigned_tokens,
                "note": (
                    "OpenAI organizasyon toplamindan kullaniciya baglanabilen yerel kullanim "
                    f"cikarilarak hesaplandi. provider={total_tokens}, yerel={locally_recorded}, "
                    f"atanamayan={unassigned_tokens}."
                ),
                "used_at": start_dt,
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"{period_start_date:%d.%m.%Y}-{period_end_date:%d.%m.%Y} OpenAI kullanim senkronu OK: "
                f"api_kullanilan={total_tokens}, admin_kullanilan={pool.used_credits}, "
                f"kullaniciya_bagli={locally_recorded}, atanamayan={reconciliation.total_tokens}, "
                f"kalan={pool.remaining_credits}"
            )
        )
