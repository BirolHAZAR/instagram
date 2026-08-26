from django.conf import settings
from django.core.cache import caches
from django.core.management.base import BaseCommand
from django.db import connection
from django.urls import NoReverseMatch, get_resolver, reverse


class Command(BaseCommand):
    help = "Run production-readiness checks that complement Django's built-in check command."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Treat launch warnings as command errors.",
        )

    def handle(self, *args, **options):
        strict = options["strict"]
        warnings = []
        errors = []

        if settings.DEBUG:
            warnings.append("DEBUG=True. Canlı ortamda DEBUG=False olmalı.")

        if settings.SECRET_KEY == "django-insecure-default-key-change-this":
            errors.append("SECRET_KEY varsayılan geliştirme değeriyle çalışıyor.")

        allowed_hosts = set(settings.ALLOWED_HOSTS or [])
        if not allowed_hosts or allowed_hosts <= {"localhost", "127.0.0.1"}:
            warnings.append("ALLOWED_HOSTS canlı domainleri içermiyor gibi görünüyor.")

        if not getattr(settings, "ACCOUNT_RATE_LIMITS", None):
            errors.append("ACCOUNT_RATE_LIMITS tanımlı değil.")
        else:
            required_rate_limits = ["login", "login_failed", "signup", "reset_password"]
            missing = [key for key in required_rate_limits if not settings.ACCOUNT_RATE_LIMITS.get(key)]
            if missing:
                errors.append(f"ACCOUNT_RATE_LIMITS eksik veya kapalı: {', '.join(missing)}")

        cache_backend = caches["default"].__class__.__module__
        if settings.DEBUG is False and "locmem" in cache_backend.lower():
            warnings.append("Canlıda LocMem cache kullanılıyor; rate-limit çoklu worker'da paylaşılmaz.")

        if settings.DEBUG is False and not getattr(settings, "CACHE_REDIS_URL", ""):
            errors.append("CACHE_REDIS_URL tanimli degil. Canlida rate limit/cache icin Redis cache zorunlu.")

        celery_urls = {
            "CELERY_BROKER_URL": getattr(settings, "CELERY_BROKER_URL", ""),
            "CELERY_RESULT_BACKEND": getattr(settings, "CELERY_RESULT_BACKEND", ""),
            "CHANNEL_REDIS_URL": getattr(settings, "CHANNEL_REDIS_URL", ""),
        }
        for name, value in celery_urls.items():
            if not str(value or "").startswith("redis://"):
                errors.append(f"{name} Redis URL degil veya bos: {value!r}")

        expected_queues = {"default", "sync", "ai", "marketplace", "maintenance", "billing", "reports", "notifications"}
        configured_queues = {getattr(queue, "name", "") for queue in getattr(settings, "CELERY_TASK_QUEUES", [])}
        missing_queues = expected_queues - configured_queues
        if missing_queues:
            errors.append("Celery queue tanimlari eksik: " + ", ".join(sorted(missing_queues)))

        routes = getattr(settings, "CELERY_TASK_ROUTES", {}) or {}
        required_route_prefixes = [
            "core.tasks.sync_tasks.*",
            "core.tasks.marketplace_sync.*",
            "core.tasks.control_tower_ai.*",
            "core.tasks.admin_ops.sync_openai_usage",
        ]
        missing_routes = [route for route in required_route_prefixes if route not in routes]
        if missing_routes:
            warnings.append("Kritik Celery route eksikleri: " + ", ".join(missing_routes))

        beat_without_queue = [
            name
            for name, entry in (getattr(settings, "CELERY_BEAT_SCHEDULE", {}) or {}).items()
            if not (entry.get("options") or {}).get("queue")
        ]
        if beat_without_queue:
            warnings.append("Queue belirtilmemis beat gorevleri: " + ", ".join(beat_without_queue))

        if getattr(settings, "TAVILY_RATE_LIMIT", "") != "100/m":
            warnings.append(f"TAVILY_RATE_LIMIT beklenen 100/m degil: {getattr(settings, 'TAVILY_RATE_LIMIT', '')}")
        if int(getattr(settings, "TAVILY_MONTHLY_LIMIT", 0) or 0) <= 0:
            errors.append("TAVILY_MONTHLY_LIMIT pozitif olmali.")

        if not settings.EMAIL_BACKEND or "console" in settings.EMAIL_BACKEND.lower():
            warnings.append("EMAIL_BACKEND console görünüyor; canlıda SMTP/servis backend'i gerekli.")

        if not settings.CSRF_TRUSTED_ORIGINS and not settings.DEBUG:
            warnings.append("CSRF_TRUSTED_ORIGINS boş. Domain/proxy yapısına göre canlıda gerekli olabilir.")

        existing_tables = set(connection.introspection.table_names())
        if "core_membershipplan" in existing_tables:
            from core.models import AICreditPackage, MembershipPlan

            membership_columns = {
                column.name for column in connection.introspection.get_table_description(
                    connection.cursor(), "core_membershipplan"
                )
            }
            if "plan_type" not in membership_columns:
                warnings.append("MembershipPlan plan_type kolonu yok. Migration'lar uygulanmalı.")
            else:
                business_plans = set(
                    MembershipPlan.objects.filter(
                        plan_type=MembershipPlan.PLAN_TYPE_BUSINESS,
                        is_active=True,
                    ).values_list("name", flat=True)
                )
                missing_business_plans = {"silver", "gold", "platinum"} - business_plans
                if missing_business_plans:
                    warnings.append(
                        "Aktif ana paket eksik: " + ", ".join(sorted(missing_business_plans))
                        + ". `python manage.py create_plans` çalıştırılmalı."
                    )

            if "core_aicreditpackage" not in existing_tables:
                warnings.append("AI kredi paket tablosu yok. Migration'lar uygulanmalı.")
            elif not AICreditPackage.objects.filter(is_active=True).exists():
                warnings.append("Aktif AI kredi paketi yok. `python manage.py create_plans` çalıştırılmalı.")

        resolver = get_resolver()
        unexpected_reverse_errors = []
        named_url_count = 0
        no_arg_reverse_ok = 0
        for name in sorted(set(key for key in resolver.reverse_dict.keys() if isinstance(key, str))):
            named_url_count += 1
            try:
                reverse(name)
                no_arg_reverse_ok += 1
            except NoReverseMatch:
                continue
            except Exception as exc:
                unexpected_reverse_errors.append(f"{name}: {type(exc).__name__}: {exc}")

        if unexpected_reverse_errors:
            errors.append("Beklenmeyen URL reverse hataları:\n" + "\n".join(unexpected_reverse_errors[:20]))

        self.stdout.write(self.style.SUCCESS("Launch check özeti"))
        self.stdout.write(f"- Named URL sayısı: {named_url_count}")
        self.stdout.write(f"- Parametresiz reverse başarılı: {no_arg_reverse_ok}")
        self.stdout.write(f"- Cache backend: {cache_backend}")

        for warning in warnings:
            self.stdout.write(self.style.WARNING(f"UYARI: {warning}"))
        for error in errors:
            self.stdout.write(self.style.ERROR(f"HATA: {error}"))

        if errors or (strict and warnings):
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS("Launch check tamamlandı."))
